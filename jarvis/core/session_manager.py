"""Sessions Jarvis, leurs Contexts, et liaisons Board -> conversation (board-session S03, session-context S03).

Core possède les Sessions (06 section A/C). Ce service est leur seule porte
d'écriture : les routes `/v1/sessions*` (et plus tard le Control Center et MCP
par leur proxy) passent par lui, jamais par le dépôt. Toutes les règles
(Session close immuable, une liaison par couple, un seul foreground) sont
celles des transitions pures de `jarvis.domain.workspace_board`.

Ce que fait cette Slice :

- **Démarrage de Core = reprise** (`start`, D02 / D-SESS du handoff
  session-context-recording). La Session restée ouverte est reprise : même
  `jarvis_session_id`, même Board actif, même conversation de la liaison
  active ; ses liaisons sont réconciliées (`resume_session_bindings`) et rien
  n'est écrit quand la base est déjà cohérente (idempotent). Aucun redémarrage
  ne crée ni ne ferme de Session. Sans Session ouverte, une Session s'ouvre sur
  le dernier Board actif (`default` s'il est archivé ou absent), avec sa
  liaison foreground, une **conversation Core neuve** et son premier Context
  actif. Seule exception : la toute première Session de la base adopte la
  conversation Core la plus récente (06 section H).
- **Contexts** : la Session ouverte a toujours un Context actif
  (`ensure_context`, adopté pour une Session d'avant les Contexts) dont le
  dossier est créé par le port `ContextWorkspaceStore`. Un échec de dossier ou
  de lecture n'arrête jamais Core (journalisé, réessayé au prochain accès).
  Service : `current_context`, `list_contexts`, `create_context` (relais
  explicite `handoff.md`, jamais de copie), `activate_context`, et
  `session_context(conversation)`, le bloc borné de chaque tour du cerveau
  (`docs/session-context.md`).
- **Ledger d'activité** (Slice 04, `docs/artifacts.md`) : chaque ouverture,
  reprise (une fois par démarrage), fermeture de Session et chaque création,
  activation ou endormissement de Context écrit ses événements
  (`session.*`, `context.*`) **dans la même transaction** que ses lignes
  (`commit_switch` / `commit_contexts` / adoption, paramètre `activity`).
- `current()` : la Session ouverte et la liaison de son Board actif (Voice y lit
  sa conversation, `GET /v1/sessions/current`).
- `start_new_session()` : **seule frontière** de Session. Ferme la Session
  ouverte (`new_session`) et en ouvre une neuve sur le **même** Board actif,
  avec une conversation neuve, en une seule transaction (`commit_switch`) qui
  endort aussi le Context actif de l'ancienne et crée celui de la neuve.
  Boards, jobs et mode d'interaction ne sont pas touchés.
- `binding_for(session, board)` : liaison du couple, créée paresseusement
  (`suspended`). Aucune promotion ici : la bascule et la promotion sont la
  Slice 04b.

**`agent_cli` provisoire.** Core ne sait pas quel CLI d'agent le Control
Center fera tourner ; tant que le pool (Slice 04a) ne l'a pas rapporté
(`record_agent`, `POST /v1/sessions/bindings/report`, ou la réponse de
l'activation en 04b), les liaisons portent `PENDING_AGENT_CLI`.

**Nouvelle Session côté Control Center (04a).** `/api/agent/restart
{new_conversation:true}` appelle `POST /v1/sessions/new` : la transaction
ci-dessous active elle-même le CLI neuf sur le Control Center (reprise QA 04a),
qui ne le redémarre pas une seconde fois ; l'ancien est rétrogradé sans être tué.

**Nouvelle Session demandée à Core (04b).** Sous `SpeechAuthority.lock` (le
verrou de la bascule de Board) : la Session neuve et sa liaison sont
préparées sans rien écrire, `host.activate(liaison neuve)` met un CLI neuf au
premier plan (échec : `board_activation_failed`, rien n'est écrit), puis une
seule transaction ferme l'ancienne et ouvre la neuve (échec : l'ancienne
liaison est rétablie sur l'hôte, `board_switch_rolled_back`), l'autorité de
parole passe à la liaison neuve et `board.voice_binding.changed` est publié.

**Démarrage** : l'autorité de parole est posée sur la liaison active de la
Session reprise (ou neuve) ; `BoardService.align_host()` (tâche de fond) la met
au premier plan de l'hôte, qui garde son CLI vivant ou le reprend par
`agent_session_id`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.core.board_service import BoardService, activate_on_host, publish_voice_binding, restore_on_host
from jarvis.core.session_contexts import ensure_context
from jarvis.core.speech_authority import SpeechAuthority
from jarvis.core.v2_services import ConversationService
from jarvis.domain.brain_context import (
    MAX_BRAIN_CONTEXT_SUMMARY_BYTES, MAX_BRAIN_DORMANT_CONTEXTS, BrainBoardContext, BrainDormantContext,
    BrainSessionContext,
)
from jarvis.domain.session_activity import (
    ActivityKind, context_dormant_events, context_event, context_transition_events, session_event,
)
from jarvis.domain.session_context import (
    SessionContext, SessionContextError, SessionContextErrorCode, activate_context,
    create_context, dormant_contexts_of_closed_session,
)
from jarvis.domain.v2 import utc_now
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, Board, BoardConversationBinding, BoardError, BoardErrorCode, BoardStatus, BrainLifecycle,
    JarvisSession, SessionEndReason, close_session_with_bindings, ensure_open, find_binding, mark_opened,
    new_binding, open_session, promote_binding, record_agent_session, resume_session_bindings, visit_board,
)
from jarvis.ports.session_context import ContextRepository, ContextWorkspaceError, ContextWorkspaceStore
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.workspace_board import HOST_UNCHANGED, HOST_UNKNOWN, BoardActivation, BoardBrainHost, BoardRepository

#: `agent_cli` des liaisons tant que le Control Center ne l'a pas rapporté (Slice 04a).
PENDING_AGENT_CLI = "pending"
#: Historique `GET /v1/sessions` : défaut et plafond de `limit`.
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100
#: Entrées du cache conversation -> Board (`board_of`).
_BOARD_OF_CACHE = 512
#: Texte de relais d'un Context (`handoff.md`), en caractères : un résumé
#: choisi, pas une copie (D05). Refusé au-delà, jamais tronqué.
MAX_HANDOFF_SUMMARY_CHARS = 8_000


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


@dataclass(frozen=True, slots=True)
class ContextView:
    """Un Context et son dossier absolu ; `workspace_error` : code stable si le dossier manque."""

    context: SessionContext
    workspace_path: str
    workspace_error: str | None = None
    #: `handoff.md` écrit par `create_context` (chemin absolu), ou son code d'échec.
    handoff_path: str | None = None
    handoff_error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"context": self.context.to_payload(), "workspace_path": self.workspace_path}
        for key in ("workspace_error", "handoff_path", "handoff_error"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


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
        contexts: ContextRepository | None = None,
        workspaces: ContextWorkspaceStore | None = None,
    ) -> None:
        self._repo = repository
        # Contexts de Session (handoff session-context-recording, Slice 03).
        # Absents (tests d'avant) : aucune Session n'a de Context, rien ne change.
        if (contexts is None) != (workspaces is None):
            raise ValueError("contexts and workspaces go together")
        self._contexts = contexts
        self._workspaces = workspaces
        #: Dernier échec de dossier dit, par Context : journalisé au changement, pas à chaque tour.
        self._workspace_failures: dict[str, str] = {}
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
        #: Rappels après un changement de Session ou de Context actif (Slice 05 :
        #: le propriétaire des captures note qu'une capture en cours le traverse).
        self._association_listeners: list[Callable[[str], Awaitable[None]]] = []

    def add_association_listener(self, listener: Callable[[str], Awaitable[None]]) -> None:
        """`listener(reason)` est appelé après chaque Context créé ou réactivé et chaque nouvelle Session.

        Appelé hors verrou, après le commit ; une erreur est journalisée, jamais
        rendue à l'appelant de la transition (elle a déjà eu lieu).
        """

        self._association_listeners.append(listener)

    async def _notify_association(self, reason: str) -> None:
        for listener in tuple(self._association_listeners):
            try:
                await listener(reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: logged, the transition is already committed
                self._trace("core.session.listener_failed", f"Rappel de changement de Context en échec : "
                            f"{type(exc).__name__}: {str(exc)[:200]}", level="error",
                            data={"reason": reason, "exception_type": type(exc).__name__})

    @property
    def started(self) -> bool:
        return self._started

    # ------------------------------------------------------------ démarrage

    async def start(self) -> SessionView:
        """Au démarrage de Core, après `BoardService.ensure_default()` et avant toute route.

        **Reprise** (D02, D-SESS) : une Session restée ouverte par la vie
        précédente est reprise telle quelle — même `jarvis_session_id`, même
        Board actif, même conversation de la liaison active —, ses liaisons
        réconciliées (`resume_session_bindings`). Aucune Session n'est créée ni
        close par un redémarrage ; `start_new_session()` est la seule frontière.
        Idempotent : un second appel ne réécrit rien.

        Sans Session ouverte (base neuve, ou arrêt après une fermeture), une
        Session s'ouvre sur le dernier Board actif. La conversation Core la plus
        récente est adoptée **exactement** quand aucune Session n'a jamais
        existé (`list_sessions(limit=1)` vide), dans le même `commit_switch`
        que la première Session (reprise QA Slice 03 board-session). Lève si la
        base refuse : Core ne démarre pas sans Session, sinon Voice n'aurait
        pas de conversation de vérité.

        Puis le Context actif de la Session est garanti (adopté pour une
        Session d'avant les Contexts) et son dossier créé ; un échec ici est
        journalisé et **n'empêche pas** Core de servir (voir `_ensure_context`).
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
            await self._ensure_context(view.session, origin="core_start")
        self._remember(view.binding)
        if self._authority is not None:
            self._authority.set(view.binding)
        return view

    async def _open_at_start(self) -> SessionView:
        current = await self._repo.current_session()
        if current is not None:
            return await self._resume(current)
        newest = tuple(await self._repo.list_sessions(limit=1))
        # Première Session de cette base : la conversation vocale en cours
        # survit à la mise à jour (06 section H). Jamais plus ensuite.
        adopt_latest_conversation = not newest
        board = await self._start_board(newest[0] if newest else None)
        now = self._clock()
        conversation_id, adopted = await self._start_conversation(adopt_latest_conversation)
        view = self._open(board, conversation_id=conversation_id, now=now)
        contexts = (create_context(view.session, (), now=now).active,) if self._contexts is not None else ()
        # Ledger d'activité (Slice 04) : écrit dans la même transaction que la Session.
        sid = view.session.jarvis_session_id
        activity = (session_event(ActivityKind.SESSION_OPENED, sid, now=now, origin="core_start",
                                  context_id=contexts[0].context_id if contexts else None),
                    *(context_event(ActivityKind.CONTEXT_CREATED, sid, c.context_id, now=now, origin="core_start",
                                    extra={"context_origin": c.origin.value}) for c in contexts))
        await self._repo.commit_switch(sessions=(view.session,), boards=(), bindings=(view.binding,), contexts=contexts,
                                       activity=activity)
        self._trace("core.session.opened", "Session ouverte au démarrage de Core",
                    data={"jarvis_session_id": view.session.jarvis_session_id, "board_id": board.board_id,
                          "conversation_id": conversation_id, "adopted_conversation": adopted, "origin": "core_start",
                          "context_id": contexts[0].context_id if contexts else None})
        return view

    async def _resume(self, session: JarvisSession) -> SessionView:
        """Reprendre la Session ouverte (D-SESS). N'écrit que ce que la réconciliation change.

        - Board actif archivé ou absent (base réécrite ailleurs) : la Session
          visite le Board de repli, comme une bascule (`last_board_unavailable`) ;
        - liaison du Board actif absente : recréée avec une conversation neuve
          (`core.session.binding_rebuilt`, warning) plutôt que d'empêcher Core
          de démarrer ;
        - liaisons : `resume_session_bindings` (la liaison active reste ou
          redevient foreground, tout autre foreground est suspendu).
        """

        now = max(self._clock(), session.started_at)
        bindings = tuple(await self._repo.list_bindings(session.jarvis_session_id))
        board = await self._start_board(session)
        sessions: tuple[JarvisSession, ...] = ()
        if board.board_id != session.active_board_id:
            session = visit_board(session, board)
            sessions = (session,)
        rebuilt: BoardConversationBinding | None = None
        if find_binding(bindings, session.jarvis_session_id, board.board_id) is None:
            conversation = await self._conversations.create()
            rebuilt = new_binding(session, board, conversation_id=conversation.id, agent_cli=PENDING_AGENT_CLI,
                                  now=now, existing=bindings)
            bindings = (*bindings, rebuilt)
            self._trace("core.session.binding_rebuilt",
                        "Liaison du Board actif absente à la reprise : recréée avec une conversation neuve",
                        level="warning", data={"jarvis_session_id": session.jarvis_session_id,
                                               "board_id": board.board_id, "conversation_id": conversation.id})
        changed = {binding.key: binding for binding in ((rebuilt,) if rebuilt is not None else ())}
        changed.update((binding.key, binding) for binding in resume_session_bindings(session, bindings, now=now))
        # Ledger (Slice 04) : une reprise par démarrage de Core, pas par appel
        # répété de `start()` (idempotent), dans la transaction de réconciliation.
        activity = ()
        if not self._started:
            active = await self._contexts.active_context(session.jarvis_session_id) if self._contexts else None
            activity = (session_event(ActivityKind.SESSION_RESUMED, session.jarvis_session_id, now=now,
                                      origin="core_start", context_id=active.context_id if active else None),)
        if sessions or changed or activity:
            await self._repo.commit_switch(sessions=sessions, boards=(), bindings=tuple(changed.values()),
                                           activity=activity)
        final = tuple(changed.get(binding.key, binding) for binding in bindings)
        binding = find_binding(final, session.jarvis_session_id, board.board_id)
        assert binding is not None  # créée ci-dessus si elle manquait
        self._trace("core.session.resumed", "Session ouverte reprise au démarrage de Core",
                    data={"jarvis_session_id": session.jarvis_session_id, "board_id": board.board_id,
                          "conversation_id": binding.conversation_id, "agent_cli": binding.agent_cli,
                          "has_agent_session_id": binding.agent_session_id is not None,
                          "reconciled_bindings": len(changed), "board_fallback": bool(sessions)})
        return SessionView(session, binding)

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

    async def start_new_session(self, *, expected_session_id: str | None = None,
                                origin: str = "protocol") -> tuple[JarvisSession, SessionView]:
        """Ferme la Session ouverte (`new_session`) et en ouvre une neuve sur le même Board actif.

        Rend `(Session close, vue de la Session neuve)`.

        Une seule transaction : ancienne Session et ses liaisons closes, Session
        neuve et sa liaison foreground. La conversation neuve est créée avant ;
        si l'écriture échoue elle reste orpheline, sans effet (aucune liaison ne
        la désigne). `expected_session_id` : garde d'un appelant qui a vu une
        Session précise ; si elle n'est plus l'ouverte (double clic, deux
        onglets), `session_closed` au lieu d'une seconde Session neuve.

        Avec un hôte (Slice 04b, voir l'en-tête du module) :
        la liaison neuve est activée sur l'hôte **avant** l'écriture, et
        l'autorité de parole la suit après.
        """

        transition = self._authority.lock if self._authority is not None else contextlib.nullcontext()
        async with transition:
            return await self._start_new_session_locked(expected_session_id, origin, self._host is not None)

    async def _start_new_session_locked(self, expected_session_id: str | None, origin: str,
                                        with_host: bool) -> tuple[JarvisSession, SessionView]:
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
        if with_host:
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
            closed, closed_bindings, view = await self._commit_new_session(current, view, activation, origin)
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
        await self._notify_association("new_session")
        return closed, view

    async def _commit_new_session(
        self, current: JarvisSession, view: SessionView, activation: BoardActivation | None, origin: str,
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
            dormanted: tuple[SessionContext, ...] = ()
            born: tuple[SessionContext, ...] = ()
            if self._contexts is not None:
                # Même transaction que la fermeture : l'actif de l'ancienne
                # Session s'endort, la neuve naît avec son propre Context (D03).
                old = await self._contexts.list_contexts(still.jarvis_session_id)
                dormanted = dormant_contexts_of_closed_session(closed, old, now=now)
                born = (create_context(view.session, (), now=now).active,)
            contexts = (*dormanted, *born)
            new_sid = view.session.jarvis_session_id
            # Ledger (Slice 04), même transaction : l'ancien Context s'endort,
            # l'ancienne Session se ferme, la neuve s'ouvre avec son Context.
            activity = (*context_dormant_events(dormanted, now=now, origin=origin),
                        session_event(ActivityKind.SESSION_CLOSED, closed.jarvis_session_id, now=now, origin=origin),
                        session_event(ActivityKind.SESSION_OPENED, new_sid, now=now, origin=origin,
                                      context_id=born[0].context_id if born else None),
                        *(context_event(ActivityKind.CONTEXT_CREATED, new_sid, c.context_id, now=now, origin=origin,
                                        extra={"context_origin": c.origin.value}) for c in born))
            await self._repo.commit_switch(sessions=(closed, view.session), boards=(),
                                           bindings=(*closed_bindings, binding), contexts=contexts,
                                           activity=activity)
            if contexts:
                self._trace("core.context.created", "Context de la Session neuve créé",
                            data={"jarvis_session_id": view.session.jarvis_session_id,
                                  "context_id": contexts[-1].context_id, "origin": "new_session",
                                  "dormanted": [c.context_id for c in contexts[:-1]]})
                self._workspace(contexts[-1])
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

    def cached_board_of(self, conversation_id: str) -> str | None:
        """`board_of` sans E/S : le cache des liaisons seulement (Slice 07, `BoardAttributingSink`).

        Toute liaison créée ou relue y passe (`_remember`) ; une conversation
        absente du cache rend `None` sans rien lire.
        """

        return self._board_of.get(conversation_id)

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

    # ------------------------------------------------------------ Contexts (Slice 03 session-context)

    async def _ensure_context(self, session: JarvisSession, *, origin: str) -> ContextView | None:
        """Le Context actif de la Session ouverte, adopté s'il n'existe pas, et son dossier. Ne lève pas.

        Politique d'échec (Slice 03) : Core **continue de servir**. Une Session
        sans Context lisible ou sans dossier n'empêche ni la voix, ni les Boards,
        ni un tour : le tour part avec un bloc `session_context` dégradé
        (`workspace_error`) ou sans bloc, l'échec est journalisé avec un code
        stable, et tout accès suivant (chaque tour) réessaie. Bloquer Core pour
        un dossier serait couper la fonction vocale pour une commodité.
        """

        if self._contexts is None:
            return None
        try:
            ensured = await ensure_context(self._contexts, session, now=max(self._clock(), session.started_at))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - capture: said with its code, retried at the next access
            self._trace("core.context.ensure_failed",
                        f"Context actif de la Session illisible : {type(exc).__name__}: {str(exc)[:200]}",
                        level="error", data={"jarvis_session_id": session.jarvis_session_id, "origin": origin,
                                             "code": _code_of(exc), "exception_type": type(exc).__name__})
            return None
        if ensured is None:
            return None
        if ensured.adopted:
            self._trace("core.context.adopted", "Context par défaut adopté pour la Session ouverte",
                        data={"jarvis_session_id": session.jarvis_session_id,
                              "context_id": ensured.context.context_id, "origin": origin})
        path, error = self._workspace(ensured.context)
        return ContextView(ensured.context, path, error)

    def _workspace(self, context: SessionContext) -> tuple[str, str | None]:
        """Créer ou retrouver le dossier du Context ; `(chemin absolu, code d'échec ou None)`. Ne lève pas."""

        assert self._workspaces is not None
        try:
            expected = str(self._workspaces.expected_path(context.jarvis_session_id, context.context_id))
            workspace = self._workspaces.ensure(context.jarvis_session_id, context.context_id)
        except (ContextWorkspaceError, SessionContextError, OSError) as exc:
            code = _code_of(exc)
            if self._workspace_failures.get(context.context_id) != code:
                self._workspace_failures[context.context_id] = code
                self._trace("core.context.workspace_failed",
                            f"Dossier du Context indisponible : {str(exc)[:300]}", level="error",
                            data={"jarvis_session_id": context.jarvis_session_id, "context_id": context.context_id,
                                  "code": code, "path": expected})
            return expected, code
        if self._workspace_failures.pop(context.context_id, None) is not None or workspace.created:
            self._trace("core.context.workspace_ready", "Dossier du Context prêt",
                        data={"jarvis_session_id": context.jarvis_session_id, "context_id": context.context_id,
                              "created": workspace.created, "path": str(workspace.path)})
        return str(workspace.path), None

    def _require_contexts(self) -> ContextRepository:
        if self._contexts is None:
            raise SessionContextError(SessionContextErrorCode.INVALID_CONTEXT, "session contexts are not enabled")
        return self._contexts

    async def _open_session(self) -> JarvisSession:
        session = await self._repo.current_session()
        if session is None:
            raise BoardError(BoardErrorCode.SESSION_NOT_FOUND, "no session is open")
        return session

    async def current_context(self) -> ContextView:
        """Le Context actif de la Session ouverte (adopté au besoin) et son dossier.

        `session_not_found` sans Session ouverte ; une base illisible lève
        (`ContextStoreError`), comme toute lecture de Session.
        """

        contexts = self._require_contexts()
        session = await self._open_session()
        ensured = await ensure_context(contexts, session, now=max(self._clock(), session.started_at))
        assert ensured is not None  # Session ouverte
        path, error = self._workspace(ensured.context)
        return ContextView(ensured.context, path, error)

    async def context_brief_payload(self) -> dict[str, Any] | None:
        """`context` de `GET /v1/sessions/current` : Context actif, dossier, `sessions_root`. `None` sans Contexts."""

        if self._contexts is None:
            return None
        view = await self.current_context()
        assert self._workspaces is not None
        return {**view.to_payload(), "sessions_root": str(self._workspaces.sessions_root())}

    def trace_context_failure(self, exc: BaseException, *, origin: str) -> None:
        """Dire un échec de lecture du Context rencontré par un appelant (route), avec son code."""

        self._trace("core.context.read_failed", f"Context actif illisible : {type(exc).__name__}: {str(exc)[:200]}",
                    level="error", data={"origin": origin, "code": _code_of(exc),
                                         "exception_type": type(exc).__name__})

    async def list_contexts(self) -> tuple[SessionContext, ...]:
        """Les Contexts de la Session ouverte, du plus ancien au plus récent. Lecture seule."""

        session = await self._open_session()
        return tuple(await self._require_contexts().list_contexts(session.jarvis_session_id))

    async def create_context(self, *, title: str | None = None, handoff_summary: str | None = None,
                             source_context_ids: tuple[str, ...] | list[str] = (),
                             origin: str = "protocol") -> ContextView:
        """Nouveau Context actif dans la Session ouverte ; l'actif précédent s'endort (une transaction).

        Relais **explicite** (D05) : `source_context_ids` (Contexts de la même
        Session, `context_not_found` sinon) et `handoff_summary` (texte choisi
        par l'appelant, ≤ `MAX_HANDOFF_SUMMARY_CHARS`, `invalid_context` au-delà)
        deviennent `handoff.md` dans le dossier **neuf** : un résumé et des
        références, jamais une copie du dossier précédent. Sans l'un ni
        l'autre, aucun fichier n'est écrit. Le Context est validé avant
        l'écriture du fichier : un échec de `handoff.md` est rendu
        (`handoff_error`) et journalisé, le Context existe.
        """

        contexts = self._require_contexts()
        if handoff_summary is not None and (not isinstance(handoff_summary, str)
                                            or len(handoff_summary) > MAX_HANDOFF_SUMMARY_CHARS):
            raise SessionContextError(SessionContextErrorCode.INVALID_CONTEXT,
                                      f"handoff_summary must be text of at most {MAX_HANDOFF_SUMMARY_CHARS} characters")
        if isinstance(source_context_ids, str) or not isinstance(source_context_ids, (list, tuple)):
            raise SessionContextError(SessionContextErrorCode.INVALID_CONTEXT,
                                      "source_context_ids must be a list of context ids")
        async with self._lock:
            session = await self._open_session()
            existing = tuple(await contexts.list_contexts(session.jarvis_session_id))
            known = {c.context_id: c for c in existing}
            for source in source_context_ids:
                if source not in known:
                    raise SessionContextError(SessionContextErrorCode.CONTEXT_NOT_FOUND,
                                              f"source context {str(source)[:80]!r} is not in session "
                                              f"{session.jarvis_session_id}")
            now = max(self._clock(), session.started_at)
            transition = create_context(session, existing, now=now, title=title,
                                        source_context_ids=tuple(source_context_ids))
            await contexts.commit_contexts(transition.changed, activity=context_transition_events(
                transition, now=now, origin=origin, created=True))
        created = transition.active
        self._trace("core.context.created", "Context créé",
                    data={"jarvis_session_id": session.jarvis_session_id, "context_id": created.context_id,
                          "origin": origin, "dormanted": [transition.dormanted.context_id]
                          if transition.dormanted is not None else [],
                          "sources": len(created.source_context_ids), "handoff": bool(handoff_summary)})
        await self._notify_association("context_created")
        path, error = self._workspace(created)
        view = ContextView(created, path, error)
        if handoff_summary or created.source_context_ids:
            view = self._write_handoff(view, handoff_summary or "", [known[c] for c in created.source_context_ids])
        return view

    def _write_handoff(self, view: ContextView, summary: str, sources: list[SessionContext]) -> ContextView:
        context = view.context
        if view.workspace_error is not None:
            return ContextView(context, view.workspace_path, view.workspace_error, handoff_error=view.workspace_error)
        lines = [f"# Relais vers ce Context ({context.context_id})", "",
                 f"Écrit par Jarvis le {context.created_at.isoformat()} : un relais choisi, "
                 "pas une copie du dossier précédent. Les sources restent lisibles à leur place, "
                 "en lecture seule.", ""]
        if sources:
            lines.append("## Sources")
            for source in sources:
                title = f" « {source.title} »" if source.title else ""
                lines.append(f"- {source.context_id}{title} : {source.workspace_path.as_posix()}")
            lines.append("")
        if summary.strip():
            lines += ["## Résumé", "", summary.strip(), ""]
        try:
            assert self._workspaces is not None
            written = self._workspaces.write_handoff(Path(view.workspace_path), "\n".join(lines))
        except ContextWorkspaceError as exc:
            self._trace("core.context.handoff_failed", f"Relais du Context non écrit : {str(exc)[:300]}",
                        level="error", data={"context_id": context.context_id, "code": exc.code})
            return ContextView(context, view.workspace_path, None, handoff_error=exc.code)
        self._trace("core.context.handoff_written", "Relais du Context écrit",
                    data={"context_id": context.context_id, "sources": len(sources), "chars": len(summary)})
        return ContextView(context, view.workspace_path, None, handoff_path=str(written))

    async def activate_context(self, context_id: str, *, origin: str = "protocol") -> ContextView:
        """Réactivation explicite d'un Context dormant de la Session ouverte ; l'actif s'endort.

        Déjà actif : rien n'est écrit. Inconnu dans la Session : `context_not_found`.
        """

        contexts = self._require_contexts()
        async with self._lock:
            session = await self._open_session()
            existing = tuple(await contexts.list_contexts(session.jarvis_session_id))
            now = max(self._clock(), session.started_at)
            transition = activate_context(session, existing, context_id, now=now)
            if transition.changed:
                await contexts.commit_contexts(transition.changed, activity=context_transition_events(
                    transition, now=now, origin=origin, created=False))
        if transition.changed:
            self._trace("core.context.activated", "Context réactivé",
                        data={"jarvis_session_id": session.jarvis_session_id, "context_id": context_id,
                              "origin": origin, "dormanted": transition.dormanted.context_id
                              if transition.dormanted is not None else None})
            await self._notify_association("context_activated")
        path, error = self._workspace(transition.active)
        return ContextView(transition.active, path, error)

    def read_context_file(self, view: ContextView, name: str, max_bytes: int) -> tuple[str, bool]:
        """Fichier géré par Jarvis du dossier d'un Context (`summary.md`, curseur), borné. Lève
        `ContextWorkspaceError` ; lecture seule, donc permise sur un dormant (Slice 08)."""

        assert self._workspaces is not None
        return self._workspaces.read_file(Path(view.workspace_path), name, max_bytes)

    async def write_active_context_files(self, context_id: str,
                                         files: tuple[tuple[str, str], ...]) -> ContextView | None:
        """Écrire, dans l'ordre, des fichiers gérés par Jarvis dans le dossier du Context **s'il est
        encore l'actif** de la Session ouverte ; `None` sinon (rien n'est écrit).

        Sous le verrou des transitions (Slice 08, worker d'enrichissement) :
        un changement de Context ne peut pas s'intercaler entre la vérification
        et l'écriture, donc une écriture implicite n'atteint jamais un Context
        devenu dormant (invariant 4). Un dossier en échec rend `None` aussi
        (son code reste celui de `current_context`). Une écriture refusée lève
        `ContextWorkspaceError` : les fichiers déjà écrits le restent
        (l'appelant écrit le curseur en dernier).
        """

        contexts = self._require_contexts()
        async with self._lock:
            session = await self._repo.current_session()
            if session is None:
                return None
            active = await contexts.active_context(session.jarvis_session_id)
            if active is None or active.context_id != context_id:
                return None
            path, error = self._workspace(active)
            if error is not None:
                return None
            assert self._workspaces is not None
            for name, text in files:
                self._workspaces.write_file(Path(path), name, text)
            return ContextView(active, path, None)

    async def session_context(self, conversation_id: str | None) -> BrainSessionContext | None:
        """Bloc `session_context` d'un tour : le Context actif de la Session de sa conversation, borné.

        `None` : Contexts désactivés, conversation liée à aucune Session, ou
        Session close (une conversation d'une Session close n'a plus de Context
        actif). Le dossier est garanti à chaque appel (réessai de la politique
        d'échec) ; `summary.md` est lu borné et refusé s'il n'est pas un fichier
        ordinaire du dossier. Lève sur une base illisible : l'orchestrateur le
        trace et le tour part sans bloc.
        """

        if self._contexts is None or not conversation_id:
            return None
        binding = await self._repo.binding_by_conversation(conversation_id)
        if binding is None:
            return None
        session = await self._repo.get_session(binding.jarvis_session_id)
        if session is None or not session.is_open:
            return None
        view = await self._ensure_context(session, origin="turn")
        if view is None:
            return None
        summary, clipped = "", False
        if view.workspace_error is None:
            try:
                assert self._workspaces is not None
                summary, clipped = self._workspaces.read_summary(Path(view.workspace_path),
                                                                 MAX_BRAIN_CONTEXT_SUMMARY_BYTES)
            except ContextWorkspaceError as exc:
                self._trace("core.context.summary_unreadable", f"summary.md du Context non lu : {str(exc)[:300]}",
                            level="warning", data={"context_id": view.context.context_id, "code": exc.code})
        others = sorted((c for c in await self._contexts.list_contexts(session.jarvis_session_id) if not c.is_active),
                        key=lambda c: c.last_active_at, reverse=True)
        assert self._workspaces is not None
        return BrainSessionContext(
            jarvis_session_id=session.jarvis_session_id, context_id=view.context.context_id,
            title=view.context.title, workspace_path=view.workspace_path,
            sessions_root=str(self._workspaces.sessions_root()), workspace_error=view.workspace_error,
            summary=summary, summary_clipped=clipped,
            dormant=tuple(BrainDormantContext(c.context_id, c.title) for c in others[:MAX_BRAIN_DORMANT_CONTEXTS]),
            omitted_dormant=max(0, len(others) - MAX_BRAIN_DORMANT_CONTEXTS),
        )

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


def _code_of(exc: BaseException) -> str:
    """Code stable d'une erreur de Context, de dossier ou de magasin (`context_store_failed` par défaut)."""

    code = getattr(exc, "code", None)
    if code is None and isinstance(exc, OSError):
        return "context_workspace_failed"
    return str(getattr(code, "value", code) or "context_store_failed")
