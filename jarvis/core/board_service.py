"""Service Core des Boards de travail (handoff board-session, Slice 02 : partie stockage).

Core possède le magasin des Boards (06 section A). Ce service est la seule
porte d'écriture : les routes `/v1/boards*` (et, plus tard, le Control Center
et MCP par leur proxy) passent par lui, jamais par le dépôt. Les règles
(Board archivé non modifiable, Board actif non archivable, bornes) sont celles
des transitions pures de `jarvis.domain.workspace_board` ; rien n'est
redécidé ici.

Ce que fait cette Slice :

- lecture/création/édition/archivage, avec les gardes du domaine ;
- `ensure_default()` : migration idempotente de l'état mono-espace vers le
  Board `default` (06 section H), clé « table vide » ;
- **mode d'interaction dérivé du type** (D01, `docs/boards.md` › *Board type*) :
  le démarrage de Core (`source="board_restore"`) et chaque bascule
  (`source="board_switch"`) demandent à `InteractionModeService` le mode que
  désigne le type du Board actif (`board_kind_mode`, comportement
  `behaving_interaction_mode` : un Board Réunion se comporte en assistant).
  Aucun mode n'est stocké sur un Board et rien ne l'y écrit ; le type, lui, est
  fixé à la création (`board_kind_immutable`).

**Board actif (V1).** Il n'y a pas de pointeur séparé : le Board actif est
`active_board_id` de la Session ouverte (`jarvis_sessions`, persistée), et
`default` quand aucune Session n'est ouverte (avant le démarrage). Depuis la
Slice 03, Core ouvre une Session à chaque démarrage sur le dernier Board actif
(`jarvis/core/session_manager.py`). Un second pointeur serait une deuxième
vérité ; celui-ci est celle que 03/04b écrivent.

**Aucun autre écrivain du mode (Slice 01b).** `POST /v1/interaction-mode`
refuse toute demande (`interaction_mode_derived`), le Control Center, le
réglage MCP et le HUD n'écrivent plus rien. Le seul autre écrivain est une
lecture du Presentation Studio (`source="presentation_studio_run"`, en
processus), transitoire : elle restaure le mode d'avant, c'est-à-dire celui du
type du Board, et une bascule pendant la lecture l'emporte (`foreign_change`).
Une bascule vers le Board **déjà actif** (`switch_noop`, par le protocole ou
`board_switch` du cerveau ; le contrôle Boards de la page n'en envoie pas)
réapplique quand même le mode de son type (`source="board_switch"`,
idempotent : rien ne bouge s'il est déjà en vigueur). C'est une reprise de plus
quand une restauration du Studio a échoué (`mode_restore_failed`) ; le prix,
assumé, est qu'elle arrête une lecture du Studio qui tenait un mode transitoire
sur ce Board.

**Bascule de Board (Slice 04b, `switch`).** Transaction sous
`SpeechAuthority.lock` (le même que la nouvelle Session de `SessionManager`) :

1. valider (Session ouverte, Board existant et non archivé) ;
2. liaison du couple `(Session, Board)` retrouvée ou créée (`binding_for`) ;
3. `host.activate(cible)` (`POST /api/agent/bindings/activate`) ; échec :
   `board_activation_failed`, **rien** n'est écrit ;
4. mode dérivé du type du Board cible appliqué (`source="board_switch"`) ;
   un Board Réunion n'est jamais refusé (comportement assistant) ; échec :
   l'ancienne liaison est réactivée sur l'hôte, `board_switch_rolled_back` ;
5. `commit_switch` : Session (Board actif, visités), liaisons (promotion,
   rétrogradation), Board (`last_opened_at`) en **une** transaction ; échec :
   hôte et mode rétablis, `board_switch_rolled_back` ;
6. autorité de parole en mémoire déplacée ;
7. `board.switched` puis `board.voice_binding.changed` publiés.

Sans hôte (`host=None` : tests, Core sans Control Center) l'étape 3 et le
rétablissement de l'hôte sont sautés ; tout le reste est identique.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from jarvis.core.interaction_mode import InteractionModeService
from jarvis.core.speech_authority import BOARD_SWITCHED, BOARD_VOICE_BINDING_CHANGED, SpeechAuthority
from jarvis.domain._checks import preview
from jarvis.domain.interaction_mode import InteractionMode, InteractionModeError, behaving_interaction_mode
from jarvis.domain.v2 import ProtocolEnvelope, utc_now
from jarvis.domain.workspace_board import (
    DEFAULT_BOARD_ID, LEGACY_EMPTY_BOARD_KIND, Board, BoardConversationBinding, BoardError, BoardErrorCode,
    BoardKind, BoardStatus, JarvisSession, SceneRef,
    archive_board, board_kind_mode, create_board, default_board, parse_board_kind_input, update_board,
)
from jarvis.ports.v2 import DiagnosticSink
from jarvis.ports.workspace_board import HOST_UNCHANGED, HOST_UNKNOWN, BoardActivation, BoardBrainHost, BoardRepository

if TYPE_CHECKING:  # import circulaire à l'exécution : SessionManager dépend de BoardService
    from jarvis.core.session_manager import SessionManager

#: Sources de `InteractionModeService.request` émises par ce service : le mode
#: dérivé du type du Board actif, au démarrage de Core et à chaque bascule.
BOARD_RESTORE_SOURCE = "board_restore"
BOARD_SWITCH_SOURCE = "board_switch"

#: Champs éditables d'un Board par `update` (routes, MCP, UI). Ni mode (dérivé
#: du type), ni type : `board_kind` est fixé à la création et un `PATCH` qui le
#: porte est refusé `board_kind_immutable` (D02).
EDITABLE_FIELDS = frozenset({
    "title", "context_summary", "task_refs", "artifact_refs", "project_refs", "scene_ref", "runtime_metadata",
})
#: Champs de `create` : les éditables, plus le type (défaut `assistant`).
CREATE_FIELDS = EDITABLE_FIELDS | {"board_kind"}
#: Statut du comportement d'un Board Réunion, dit dans les traces de mode :
#: valide et ouvrable, comportement assistant tant que la réunion n'existe pas.
MEETING_PLANNED = "meeting_planned"

_TRACE_EXCEPTION_CHARS = 200

#: Refus que l'hôte rend lui-même, avec leur code : relevés tels quels.
_HOST_REFUSALS = frozenset({BoardErrorCode.SESSION_CLOSED, BoardErrorCode.INVALID_BINDING,
                            BoardErrorCode.BOARD_ACTIVATION_FAILED})


def _clip_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:_TRACE_EXCEPTION_CHARS]}"


async def activate_on_host(host: BoardBrainHost, binding: BoardConversationBinding,
                           trace: Callable[..., None], *, step: str) -> BoardActivation:
    """`host.activate(binding)` ; tout échec devient un `BoardError` tracé (étape 3 des transitions).

    Un refus codé de l'hôte (`session_closed`, `invalid_binding`,
    `board_activation_failed`) garde son code et son `host_state` ; toute autre
    panne devient `board_activation_failed` (`host_state` inconnu), cause réelle
    dans le message.
    """

    try:
        return await host.activate(binding)
    except asyncio.CancelledError:
        raise
    except BoardError as exc:
        if exc.code not in _HOST_REFUSALS:
            raise
        failure = exc
    except Exception as exc:  # noqa: BLE001 - re-raised below as a typed BoardError, cause kept
        failure = BoardError(BoardErrorCode.BOARD_ACTIVATION_FAILED,
                             f"board brain host could not activate {binding.board_id}: {_clip_exc(exc)}")
        failure.__cause__ = exc
        failure.host_state = HOST_UNKNOWN  # type: ignore[attr-defined]
    trace("core.board.activation_failed", f"Cerveau du Board non activé ({step}) : {failure}", level="error",
          data={"code": failure.code.value, "board_id": binding.board_id, "step": step,
                "conversation_id": binding.conversation_id, "jarvis_session_id": binding.jarvis_session_id,
                "host_state": getattr(failure, "host_state", HOST_UNCHANGED)})
    raise failure


async def restore_on_host(host: BoardBrainHost | None, binding: BoardConversationBinding | None,
                          trace: Callable[..., None], *, step: str) -> bool:
    """Rétablir l'ancien foreground sur l'hôte après un échec. Ne lève jamais : dit le résultat.

    Rend vrai si l'hôte l'a repris. Un échec est une erreur tracée
    (`core.board.host_restore_failed`) : Core n'a rien validé, son autorité
    reste l'ancienne liaison ; le Control Center se réaligne au prochain tour
    (`GET /v1/sessions/current`).
    """

    if host is None or binding is None:
        return False
    try:
        await host.activate(binding)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - capture: rollback best effort, the trace is the record
        trace("core.board.host_restore_failed",
              f"Ancien cerveau non rétabli après échec ({step}) : {_clip_exc(exc)}", level="error",
              data={"code": str(getattr(getattr(exc, "code", None), "value", "board_activation_failed")),
                    "board_id": binding.board_id, "conversation_id": binding.conversation_id, "step": step,
                    "exception_type": type(exc).__name__})
        return False
    trace("core.board.host_restored", f"Ancien cerveau rétabli après échec ({step})",
          data={"board_id": binding.board_id, "conversation_id": binding.conversation_id, "step": step})
    return True


async def publish_voice_binding(events: Any, binding: BoardConversationBinding, *, reason: str) -> None:
    """`board.voice_binding.changed` : Voice se relie à la conversation qui a la parole."""

    if events is None:
        return
    await events.publish(ProtocolEnvelope(
        message_type=BOARD_VOICE_BINDING_CHANGED,
        payload={"conversation_id": binding.conversation_id, "board_id": binding.board_id,
                 "jarvis_session_id": binding.jarvis_session_id, "reason": reason},
        conversation_id=binding.conversation_id,
    ))


@dataclass(frozen=True, slots=True)
class SwitchResult:
    """Issue de `BoardService.switch` : la Session, la liaison qui a la parole, le Board actif."""

    session: JarvisSession
    binding: BoardConversationBinding
    board: Board
    previous_board_id: str
    changed: bool

    def to_payload(self) -> dict[str, Any]:
        return {"session": self.session.to_payload(), "binding": self.binding.to_payload(),
                "board": self.board.to_payload(), "previous_board_id": self.previous_board_id,
                "changed": self.changed}


def _invalid(message: str) -> BoardError:
    return BoardError(BoardErrorCode.INVALID_BOARD, message)


def parse_board_edits(payload: object, *, require_title: bool, allowed: frozenset[str] = EDITABLE_FIELDS) -> dict[str, Any]:
    """Corps JSON -> arguments de `create_board` / `update_board`. Strict : champ inconnu ou mal typé = `invalid_board`.

    Les valeurs elles-mêmes (longueurs, bornes) sont vérifiées par le domaine
    à la construction du Board ; ici seulement la forme du fil. `board_kind`
    hors de `allowed` (une édition) : `board_kind_immutable`, pas un champ inconnu.
    """

    if not isinstance(payload, dict):
        raise _invalid("board request must be a JSON object")
    if "board_kind" in payload and "board_kind" not in allowed:
        raise BoardError(BoardErrorCode.BOARD_KIND_IMMUTABLE,
                         "board_kind is fixed when the board is created and cannot be changed; "
                         "create a new board of the wanted type instead")
    unknown = sorted(str(key)[:40] for key in payload if key not in allowed)
    if unknown:
        raise _invalid(f"unknown board fields: {unknown[:5]}")
    if require_title and "title" not in payload:
        raise BoardError(BoardErrorCode.INVALID_TITLE, "title is required")
    if not payload:
        raise _invalid("board update names no field")
    edits: dict[str, Any] = {}
    for name, value in payload.items():
        if name in {"task_refs", "artifact_refs", "project_refs"}:
            # Une chaîne serait itérée caractère par caractère : liste exigée.
            if not isinstance(value, list):
                raise _invalid(f"{name} must be a list of strings")
            edits[name] = tuple(value)
        elif name == "scene_ref":
            edits[name] = None if value is None else SceneRef.from_payload(value)
        elif name == "runtime_metadata":
            if not isinstance(value, dict):
                raise _invalid("runtime_metadata must be an object")
            edits[name] = value
        elif name == "board_kind":
            # Valeur interne exacte ; `empty` : alias déprécié d'`assistant`, jamais stocké.
            edits[name] = parse_board_kind_input(value)
        elif name == "title":
            if not isinstance(value, str):
                raise BoardError(BoardErrorCode.INVALID_TITLE, "title must be a string")
            edits[name] = value
        else:  # context_summary
            if not isinstance(value, str):
                raise _invalid("context_summary must be a string")
            edits[name] = value
    return edits


class BoardService:
    """Porte unique des Boards dans Core. Voir l'en-tête du module."""

    def __init__(
        self,
        repository: BoardRepository,
        *,
        interaction_mode: InteractionModeService,
        diagnostics: DiagnosticSink | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repo = repository
        self._modes = interaction_mode
        self._diagnostics = diagnostics
        self._clock = clock
        # Lecture-modification-écriture d'un Board : deux éditions concurrentes
        # (route, MCP) ne s'écrasent pas l'une l'autre.
        self._lock = asyncio.Lock()
        # Transitions (Slice 04b), câblées par `configure_transitions` : la
        # bascule a besoin des Sessions, qui dépendent de ce service.
        self._sessions: SessionManager | None = None
        self._authority: SpeechAuthority | None = None
        self._host: BoardBrainHost | None = None
        self._events: Any = None

    # ------------------------------------------------------------ cycle de vie

    async def start(self, *, ensure_default: bool = True) -> None:
        """Au démarrage de Core, après `state.initialize()` et avant toute route.

        Lève seulement si la base refuse (Core ne démarre pas sur une base
        illisible) ; un mode que Core refuse est journalisé, pas levé.
        Core appelle `ensure_default()` lui-même, avant d'ouvrir la Session
        (Slice 03 : le mode restauré est celui du type du Board de cette
        Session), puis `start(ensure_default=False)`.
        """

        if ensure_default:
            await self.ensure_default()
        await self.restore_interaction_mode()

    # ------------------------------------------------------------ migration

    async def ensure_default(self) -> bool:
        """Créer le Board `default` si aucun Board n'existe (06 section H). Idempotent.

        Rend vrai si cet appel l'a créé. Clé « table vide », tenue dans une
        seule transaction : un second démarrage, ou deux démarrages concurrents
        sur le même fichier, n'insèrent jamais deux fois. Le Board naît de type
        `assistant` (le réglage global historique n'est pas repris : un Board
        jamais réglé se comportait déjà en assistant). Des Boards existent sans
        `default` : rien n'est inventé, c'est dit ; `get_active()` le dira
        ensuite par `board_not_found` tant qu'aucune Session ne désigne un Board.
        """

        created = await self._repo.insert_board_if_empty(default_board(now=self._clock()))
        if created:
            self._trace("core.board.default_created", "Board par défaut créé (migration mono-espace)",
                        data={"board_id": DEFAULT_BOARD_ID})
        elif await self._repo.get_board(DEFAULT_BOARD_ID) is None:
            self._trace("core.board.default_absent", "Aucun Board par défaut : des Boards existent déjà",
                        level="warning", data={"board_id": DEFAULT_BOARD_ID})
        return created

    # ------------------------------------------------------------ lecture

    async def active_board_id(self) -> str:
        """Board de la Session ouverte, `default` sans Session (voir l'en-tête)."""

        session = await self._repo.current_session()
        return session.active_board_id if session is not None else DEFAULT_BOARD_ID

    async def list(self, *, include_archived: bool = False) -> tuple[Board, ...]:
        return tuple(await self._repo.list_boards(include_archived=include_archived))

    async def get(self, board_id: str) -> Board:
        board = await self._repo.get_board(board_id) if isinstance(board_id, str) else None
        if board is None:
            raise BoardError(BoardErrorCode.BOARD_NOT_FOUND, f"board {str(board_id)[:80]!r} does not exist")
        return board

    async def get_active(self) -> Board:
        return await self.get(await self.active_board_id())

    # ------------------------------------------------------------ écriture

    async def create(self, payload: object) -> Board:
        edits = parse_board_edits(payload, require_title=True, allowed=CREATE_FIELDS)
        now = self._clock()
        title = edits.pop("title")
        board = create_board(title, now=now, board_kind=edits.pop("board_kind", BoardKind.ASSISTANT))
        if edits:
            board = update_board(board, now=now, **edits)
        async with self._lock:
            await self._repo.save_board(board)
        data: dict[str, Any] = {"board_id": board.board_id, "board_kind": board.board_kind.value}
        if isinstance(payload, dict) and payload.get("board_kind") == LEGACY_EMPTY_BOARD_KIND:
            data["deprecated_kind"] = LEGACY_EMPTY_BOARD_KIND
        self._trace("core.board.created", "Board créé", data=data)
        return board

    async def update(self, board_id: str, payload: object) -> Board:
        try:
            edits = parse_board_edits(payload, require_title=False)
        except BoardError as exc:
            if exc.code is BoardErrorCode.BOARD_KIND_IMMUTABLE:
                # Refus attendu d'un client hérité (ancien écran, ancien outil) : warning, pas un défaut de Core.
                self._trace("core.board.kind_change_refused", "Type de Board non modifiable : rien n'a été écrit",
                            level="warning", data={"code": exc.code.value, "board_id": str(board_id)[:80],
                                                   "requested_kind": _bounded_raw(payload.get("board_kind"))
                                                   if isinstance(payload, dict) else None})
            raise
        async with self._lock:
            board = update_board(await self.get(board_id), now=self._clock(), **edits)
            await self._repo.save_board(board)
        self._trace("core.board.updated", "Board modifié",
                    data={"board_id": board.board_id, "fields": sorted(edits)})
        return board

    async def archive(self, board_id: str) -> Board:
        async with self._lock:
            board = await self.get(board_id)
            archived = archive_board(board, active_board_id=await self.active_board_id(), now=self._clock())
            if archived is not board:
                await self._repo.save_board(archived)
        self._trace("core.board.archived", "Board archivé",
                    data={"board_id": board_id, "changed": archived is not board})
        return archived

    # ------------------------------------------------------------ mode d'interaction

    async def restore_interaction_mode(self) -> None:
        """Appliquer le mode dérivé du type du Board actif au démarrage de Core. Ne lève pas pour un refus.

        Toujours demandé, quel que soit le type : c'est ce qui annule, à chaque
        démarrage, un mode vivant changé par un écrivain hérité (voir l'en-tête).
        """

        try:
            board = await self.get_active()
        except BoardError as exc:
            self._trace("core.board.interaction_mode.restore_failed",
                        f"Mode du Board actif non restauré : {exc}", level="error",
                        data={"code": exc.code.value})
            return
        try:
            await self._request_board_mode(board, source=BOARD_RESTORE_SOURCE)
        except InteractionModeError:
            return  # argued: already traced as `apply_failed` by `_request_board_mode`; Core keeps its mode

    @staticmethod
    def board_mode(board: Board) -> InteractionMode:
        """Mode dont le comportement tourne pour ce Board : celui de son type ; Réunion -> assistant."""

        return behaving_interaction_mode(board_kind_mode(board.board_kind))

    async def _request_board_mode(self, board: Board, *, source: str) -> None:
        """Demander à `InteractionModeService` le mode du type de `board`. Un refus est tracé puis levé."""

        mode = self.board_mode(board)
        try:
            state, disposition = await self._modes.request(mode.value, source=source)
        except InteractionModeError as exc:
            self._trace("core.board.interaction_mode.apply_failed",
                        f"Mode du Board {board.board_id} refusé par Core : {exc}", level="error",
                        data={"board_id": board.board_id, "code": exc.code, "mode": mode.value,
                              "board_kind": board.board_kind.value, "source": source})
            raise
        data: dict[str, Any] = {"board_id": board.board_id, "board_kind": board.board_kind.value,
                                "mode": state.mode.value, "revision": state.revision,
                                "disposition": disposition.value, "source": source}
        message = f"Mode du type de Board appliqué ({source})"
        if board.board_kind is BoardKind.MEETING:
            # Réunion n'a pas encore de comportement : c'est dit, jamais refusé (pas de bascule annulée).
            data["status"] = MEETING_PLANNED
            message = f"Board Réunion : comportement réunion pas encore disponible, assistant appliqué ({source})"
        self._trace("core.board.interaction_mode.applied", message, data=data)

    # ------------------------------------------------------------ bascule (Slice 04b)

    def configure_transitions(self, *, sessions: SessionManager, authority: SpeechAuthority,
                              host: BoardBrainHost | None, events: Any) -> None:
        """Câblage du composition root : Sessions, autorité de parole, hôte des cerveaux, bus."""

        self._sessions = sessions
        self._authority = authority
        self._host = host
        self._events = events

    async def switch(self, board_id: object, *, origin: str = "protocol") -> SwitchResult:
        """Rendre `board_id` actif dans la Session ouverte. Voir l'en-tête du module (étapes 1 à 7)."""

        if self._sessions is None or self._authority is None:
            raise RuntimeError("board switch is not configured (configure_transitions)")
        if not isinstance(board_id, str) or not board_id:
            raise BoardError(BoardErrorCode.INVALID_BOARD, "board_id must be a non-empty string")
        async with self._authority.lock:
            return await self._switch_locked(board_id, origin=origin)

    async def _switch_locked(self, board_id: str, *, origin: str) -> SwitchResult:
        assert self._sessions is not None and self._authority is not None
        sessions = self._sessions
        current = await sessions.current()
        session, previous = current.session, current.binding
        board = await self.get(board_id)
        if board.status is BoardStatus.ARCHIVED:
            raise BoardError(BoardErrorCode.BOARD_ARCHIVED, f"board {board.board_id} is archived")
        if board.board_id == session.active_board_id:
            # Le mode du type est réappliqué (en-tête, *Aucun autre écrivain du mode*) : c'est
            # la reprise d'une restauration du Studio ratée ; idempotent sinon.
            try:
                await self._request_board_mode(board, source=BOARD_SWITCH_SOURCE)
            except InteractionModeError:
                pass  # argued: traced at error level as `apply_failed`; a no-op switch has nothing to roll back
            self._trace("core.board.switch_noop", "Bascule vers le Board déjà actif : mode de son type réappliqué",
                        data={"board_id": board.board_id, "origin": origin,
                              "mode": self._modes.state.mode.value, "mode_source": self._modes.state.source})
            return SwitchResult(session, previous, board, previous.board_id, changed=False)
        target = await sessions.binding_for(session.jarvis_session_id, board.board_id)
        self._trace("core.board.switch_started", "Bascule de Board demandée",
                    data={"board_id": board.board_id, "previous_board_id": previous.board_id,
                          "jarvis_session_id": session.jarvis_session_id, "origin": origin})
        # 3. Hôte. Un échec n'a rien écrit : seule la liaison `suspended` créée
        #    par `binding_for` peut exister, et A/B/A la reprendra telle quelle.
        activation: BoardActivation | None = None
        if self._host is not None:
            try:
                activation = await activate_on_host(self._host, target, self._trace, step="switch")
            except BoardError as exc:
                if getattr(exc, "host_state", HOST_UNCHANGED) == HOST_UNKNOWN:
                    # Délai ou réponse illisible : l'hôte a peut-être basculé.
                    await restore_on_host(self._host, previous, self._trace, step="switch_activation")
                raise
        host = self._host if activation is not None else None
        # 4. Mode dérivé du type du Board cible (Réunion : assistant, jamais refusé).
        previous_mode = self._modes.state.mode
        try:
            await self._request_board_mode(board, source=BOARD_SWITCH_SOURCE)
        except InteractionModeError as exc:
            await restore_on_host(host, previous, self._trace, step="switch_mode")
            raise self._rolled_back(board, previous, "mode", exc) from exc
        # 5. Une transaction SQLite.
        try:
            session, binding = await sessions.commit_promotion(session.jarvis_session_id, board, activation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - rolled back, re-raised as board_switch_rolled_back with its cause
            await restore_on_host(host, previous, self._trace, step="switch_commit")
            await self._restore_mode(previous_mode)
            raise self._rolled_back(board, previous, "commit", exc) from exc
        # 6. Autorité : aucune attente entre l'écriture validée et ce point.
        self._authority.set(binding)
        self._trace("core.board.switched", "Board actif changé : la parole passe à sa liaison",
                    data={"board_id": board.board_id, "previous_board_id": previous.board_id,
                          "conversation_id": binding.conversation_id,
                          "previous_conversation_id": previous.conversation_id,
                          "jarvis_session_id": session.jarvis_session_id, "origin": origin,
                          "previous_lifecycle": activation.previous_lifecycle.value
                          if activation is not None and activation.previous_lifecycle is not None else None})
        # 7. Évènements : Voice se relie (`board.voice_binding.changed`).
        if self._events is not None:
            await self._events.publish(ProtocolEnvelope(
                message_type=BOARD_SWITCHED,
                payload={"board_id": board.board_id, "previous_board_id": previous.board_id,
                         "jarvis_session_id": session.jarvis_session_id, "conversation_id": binding.conversation_id,
                         "previous_conversation_id": previous.conversation_id, "origin": origin},
                conversation_id=binding.conversation_id,
            ))
        await publish_voice_binding(self._events, binding, reason="board_switch")
        return SwitchResult(session, binding, await self.get(board.board_id), previous.board_id, changed=True)

    async def _restore_mode(self, mode: InteractionMode) -> None:
        """Rétablir le mode d'avant une bascule annulée. Ne lève pas : un refus est tracé."""

        if self._modes.state.mode is mode:
            return
        try:
            await self._modes.request(mode.value, source=BOARD_SWITCH_SOURCE)
        except InteractionModeError as exc:
            self._trace("core.board.interaction_mode.restore_failed",
                        f"Mode d'avant la bascule non rétabli : {exc}", level="error",
                        data={"code": exc.code, "mode": mode.value, "source": BOARD_SWITCH_SOURCE})

    def _rolled_back(self, board: Board, previous: BoardConversationBinding, step: str,
                     exc: BaseException) -> BoardError:
        error = BoardError(BoardErrorCode.BOARD_SWITCH_ROLLED_BACK,
                           f"switch to board {board.board_id} rolled back at {step}: {_clip_exc(exc)}")
        cause = getattr(exc, "code", "")
        self._trace("core.board.switch_rolled_back", f"Bascule annulée ({step}) : {_clip_exc(exc)}", level="error",
                    data={"code": error.code.value, "step": step, "board_id": board.board_id,
                          "previous_board_id": previous.board_id, "exception_type": type(exc).__name__,
                          "cause_code": str(getattr(cause, "value", cause))})
        return error

    async def align_host(self) -> bool:
        """Au démarrage de Core : l'hôte met au premier plan la liaison active de la Session reprise (ou neuve).

        Tâche de fond, ne lève jamais (rend vrai si l'hôte a suivi). Le Control
        Center peut être absent ou démarrer après Core : c'est dit
        (`core.board.host_align_deferred`), et il se réaligne lui-même depuis
        `GET /v1/sessions/current` (adoption à son démarrage, puis au premier
        tour dont la conversation lui est inconnue).
        """

        if self._host is None or self._sessions is None or self._authority is None:
            return False
        async with self._authority.lock:
            try:
                view = await self._sessions.current()
                activation = await self._host.activate(view.binding)
                await self._sessions.record_activation(view.binding, activation)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - capture: the Control Center realigns itself, said here
                cause = getattr(exc, "code", "board_activation_failed")
                self._trace("core.board.host_align_deferred",
                            f"Hôte des cerveaux non aligné au démarrage : {_clip_exc(exc)}", level="warning",
                            data={"code": str(getattr(cause, "value", cause)), "exception_type": type(exc).__name__})
                return False
        self._trace("core.board.host_aligned", "Hôte des cerveaux aligné sur la Session ouverte",
                    data={"board_id": view.binding.board_id, "conversation_id": view.binding.conversation_id,
                          "agent_cli": activation.agent_cli})
        return True

    # ------------------------------------------------------------ journal

    def _trace(self, kind: str, message: str, *, level: str = "info", data: Mapping[str, Any] | None = None) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=dict(data or {}))
        except Exception:  # noqa: BLE001 - intentional: an unavailable journal must not break a Board write
            pass


def _bounded_raw(value: object) -> object:
    """Valeur brute bornée pour une trace (Slice 08, polish S01a : `preview` citait une chaîne, `"'presentation'"`)."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:64]
