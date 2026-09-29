"""Sessions Jarvis et liaisons Board -> conversation (handoff board-session, Slice 03).

Core possède les Sessions (06 section A/C). Ce service est leur seule porte
d'écriture : les routes `/v1/sessions*` (et plus tard le Control Center et MCP
par leur proxy) passent par lui, jamais par le dépôt. Toutes les règles
(Session close immuable, une liaison par couple, un seul foreground) sont
celles des transitions pures de `jarvis.domain.workspace_board`.

Ce que fait cette Slice :

- **Démarrage de Core = nouvelle Session** (`start`). La Session restée
  ouverte d'une vie précédente est close avec `end_reason=core_restart`, ses
  liaisons avec elle ; une Session neuve s'ouvre sur le dernier Board actif
  (`default` s'il est archivé ou absent), avec sa liaison foreground et une
  **conversation Core neuve**. Seule exception : la toute première Session de
  la base (aucune ligne de Session) adopte la conversation Core la plus
  récente, pour que la conversation vocale en cours survive à la mise à jour
  (06 section H).
- `current()` : la Session ouverte et la liaison de son Board actif (Voice y lit
  sa conversation, `GET /v1/sessions/current`).
- `start_new_session()` : ferme la Session ouverte (`new_session`) et en ouvre
  une neuve sur le **même** Board actif, avec une conversation neuve, en une
  seule transaction (`commit_switch`). Boards, jobs et mode d'interaction ne
  sont pas touchés.
- `binding_for(session, board)` : liaison du couple, créée paresseusement
  (`suspended`). Aucune promotion ici : la bascule et la promotion sont la
  Slice 04b.

**`agent_cli` provisoire.** Core ne sait pas quel CLI d'agent le Control
Center fera tourner ; tant que le pool (Slice 04a) ne l'a pas rapporté
(`record_agent`, `POST /v1/sessions/bindings/report`, ou la réponse de
l'activation en 04b), les liaisons portent `PENDING_AGENT_CLI`.

**Nouvelle Session côté Control Center (04a).** `/api/agent/restart
{new_conversation:true}` appelle `POST /v1/sessions/new {"activate_host": false}` ;
le pool donne un CLI neuf à la nouvelle liaison et rétrograde l'ancien sans le
tuer.

**Nouvelle Session demandée à Core (04b).** Sous `SpeechAuthority.lock` (le
verrou de la bascule de Board) : la Session neuve et sa liaison sont
préparées sans rien écrire, `host.activate(liaison neuve)` met un CLI neuf au
premier plan (échec : `board_activation_failed`, rien n'est écrit), puis une
seule transaction ferme l'ancienne et ouvre la neuve (échec : l'ancienne
liaison est rétablie sur l'hôte, `board_switch_rolled_back`), l'autorité de
parole passe à la liaison neuve et `board.voice_binding.changed` est publié.
`activate_host=False` : l'appelant (le Control Center) démarre lui-même le CLI
neuf, Core ne le réactive pas une seconde fois.

**Démarrage** : l'autorité de parole est posée sur la liaison de la Session
neuve ; `BoardService.align_host()` (tâche de fond) la met au premier plan de
l'hôte.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.core.board_service import BoardService, activate_on_host, publish_voice_binding, restore_on_host
from jarvis.core.speech_authority import SpeechAuthority
from jarvis.core.v2_services import ConversationService
from jarvis.domain.brain_context import BrainBoardContext
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, Board, BoardConversationBinding, BoardError, BoardErrorCode, BoardStatus, BrainLifecycle,
    JarvisSession, SessionEndReason, close_session_with_bindings, ensure_open, find_binding, mark_opened,
    new_binding, open_session, promote_binding, record_agent_session, visit_board,
)
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.workspace_board import HOST_UNCHANGED, HOST_UNKNOWN, BoardActivation, BoardBrainHost, BoardRepository

#: `agent_cli` des liaisons tant que le Control Center ne l'a pas rapporté (Slice 04a).
PENDING_AGENT_CLI = "pending"
#: Historique `GET /v1/sessions` : défaut et plafond de `limit`.
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100
#: Entrées du cache conversation -> Board (`board_of`).
_BOARD_OF_CACHE = 512


def _demoted_to(activation: BoardActivation | None) -> BrainLifecycle:
    """Ce que l'hôte a fait de l'ancien foreground ; `suspended` quand il ne le dit pas (ou sans hôte).

    Le cycle de vie des liaisons est une photographie prise aux transitions :
    le pool suspend ensuite seul un CLI de fond 60 s après son dernier
    sous-agent sans le redire à Core (`docs/boards.md`).
    """

    lifecycle = activation.previous_lifecycle if activation is not None else None
    if lifecycle is None or lifecycle is BrainLifecycle.FOREGROUND:
        return BrainLifecycle.SUSPENDED
    return lifecycle


@dataclass(frozen=True, slots=True)
class SessionView:
    """La Session et la liaison de son Board actif (celle qui porte la conversation de Voice)."""

    session: JarvisSession
    binding: BoardConversationBinding

    def to_payload(self) -> dict[str, Any]:
        return {"session": self.session.to_payload(), "binding": self.binding.to_payload()}


class SessionManager:
    """Porte unique des Sessions dans Core. Voir l'en-tête du module."""

    def __init__(
        self,
        repository: BoardRepository,
        *,
        boards: BoardService,
        conversations: ConversationService,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], datetime] = utc_now,
        authority: SpeechAuthority | None = None,
        host: BoardBrainHost | None = None,
        events: Any = None,
    ) -> None:
        self._repo = repository
        self._boards = boards
        self._conversations = conversations
        self._diagnostics = diagnostics
        self._clock = clock
        # Toute lecture-modification-écriture de Session/liaison : deux
        # « nouvelle Session » concurrentes (double clic, deux onglets) ne
        # ferment pas deux fois la même Session.
        self._lock = asyncio.Lock()
        self._started = False
        # Slice 04b : autorité de parole (verrou des transitions), hôte des
        # cerveaux (Control Center) et bus. Absents (tests d'avant) : une
        # nouvelle Session n'active rien et ne publie rien.
        self._authority = authority
        self._host = host
        self._events = events
        #: conversation Core -> Board (`None` : liée à aucun Board), pour la porte
        #: de parole et l'étiquetage du travail. Une liaison ne change jamais de
        #: conversation, et toute liaison créée passe par `_remember`, qui
        #: remplace une absence mémorisée : le cache ne se périme pas ; il est borné.
        self._board_of: dict[str, str | None] = {}

    @property
    def started(self) -> bool:
        return self._started

    # ------------------------------------------------------------ démarrage

    async def start(self) -> SessionView:
        """Au démarrage de Core, après `BoardService.ensure_default()` et avant toute route.

        La conversation Core la plus récente est adoptée **exactement** quand
        aucune Session n'a jamais existé (`list_sessions(limit=1)` vide), dans
        le même `commit_switch` que la première Session : la décision ne dépend
        plus de « ce passage a créé `default` », qui est validé avant et se
        perdait sur un arrêt brutal entre les deux ou sur une base où la Slice 02
        avait déjà créé `default` (reprise QA Slice 03). Lève si la base refuse :
        Core ne démarre pas sans Session, sinon Voice n'aurait pas de
        conversation de vérité.
        """

        async with self._lock:
            try:
                view = await self._open_at_start()
            except Exception as exc:
                self._trace("core.session.start_failed",
                            f"Session non ouverte au démarrage : {type(exc).__name__}: {str(exc)[:200]}",
                            level="error", data={"code": getattr(getattr(exc, "code", None), "value", "store_failed")})
                raise
            self._started = True
        self._remember(view.binding)
        if self._authority is not None:
            self._authority.set(view.binding)
        return view

    async def _open_at_start(self) -> SessionView:
        stale = await self._repo.current_session()
        newest = (stale,) if stale is not None else tuple(await self._repo.list_sessions(limit=1))
        # Première Session de cette base : la conversation vocale en cours
        # survit à la mise à jour (06 section H). Jamais plus ensuite.
        adopt_latest_conversation = not newest
        board = await self._start_board(newest[0] if newest else None)
        now = self._clock()
        sessions: list[JarvisSession] = []
        bindings: list[BoardConversationBinding] = []
        if stale is not None:
            # Horloge reculée depuis la vie précédente : la fermeture reste
            # valide (fin ≥ début) plutôt que d'empêcher Core de démarrer.
            closed, closed_bindings = close_session_with_bindings(
                stale, await self._repo.list_bindings(stale.jarvis_session_id),
                reason=SessionEndReason.CORE_RESTART, now=max(now, stale.started_at),
            )
            sessions.append(closed)
            bindings.extend(closed_bindings)
        conversation_id, adopted = await self._start_conversation(adopt_latest_conversation)
        view = self._open(board, conversation_id=conversation_id, now=now)
        await self._repo.commit_switch(sessions=(*sessions, view.session), boards=(), bindings=(*bindings, view.binding))
        if stale is not None:
            self._trace("core.session.closed", "Session précédente close (redémarrage de Core)",
                        data={"jarvis_session_id": stale.jarvis_session_id, "end_reason": "core_restart",
                              "bindings": len(bindings)})
        self._trace("core.session.opened", "Session ouverte au démarrage de Core",
                    data={"jarvis_session_id": view.session.jarvis_session_id, "board_id": board.board_id,
                          "conversation_id": conversation_id, "adopted_conversation": adopted, "origin": "core_start"})
        return view

    async def _start_board(self, newest: JarvisSession | None) -> Board:
        """Dernier Board actif (Session restée ouverte, sinon la plus récente) ; `default` s'il est
        archivé ou absent ; sinon le premier Board actif."""

        last = newest.active_board_id if newest is not None else DEFAULT_BOARD_ID
        board = await self._repo.get_board(last)
        if board is not None and board.status is BoardStatus.ACTIVE:
            return board
        self._trace("core.session.last_board_unavailable", "Dernier Board actif archivé ou absent : repli",
                    level="warning", data={"board_id": last, "found": board is not None})
        fallback = await self._repo.get_board(DEFAULT_BOARD_ID)
        if fallback is not None and fallback.status is BoardStatus.ACTIVE:
            return fallback
        listed = await self._repo.list_boards()
        if listed:
            return listed[0]
        raise BoardError(BoardErrorCode.BOARD_NOT_FOUND, "no active board to open a session on")

    async def _start_conversation(self, adopt_latest: bool) -> tuple[str, bool]:
        if adopt_latest:
            latest = await self._conversations.latest()
            if latest is not None:
                return latest.id, True
        return (await self._conversations.create()).id, False

    # ------------------------------------------------------------ lecture

    async def current(self) -> SessionView:
        """La Session ouverte et la liaison de son Board actif.

        `session_not_found` si aucune Session n'est ouverte (Core pas encore
        démarré) ; `binding_not_found` si la liaison du Board actif manque :
        chaque ouverture et chaque bascule l'écrivent dans la même transaction,
        son absence est une base abîmée, pas un cas à combler en silence.
        """

        session = await self._repo.current_session()
        if session is None:
            raise BoardError(BoardErrorCode.SESSION_NOT_FOUND, "no session is open")
        binding = find_binding(await self._repo.list_bindings(session.jarvis_session_id),
                               session.jarvis_session_id, session.active_board_id)
        if binding is None:
            raise BoardError(BoardErrorCode.BINDING_NOT_FOUND,
                             f"session {session.jarvis_session_id} has no binding for its active board "
                             f"{session.active_board_id}")
        return SessionView(session, binding)

    async def get(self, jarvis_session_id: str) -> JarvisSession:
        session = await self._repo.get_session(jarvis_session_id) if isinstance(jarvis_session_id, str) else None
        if session is None:
            raise BoardError(BoardErrorCode.SESSION_NOT_FOUND,
                             f"session {str(jarvis_session_id)[:80]!r} does not exist")
        return session

    async def history(self, *, limit: int = DEFAULT_HISTORY_LIMIT) -> tuple[JarvisSession, ...]:
        """Sessions, la plus récente d'abord. Lecture seule."""

        if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise BoardError(BoardErrorCode.INVALID_SESSION, f"limit must be an integer in 1..{MAX_HISTORY_LIMIT}")
        return tuple(await self._repo.list_sessions(limit=limit))

    # ------------------------------------------------------------ écriture

    async def start_new_session(self, *, expected_session_id: str | None = None, origin: str = "protocol",
                                activate_host: bool = True) -> tuple[JarvisSession, SessionView]:
        """Ferme la Session ouverte (`new_session`) et en ouvre une neuve sur le même Board actif.

        Rend `(Session close, vue de la Session neuve)`.

        Une seule transaction : ancienne Session et ses liaisons closes, Session
        neuve et sa liaison foreground. La conversation neuve est créée avant ;
        si l'écriture échoue elle reste orpheline, sans effet (aucune liaison ne
        la désigne). `expected_session_id` : garde d'un appelant qui a vu une
        Session précise ; si elle n'est plus l'ouverte (double clic, deux
        onglets), `session_closed` au lieu d'une seconde Session neuve.

        Avec un hôte et `activate_host` (Slice 04b, voir l'en-tête du module) :
        la liaison neuve est activée sur l'hôte **avant** l'écriture, et
        l'autorité de parole la suit après.
        """

        transition = self._authority.lock if self._authority is not None else contextlib.nullcontext()
        async with transition:
            return await self._start_new_session_locked(expected_session_id, origin,
                                                        activate_host and self._host is not None)

    async def _start_new_session_locked(self, expected_session_id: str | None, origin: str,
                                        activate_host: bool) -> tuple[JarvisSession, SessionView]:
        async with self._lock:
            current = await self._repo.current_session()
            if expected_session_id is not None:
                expected = await self.get(expected_session_id)
                ensure_open(expected)
            if current is None:
                raise BoardError(BoardErrorCode.SESSION_NOT_FOUND, "no session is open")
            board = await self._boards.get(current.active_board_id)
            previous = find_binding(await self._repo.list_bindings(current.jarvis_session_id),
                                    current.jarvis_session_id, current.active_board_id)
            conversation = await self._conversations.create()
            view = self._open(board, conversation_id=conversation.id, now=max(self._clock(), current.started_at))
        activation: BoardActivation | None = None
        if activate_host:
            assert self._host is not None
            # Hors du verrou des Sessions : l'hôte peut rapporter un CLI
            # (`record_agent`) pendant qu'il démarre celui-ci. Le verrou des
            # transitions, lui, est tenu : rien d'autre ne déplace la Session.
            try:
                activation = await activate_on_host(self._host, view.binding, self._trace, step="new_session")
            except BoardError as exc:
                if getattr(exc, "host_state", HOST_UNCHANGED) == HOST_UNKNOWN:
                    await restore_on_host(self._host, previous, self._trace, step="new_session_activation")
                raise
        try:
            closed, closed_bindings, view = await self._commit_new_session(current, view, activation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if activation is None:
                raise
            await restore_on_host(self._host, previous, self._trace, step="new_session_commit")
            self._trace("core.session.new_rolled_back",
                        f"Nouvelle Session annulée : {type(exc).__name__}: {str(exc)[:200]}", level="error",
                        data={"code": BoardErrorCode.BOARD_SWITCH_ROLLED_BACK.value,
                              "jarvis_session_id": current.jarvis_session_id, "exception_type": type(exc).__name__})
            raise BoardError(BoardErrorCode.BOARD_SWITCH_ROLLED_BACK,
                             f"new session rolled back: {type(exc).__name__}: {str(exc)[:200]}") from exc
        self._remember(view.binding)
        if self._authority is not None:
            self._authority.set(view.binding)
        self._trace("core.session.closed", "Session close (nouvelle Session demandée)",
                    data={"jarvis_session_id": closed.jarvis_session_id, "end_reason": "new_session",
                          "bindings": len(closed_bindings)})
        self._trace("core.session.opened", "Nouvelle Session ouverte",
                    data={"jarvis_session_id": view.session.jarvis_session_id, "board_id": board.board_id,
                          "conversation_id": conversation.id, "adopted_conversation": False, "origin": origin,
                          "host_activated": activation is not None})
        await publish_voice_binding(self._events, view.binding, reason="new_session")
        return closed, view

    async def _commit_new_session(
        self, current: JarvisSession, view: SessionView, activation: BoardActivation | None,
    ) -> tuple[JarvisSession, tuple[BoardConversationBinding, ...], SessionView]:
        """Relire puis écrire : les liaisons ont pu recevoir un rapport de CLI pendant l'activation."""

        async with self._lock:
            still = await self._repo.current_session()
            if still is None or still.jarvis_session_id != current.jarvis_session_id:
                raise BoardError(BoardErrorCode.SESSION_CLOSED,
                                 f"session {current.jarvis_session_id} is no longer the open session")
            now = max(self._clock(), still.started_at)
            closed, closed_bindings = close_session_with_bindings(
                still, await self._repo.list_bindings(still.jarvis_session_id),
                reason=SessionEndReason.NEW_SESSION, now=now, foreground_to=_demoted_to(activation),
            )
            binding = view.binding
            if activation is not None:
                binding = record_agent_session(binding, activation.agent_session_id, now=now,
                                               agent_cli=activation.agent_cli)
            await self._repo.commit_switch(sessions=(closed, view.session), boards=(),
                                           bindings=(*closed_bindings, binding))
        return closed, closed_bindings, SessionView(view.session, binding)

    async def commit_promotion(self, jarvis_session_id: str, board: Board,
                               activation: BoardActivation | None) -> tuple[JarvisSession, BoardConversationBinding]:
        """Étape 5 de la bascule (`BoardService.switch`) : une seule transaction SQLite.

        Session : `board` actif (visité à la première fois). Liaisons : celle de
        `board` promue foreground (avec le CLI et l'identifiant de reprise que
        l'hôte vient de rendre), l'ancienne rétrogradée à ce que l'hôte en a fait
        (`background_running` si elle travaille, `suspended` sinon). Board :
        `last_opened_at`. Tout est relu sous le verrou : un rapport de CLI arrivé
        entre-temps n'est pas écrasé.
        """

        async with self._lock:
            session = await self.get(jarvis_session_id)
            ensure_open(session)
            bindings = tuple(await self._repo.list_bindings(session.jarvis_session_id))
            target = find_binding(bindings, session.jarvis_session_id, board.board_id)
            if target is None:
                raise BoardError(BoardErrorCode.BINDING_NOT_FOUND,
                                 f"session {jarvis_session_id} has no binding for board {board.board_id}")
            now = self._clock()
            visited = visit_board(session, board)
            promoted = promote_binding(visited, bindings, target, now=now, demote_to=_demoted_to(activation))
            changed = []
            for before, after in zip(bindings, promoted):
                if after.key == target.key and activation is not None:
                    after = record_agent_session(after, activation.agent_session_id, now=now,
                                                 agent_cli=activation.agent_cli)
                if after != before:
                    changed.append(after)
            opened = mark_opened(board, now=now)
            await self._repo.commit_switch(sessions=(visited,), boards=(opened,), bindings=tuple(changed))
        binding = next(item for item in changed if item.key == target.key)
        self._remember(binding)
        return visited, binding

    async def record_activation(self, binding: BoardConversationBinding, activation: BoardActivation) -> None:
        """Enregistrer le CLI qu'une activation hors transition a rapporté (alignement au démarrage)."""

        await self.record_agent(binding.jarvis_session_id, binding.board_id, agent_cli=activation.agent_cli,
                                agent_session_id=activation.agent_session_id)

    async def board_of(self, conversation_id: str | None) -> str | None:
        """Le Board de cette conversation Core, `None` si elle n'est liée à aucun (conversation d'avant les Boards).

        Porte de parole (Board d'une parole retenue), étiquetage du travail des
        jobs Core (`JobService`). Une panne de lecture lève : l'appelant la trace.
        """

        if not conversation_id:
            return None
        if conversation_id in self._board_of:
            return self._board_of[conversation_id]
        binding = await self._repo.binding_by_conversation(conversation_id)
        if binding is None:
            self._cache(conversation_id, None)
            return None
        self._remember(binding)
        return binding.board_id

    async def board_context(self, conversation_id: str | None) -> BrainBoardContext | None:
        """Bloc `board` d'un tour : le Board de sa conversation, borné (`BrainBoardContext.from_board`).

        `None` pour une conversation liée à aucun Board. Lève sur une base
        illisible : l'orchestrateur le trace et le tour part sans bloc.
        """

        board_id = await self.board_of(conversation_id)
        if board_id is None:
            return None
        return BrainBoardContext.from_board(await self._boards.get(board_id))

    def _remember(self, binding: BoardConversationBinding) -> None:
        self._cache(binding.conversation_id, binding.board_id)

    def _cache(self, conversation_id: str, board_id: str | None) -> None:
        if len(self._board_of) >= _BOARD_OF_CACHE and conversation_id not in self._board_of:
            self._board_of.pop(next(iter(self._board_of)))
        self._board_of[conversation_id] = board_id

    async def binding_for(self, jarvis_session_id: str, board_id: str) -> BoardConversationBinding:
        """Liaison du couple `(Session, Board)`, créée à la première demande. A/B/A la retrouve.

        Session close : `session_closed`. Board archivé : `board_archived`.
        Une liaison créée ici est `suspended` avec une conversation neuve ; la
        rendre foreground est la bascule (Slice 04b).
        """

        async with self._lock:
            session = await self.get(jarvis_session_id)
            ensure_open(session)
            board = await self._boards.get(board_id)
            existing = await self._repo.list_bindings(session.jarvis_session_id)
            found = find_binding(existing, session.jarvis_session_id, board.board_id)
            if found is not None:
                return found
            if board.status is BoardStatus.ARCHIVED:
                # Même refus que `new_binding`, levé avant de créer une conversation qui resterait orpheline.
                raise BoardError(BoardErrorCode.BOARD_ARCHIVED, f"board {board.board_id} is archived")
            conversation = await self._conversations.create()
            binding = new_binding(session, board, conversation_id=conversation.id, agent_cli=PENDING_AGENT_CLI,
                                  now=self._clock(), existing=existing)
            await self._repo.save_binding(binding)
        self._remember(binding)
        self._trace("core.session.binding_created", "Liaison Board créée",
                    data={"jarvis_session_id": session.jarvis_session_id, "board_id": board.board_id,
                          "conversation_id": conversation.id})
        return binding

    async def record_agent(self, jarvis_session_id: str, board_id: str, *, agent_cli: str,
                           agent_session_id: str | None) -> BoardConversationBinding:
        """Le Control Center rapporte le CLI réel d'une liaison et son identifiant de reprise (Slice 04a).

        Liaison inconnue : `binding_not_found`. Une liaison close l'accepte (son
        CLI finit peut-être du travail) : la garde du magasin interdit seulement
        de la rouvrir ou de la remettre foreground. Rapport identique : rien
        n'est écrit.
        """

        async with self._lock:
            session = await self.get(jarvis_session_id)
            found = find_binding(await self._repo.list_bindings(session.jarvis_session_id),
                                 session.jarvis_session_id, board_id)
            if found is None:
                raise BoardError(BoardErrorCode.BINDING_NOT_FOUND,
                                 f"session {jarvis_session_id} has no binding for board {str(board_id)[:80]!r}")
            if found.agent_cli == agent_cli and found.agent_session_id == agent_session_id:
                return found
            updated = record_agent_session(found, agent_session_id, now=self._clock(), agent_cli=agent_cli)
            await self._repo.save_binding(updated)
        self._trace("core.session.agent_reported", "CLI de la liaison rapporté par le Control Center",
                    data={"jarvis_session_id": jarvis_session_id, "board_id": board_id, "agent_cli": agent_cli,
                          "has_agent_session_id": agent_session_id is not None})
        return updated

    # ------------------------------------------------------------ interne

    @staticmethod
    def _open(board: Board, *, conversation_id: str, now: datetime) -> SessionView:
        session = open_session(board, now=now)
        binding = new_binding(session, board, conversation_id=conversation_id, agent_cli=PENDING_AGENT_CLI, now=now)
        (foreground,) = promote_binding(session, (binding,), binding, now=now)
        return SessionView(session, foreground)

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not break a Session write
            pass
