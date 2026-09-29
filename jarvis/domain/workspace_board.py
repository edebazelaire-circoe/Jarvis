"""Contrat pur des Boards de travail et des Sessions Jarvis (handoff board-session, Slice 01).

Trois valeurs, un vocabulaire (glossaire complet : `docs/boards.md`) :

- `Board` : l'espace de travail **durable** et la frontière de contexte
  (résumé, références de tâches/artefacts/projets, scène, mode d'interaction).
  Rien à voir avec le « board » Barehands (`jarvis/ports/board.py`) : d'où le
  nom de module `workspace_board` et la table `work_boards` ;
- `JarvisSession` : l'épisode de conversation humain/Jarvis. Elle traverse
  plusieurs Boards, puis se ferme et devient un historique **immuable** ;
- `BoardConversationBinding` : pour une Session et un Board, la conversation
  Core et la session CLI d'agent qui la portent. Unique par couple
  `(jarvis_session_id, board_id)` : revenir sur un Board dans la même Session
  retrouve la même liaison (A/B/A).

Invariants portés ici, que ni l'UI, ni MCP, ni le magasin ne contournent :

- une Session fermée ne change plus jamais (`session_closed`) ;
- au plus une liaison `foreground` par Session : c'est elle qui a l'autorité
  de parole ;
- le Board actif d'une Session n'est jamais archivé (`board_is_active`) ;
- toute chaîne et toute collection est bornée ; la validation refuse, elle ne
  tronque pas.

Pur : aucune E/S, aucune horloge implicite (chaque transition reçoit `now`),
aucune dépendance hors du domaine. La persistance (Slice 02), les liaisons
vivantes (Slice 03) et la bascule (Slice 04b) appliquent ces fonctions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
import uuid

from jarvis.domain._checks import MAX_ID_CHARS, TOKEN, preview
from jarvis.domain.interaction_mode import DEFAULT_INTERACTION_MODE, InteractionMode

# ------------------------------------------------------------------ constantes

#: Board créé par la migration depuis l'état mono-espace (06 section H).
DEFAULT_BOARD_ID = "default"
DEFAULT_BOARD_TITLE = "Board principal"
BOARD_ID_PREFIX = "board_"
SESSION_ID_PREFIX = "jsess_"

MAX_TITLE_CHARS = 120
#: Résumé de contexte d'un Board. Le bloc `board` injecté à chaque tour
#: (06 section E, ~2 Ko) porte titre + résumé + références : 1 500 caractères
#: laissent la place au reste. Au-delà : refus `context_summary_too_long`,
#: jamais de troncature silencieuse — l'éditeur (UI, MCP, cerveau du Board)
#: doit condenser lui-même.
MAX_CONTEXT_SUMMARY_CHARS = 1_500
#: Références opaques (id de tâche, chemin ou id d'artefact, id de projet).
MAX_REFS_PER_KIND = 64
MAX_REF_CHARS = 256
#: Métadonnées d'exécution : petit dictionnaire plat de scalaires JSON.
MAX_RUNTIME_METADATA_KEYS = 16
MAX_RUNTIME_METADATA_KEY_CHARS = 64
MAX_RUNTIME_METADATA_VALUE_CHARS = 256
#: Boards visités par une Session : borne défensive, largement au-dessus
#: d'un usage humain.
MAX_VISITED_BOARDS = 256
MAX_AGENT_CLI_CHARS = 32


# ------------------------------------------------------------------ erreurs


class BoardErrorCode(StrEnum):
    """Motif stable d'un refus : se compare, se journalise, voyage en HTTP/MCP."""

    BOARD_NOT_FOUND = "board_not_found"
    BOARD_ARCHIVED = "board_archived"
    #: Archiver le Board actif de la Session courante.
    BOARD_IS_ACTIVE = "board_is_active"
    SESSION_NOT_FOUND = "session_not_found"
    #: Toute mutation d'une Session fermée, ou promotion d'une liaison fermée.
    SESSION_CLOSED = "session_closed"
    BINDING_NOT_FOUND = "binding_not_found"
    #: Deux liaisons pour un même `(session, board)`, deux `foreground` dans
    #: une Session, ou liaison qui n'appartient pas à la Session/au Board visé.
    BINDING_CONFLICT = "binding_conflict"
    INVALID_TITLE = "invalid_title"
    CONTEXT_SUMMARY_TOO_LONG = "context_summary_too_long"
    INVALID_BOARD = "invalid_board"
    INVALID_SESSION = "invalid_session"
    INVALID_BINDING = "invalid_binding"
    #: Un tour visant la liaison d'un Board qui n'a pas l'autorité de parole
    #: (routage du pool, 06 section B).
    BRAIN_NOT_FOREGROUND = "brain_not_foreground"
    #: L'hôte (Control Center) n'a pas pu activer l'agent de la liaison cible :
    #: bascule abandonnée avant toute écriture (06 section D).
    BOARD_ACTIVATION_FAILED = "board_activation_failed"
    #: Une étape après l'activation a échoué (mode du Board refusé, écriture) :
    #: l'activation précédente a été rétablie, rien n'est validé, l'ancien Board
    #: reste actif. Défaut côté serveur, d'où 500.
    BOARD_SWITCH_ROLLED_BACK = "board_switch_rolled_back"


#: Statut HTTP que les routes Core/CC (Slices 02-05) rendent pour chaque code.
HTTP_STATUS: Mapping[BoardErrorCode, int] = MappingProxyType({
    BoardErrorCode.BOARD_NOT_FOUND: 404,
    BoardErrorCode.SESSION_NOT_FOUND: 404,
    BoardErrorCode.BINDING_NOT_FOUND: 404,
    BoardErrorCode.BOARD_ARCHIVED: 409,
    BoardErrorCode.BOARD_IS_ACTIVE: 409,
    BoardErrorCode.SESSION_CLOSED: 409,
    BoardErrorCode.BINDING_CONFLICT: 409,
    BoardErrorCode.INVALID_TITLE: 400,
    BoardErrorCode.CONTEXT_SUMMARY_TOO_LONG: 400,
    BoardErrorCode.INVALID_BOARD: 400,
    BoardErrorCode.INVALID_SESSION: 400,
    BoardErrorCode.INVALID_BINDING: 400,
    BoardErrorCode.BRAIN_NOT_FOREGROUND: 409,
    #: 502 : c'est l'hôte en amont (le Control Center) qui a échoué.
    BoardErrorCode.BOARD_ACTIVATION_FAILED: 502,
    BoardErrorCode.BOARD_SWITCH_ROLLED_BACK: 500,
})


class BoardError(ValueError):
    """Refus nommé du contrat Board/Session ; `code` stable, `status` HTTP.

    Même forme que `InteractionModeError` : le message est lu tel quel par un
    humain dans le Control Center, le code est l'identité du défaut.
    """

    def __init__(self, code: BoardErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = BoardErrorCode(code)
        self.status = HTTP_STATUS[self.code]


# ------------------------------------------------------------------ énumérations


class BoardStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class SessionEndReason(StrEnum):
    #: L'utilisateur ou Jarvis a demandé une conversation neuve.
    NEW_SESSION = "new_session"
    #: Démarrage de Jarvis (Core) : la Session restée ouverte est close.
    CORE_RESTART = "core_restart"


class BindingStatus(StrEnum):
    #: Liaison d'une Session ouverte.
    OPEN = "open"
    #: Session close : la liaison ne redevient jamais `foreground`. Son CLI
    #: peut encore finir du travail (`background_running`) puis être suspendu.
    CLOSED = "closed"


class BrainLifecycle(StrEnum):
    """État du processus d'agent derrière une liaison (06 section B)."""

    #: CLI vivant, reçoit les tours, seule autorité de parole.
    FOREGROUND = "foreground"
    #: CLI vivant gardé pour ses sous-agents ; aucun tour, aucune parole.
    BACKGROUND_RUNNING = "background_running"
    #: CLI arrêté ; `agent_session_id` permet de le reprendre.
    SUSPENDED = "suspended"


class InteractionModeOrigin(StrEnum):
    """D'où vient le mode stocké sur un Board (06 sections F et H)."""

    #: Jamais choisi : le Board porte le défaut.
    UNSET = "unset"
    #: Repris une fois du réglage global historique à la migration.
    MIGRATED = "migrated"
    #: Choisi explicitement (UI, MCP, commande vocale).
    USER = "user"


class SceneRefKind(StrEnum):
    #: V1 : une seule scène globale partagée (limite acceptée, 06 section J).
    GLOBAL = "global"


# ------------------------------------------------------------------ validation


def _fail(code: BoardErrorCode, message: str) -> BoardError:
    return BoardError(code, message)


def _check_aware(code: BoardErrorCode, name: str, value: object, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, datetime):
        raise _fail(code, f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise _fail(code, f"{name} must be timezone-aware")


def _check_str(code: BoardErrorCode, name: str, value: object, limit: int, *, required: bool) -> None:
    if not isinstance(value, str):
        raise _fail(code, f"{name} must be a string, got {preview(value)}")
    if len(value) > limit:
        raise _fail(code, f"{name} exceeds {limit} characters")
    if required and (not value.strip() or value != value.strip()):
        raise _fail(code, f"{name} must be non-empty without surrounding spaces")
    if value and not value.isprintable():
        raise _fail(code, f"{name} must be a single printable line")


def _check_board_id(code: BoardErrorCode, name: str, value: object) -> None:
    _check_str(code, name, value, MAX_ID_CHARS, required=True)
    if value != DEFAULT_BOARD_ID and not (str(value).startswith(BOARD_ID_PREFIX) and len(str(value)) > len(BOARD_ID_PREFIX)):
        raise _fail(code, f"{name} must be {DEFAULT_BOARD_ID!r} or start with {BOARD_ID_PREFIX!r}, got {preview(value)}")


def _check_session_id(code: BoardErrorCode, name: str, value: object) -> None:
    _check_str(code, name, value, MAX_ID_CHARS, required=True)
    if not (str(value).startswith(SESSION_ID_PREFIX) and len(str(value)) > len(SESSION_ID_PREFIX)):
        raise _fail(code, f"{name} must start with {SESSION_ID_PREFIX!r}, got {preview(value)}")


def _check_enum(code: BoardErrorCode, name: str, value: object, enum: type[StrEnum]) -> None:
    if not isinstance(value, enum):
        raise _fail(code, f"{name} must be a {enum.__name__}")


def _check_title(value: object) -> None:
    _check_str(BoardErrorCode.INVALID_TITLE, "title", value, MAX_TITLE_CHARS, required=True)


def _check_refs(name: str, value: object) -> None:
    code = BoardErrorCode.INVALID_BOARD
    if not isinstance(value, tuple):
        raise _fail(code, f"{name} must be a tuple")
    if len(value) > MAX_REFS_PER_KIND:
        raise _fail(code, f"{name} holds at most {MAX_REFS_PER_KIND} references")
    for ref in value:
        _check_str(code, name, ref, MAX_REF_CHARS, required=True)
    if len(set(value)) != len(value):
        raise _fail(code, f"{name} must not repeat a reference")


def _freeze_metadata(value: object) -> Mapping[str, Any]:
    code = BoardErrorCode.INVALID_BOARD
    if not isinstance(value, Mapping):
        raise _fail(code, "runtime_metadata must be a mapping")
    if len(value) > MAX_RUNTIME_METADATA_KEYS:
        raise _fail(code, f"runtime_metadata holds at most {MAX_RUNTIME_METADATA_KEYS} keys")
    for key, item in value.items():
        if not isinstance(key, str) or not TOKEN.fullmatch(key) or len(key) > MAX_RUNTIME_METADATA_KEY_CHARS:
            raise _fail(code, f"runtime_metadata key must be a short token, got {preview(key)}")
        if item is None or isinstance(item, (bool, int, float)):
            continue
        if isinstance(item, str) and len(item) <= MAX_RUNTIME_METADATA_VALUE_CHARS:
            continue
        raise _fail(code, f"runtime_metadata[{key!r}] must be a JSON scalar (string <= {MAX_RUNTIME_METADATA_VALUE_CHARS})")
    return MappingProxyType(dict(value))


# ------------------------------------------------------------------ identifiants


def new_board_id() -> str:
    return f"{BOARD_ID_PREFIX}{uuid.uuid4().hex}"


def new_session_id() -> str:
    return f"{SESSION_ID_PREFIX}{uuid.uuid4().hex}"


# ------------------------------------------------------------------ valeurs


@dataclass(frozen=True, slots=True)
class SceneRef:
    """Référence de scène d'un Board. V1 : la scène globale, révision au départ."""

    scene_id: str
    kind: SceneRefKind = SceneRefKind.GLOBAL
    revision_at_leave: int | None = None

    def __post_init__(self) -> None:
        code = BoardErrorCode.INVALID_BOARD
        _check_enum(code, "scene_ref.kind", self.kind, SceneRefKind)
        _check_str(code, "scene_ref.scene_id", self.scene_id, MAX_ID_CHARS, required=True)
        rev = self.revision_at_leave
        if rev is not None and (type(rev) is not int or rev < 0):
            raise _fail(code, "scene_ref.revision_at_leave must be a non-negative integer")

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "scene_id": self.scene_id, "revision_at_leave": self.revision_at_leave}

    @classmethod
    def from_payload(cls, payload: object) -> SceneRef:
        code = BoardErrorCode.INVALID_BOARD
        data = _strict_keys(code, "scene_ref", payload, _SCENE_REF_KEYS, required=frozenset({"kind", "scene_id"}))
        return cls(
            kind=_parse_enum(code, "scene_ref.kind", data["kind"], SceneRefKind),
            scene_id=data["scene_id"],
            revision_at_leave=data.get("revision_at_leave"),
        )


@dataclass(frozen=True, slots=True)
class Board:
    """Espace de travail durable. Voir `docs/boards.md` › *Board*."""

    board_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: BoardStatus = BoardStatus.ACTIVE
    last_opened_at: datetime | None = None
    context_summary: str = ""
    task_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    project_refs: tuple[str, ...] = ()
    scene_ref: SceneRef | None = None
    interaction_mode: InteractionMode = DEFAULT_INTERACTION_MODE
    interaction_mode_origin: InteractionModeOrigin = InteractionModeOrigin.UNSET
    runtime_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = BoardErrorCode.INVALID_BOARD
        _check_board_id(code, "board_id", self.board_id)
        _check_title(self.title)
        _check_enum(code, "status", self.status, BoardStatus)
        for name in ("created_at", "updated_at"):
            _check_aware(code, name, getattr(self, name))
        _check_aware(code, "last_opened_at", self.last_opened_at, required=False)
        if self.updated_at < self.created_at:
            raise _fail(code, "updated_at cannot be before created_at")
        if not isinstance(self.context_summary, str):
            raise _fail(code, "context_summary must be a string")
        if len(self.context_summary) > MAX_CONTEXT_SUMMARY_CHARS:
            raise _fail(
                BoardErrorCode.CONTEXT_SUMMARY_TOO_LONG,
                f"context_summary exceeds {MAX_CONTEXT_SUMMARY_CHARS} characters ({len(self.context_summary)})",
            )
        # Multi-ligne permis, rien d'autre d'invisible : le résumé est injecté
        # tel quel dans chaque tour du cerveau (06 section E).
        if not all(ch.isprintable() or ch in "\n\t" for ch in self.context_summary):
            raise _fail(code, "context_summary accepts printable text, newlines and tabs only")
        for name in ("task_refs", "artifact_refs", "project_refs"):
            _check_refs(name, getattr(self, name))
        if self.scene_ref is not None and not isinstance(self.scene_ref, SceneRef):
            raise _fail(code, "scene_ref must be a SceneRef")
        _check_enum(code, "interaction_mode", self.interaction_mode, InteractionMode)
        _check_enum(code, "interaction_mode_origin", self.interaction_mode_origin, InteractionModeOrigin)
        # Immuable jusque dans ses métadonnées : un appelant ne modifie pas un
        # Board stocké en gardant une référence au dict qu'il a passé.
        object.__setattr__(self, "runtime_metadata", _freeze_metadata(self.runtime_metadata))

    @property
    def is_default(self) -> bool:
        return self.board_id == DEFAULT_BOARD_ID

    def to_payload(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "title": self.title,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_opened_at": _iso(self.last_opened_at),
            "context_summary": self.context_summary,
            "task_refs": list(self.task_refs),
            "artifact_refs": list(self.artifact_refs),
            "project_refs": list(self.project_refs),
            "scene_ref": None if self.scene_ref is None else self.scene_ref.to_payload(),
            "interaction_mode": self.interaction_mode.value,
            "interaction_mode_origin": self.interaction_mode_origin.value,
            "runtime_metadata": dict(self.runtime_metadata),
        }

    @classmethod
    def from_payload(cls, payload: object) -> Board:
        code = BoardErrorCode.INVALID_BOARD
        data = _strict_keys(code, "board", payload, _BOARD_KEYS, required=_BOARD_REQUIRED)
        scene = data.get("scene_ref")
        # Strict : la valeur interne exacte, pas l'étiquette ni une autre casse.
        mode = _parse_enum(code, "interaction_mode", data.get("interaction_mode", DEFAULT_INTERACTION_MODE.value), InteractionMode)
        return cls(
            board_id=data["board_id"],
            title=data["title"],
            status=_parse_enum(code, "status", data.get("status", BoardStatus.ACTIVE.value), BoardStatus),
            created_at=_parse_dt(code, "created_at", data["created_at"]),
            updated_at=_parse_dt(code, "updated_at", data["updated_at"]),
            last_opened_at=_parse_dt(code, "last_opened_at", data.get("last_opened_at"), required=False),
            context_summary=data.get("context_summary", ""),
            task_refs=_parse_list(code, "task_refs", data.get("task_refs", [])),
            artifact_refs=_parse_list(code, "artifact_refs", data.get("artifact_refs", [])),
            project_refs=_parse_list(code, "project_refs", data.get("project_refs", [])),
            scene_ref=None if scene is None else SceneRef.from_payload(scene),
            interaction_mode=mode,
            interaction_mode_origin=_parse_enum(
                code, "interaction_mode_origin",
                data.get("interaction_mode_origin", InteractionModeOrigin.UNSET.value), InteractionModeOrigin,
            ),
            runtime_metadata=data.get("runtime_metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class JarvisSession:
    """Épisode de conversation humain/Jarvis. Voir `docs/boards.md` › *Session*.

    `visited_board_ids` est dans l'ordre de première visite, sans doublon, et
    contient toujours `active_board_id`.
    """

    jarvis_session_id: str
    started_at: datetime
    active_board_id: str
    visited_board_ids: tuple[str, ...]
    status: SessionStatus = SessionStatus.OPEN
    ended_at: datetime | None = None
    end_reason: SessionEndReason | None = None

    def __post_init__(self) -> None:
        code = BoardErrorCode.INVALID_SESSION
        _check_session_id(code, "jarvis_session_id", self.jarvis_session_id)
        _check_aware(code, "started_at", self.started_at)
        _check_board_id(code, "active_board_id", self.active_board_id)
        if not isinstance(self.visited_board_ids, tuple):
            raise _fail(code, "visited_board_ids must be a tuple")
        if len(self.visited_board_ids) > MAX_VISITED_BOARDS:
            raise _fail(code, f"visited_board_ids holds at most {MAX_VISITED_BOARDS} boards")
        for board_id in self.visited_board_ids:
            _check_board_id(code, "visited_board_ids", board_id)
        if len(set(self.visited_board_ids)) != len(self.visited_board_ids):
            raise _fail(code, "visited_board_ids must not repeat a board")
        if self.active_board_id not in self.visited_board_ids:
            raise _fail(code, "active_board_id must be one of visited_board_ids")
        _check_enum(code, "status", self.status, SessionStatus)
        _check_aware(code, "ended_at", self.ended_at, required=False)
        if self.end_reason is not None:
            _check_enum(code, "end_reason", self.end_reason, SessionEndReason)
        closed = self.status is SessionStatus.CLOSED
        if closed != (self.ended_at is not None) or closed != (self.end_reason is not None):
            raise _fail(code, "ended_at and end_reason are set exactly when the session is closed")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise _fail(code, "ended_at cannot be before started_at")

    @property
    def is_open(self) -> bool:
        return self.status is SessionStatus.OPEN

    def to_payload(self) -> dict[str, Any]:
        return {
            "jarvis_session_id": self.jarvis_session_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": _iso(self.ended_at),
            "end_reason": None if self.end_reason is None else self.end_reason.value,
            "status": self.status.value,
            "active_board_id": self.active_board_id,
            "visited_board_ids": list(self.visited_board_ids),
        }

    @classmethod
    def from_payload(cls, payload: object) -> JarvisSession:
        code = BoardErrorCode.INVALID_SESSION
        data = _strict_keys(code, "session", payload, _SESSION_KEYS, required=_SESSION_REQUIRED)
        reason = data.get("end_reason")
        return cls(
            jarvis_session_id=data["jarvis_session_id"],
            started_at=_parse_dt(code, "started_at", data["started_at"]),
            ended_at=_parse_dt(code, "ended_at", data.get("ended_at"), required=False),
            end_reason=None if reason is None else _parse_enum(code, "end_reason", reason, SessionEndReason),
            status=_parse_enum(code, "status", data["status"], SessionStatus),
            active_board_id=data["active_board_id"],
            visited_board_ids=_parse_list(code, "visited_board_ids", data["visited_board_ids"]),
        )


@dataclass(frozen=True, slots=True)
class BoardConversationBinding:
    """Liaison `(Session, Board)` -> conversation Core + session CLI d'agent.

    `agent_session_id` est l'identifiant de reprise rapporté par le Control
    Center (Claude `session_id`, fil Codex) ; inconnu tant qu'aucun tour n'a
    tourné.
    """

    jarvis_session_id: str
    board_id: str
    conversation_id: str
    agent_cli: str
    created_at: datetime
    last_active_at: datetime
    lifecycle: BrainLifecycle = BrainLifecycle.SUSPENDED
    status: BindingStatus = BindingStatus.OPEN
    agent_session_id: str | None = None

    def __post_init__(self) -> None:
        code = BoardErrorCode.INVALID_BINDING
        _check_session_id(code, "jarvis_session_id", self.jarvis_session_id)
        _check_board_id(code, "board_id", self.board_id)
        _check_str(code, "conversation_id", self.conversation_id, MAX_ID_CHARS, required=True)
        _check_str(code, "agent_cli", self.agent_cli, MAX_AGENT_CLI_CHARS, required=True)
        if not TOKEN.fullmatch(self.agent_cli):
            raise _fail(code, f"agent_cli must be a short token, got {preview(self.agent_cli)}")
        if self.agent_session_id is not None:
            _check_str(code, "agent_session_id", self.agent_session_id, MAX_ID_CHARS, required=True)
        _check_aware(code, "created_at", self.created_at)
        _check_aware(code, "last_active_at", self.last_active_at)
        if self.last_active_at < self.created_at:
            raise _fail(code, "last_active_at cannot be before created_at")
        _check_enum(code, "lifecycle", self.lifecycle, BrainLifecycle)
        _check_enum(code, "status", self.status, BindingStatus)
        if self.status is BindingStatus.CLOSED and self.lifecycle is BrainLifecycle.FOREGROUND:
            raise _fail(code, "a closed binding cannot be foreground")

    @property
    def key(self) -> tuple[str, str]:
        return (self.jarvis_session_id, self.board_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "jarvis_session_id": self.jarvis_session_id,
            "board_id": self.board_id,
            "conversation_id": self.conversation_id,
            "agent_cli": self.agent_cli,
            "agent_session_id": self.agent_session_id,
            "lifecycle": self.lifecycle.value,
            "created_at": self.created_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            "status": self.status.value,
        }

    @classmethod
    def from_payload(cls, payload: object) -> BoardConversationBinding:
        code = BoardErrorCode.INVALID_BINDING
        data = _strict_keys(code, "binding", payload, _BINDING_KEYS, required=_BINDING_REQUIRED)
        return cls(
            jarvis_session_id=data["jarvis_session_id"],
            board_id=data["board_id"],
            conversation_id=data["conversation_id"],
            agent_cli=data["agent_cli"],
            agent_session_id=data.get("agent_session_id"),
            lifecycle=_parse_enum(code, "lifecycle", data["lifecycle"], BrainLifecycle),
            created_at=_parse_dt(code, "created_at", data["created_at"]),
            last_active_at=_parse_dt(code, "last_active_at", data["last_active_at"]),
            status=_parse_enum(code, "status", data["status"], BindingStatus),
        )


# ------------------------------------------------------------------ fil (dicts)

_SCENE_REF_KEYS = frozenset({"kind", "scene_id", "revision_at_leave"})
_BOARD_KEYS = frozenset({
    "board_id", "title", "status", "created_at", "updated_at", "last_opened_at", "context_summary",
    "task_refs", "artifact_refs", "project_refs", "scene_ref", "interaction_mode",
    "interaction_mode_origin", "runtime_metadata",
})
_BOARD_REQUIRED = frozenset({"board_id", "title", "created_at", "updated_at"})
_SESSION_KEYS = frozenset({
    "jarvis_session_id", "started_at", "ended_at", "end_reason", "status", "active_board_id", "visited_board_ids",
})
_SESSION_REQUIRED = frozenset({"jarvis_session_id", "started_at", "status", "active_board_id", "visited_board_ids"})
_BINDING_KEYS = frozenset({
    "jarvis_session_id", "board_id", "conversation_id", "agent_cli", "agent_session_id", "lifecycle",
    "created_at", "last_active_at", "status",
})
_BINDING_REQUIRED = _BINDING_KEYS - {"agent_session_id"}


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _strict_keys(
    code: BoardErrorCode, name: str, payload: object, allowed: frozenset[str], *, required: frozenset[str]
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _fail(code, f"{name} payload must be an object")
    unknown = sorted(str(key)[:40] for key in payload if key not in allowed)
    if unknown:
        raise _fail(code, f"{name} has unknown fields: {unknown[:5]}")
    missing = sorted(required - payload.keys())
    if missing:
        raise _fail(code, f"{name} is missing fields: {missing}")
    return payload


def _parse_dt(code: BoardErrorCode, name: str, raw: object, *, required: bool = True) -> datetime | None:
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise _fail(code, f"{name} must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise _fail(code, f"{name} is not ISO 8601: {preview(raw)}") from None


def _parse_enum(code: BoardErrorCode, name: str, raw: object, enum: type[StrEnum]) -> Any:
    try:
        return enum(raw)
    except ValueError:
        raise _fail(code, f"{name} is not a {enum.__name__}: {preview(raw)}") from None


def _parse_list(code: BoardErrorCode, name: str, raw: object) -> tuple[Any, ...]:
    if not isinstance(raw, list):
        raise _fail(code, f"{name} must be a list")
    return tuple(raw)


# ------------------------------------------------------------------ transitions : Board


def create_board(title: str, *, now: datetime, board_id: str | None = None) -> Board:
    """Nouveau Board actif ; le titre est débarrassé de ses espaces de bord."""

    clean = title.strip() if isinstance(title, str) else title
    return Board(board_id=board_id or new_board_id(), title=clean, created_at=now, updated_at=now)  # type: ignore[arg-type]


def default_board(*, now: datetime) -> Board:
    """Board `default` de la migration mono-espace ; mode `unset` (06 section H)."""

    return Board(board_id=DEFAULT_BOARD_ID, title=DEFAULT_BOARD_TITLE, created_at=now, updated_at=now)


def _require_open_board(board: Board) -> None:
    if board.status is BoardStatus.ARCHIVED:
        raise _fail(BoardErrorCode.BOARD_ARCHIVED, f"board {board.board_id} is archived")


_UNSET: Any = object()


def update_board(
    board: Board,
    *,
    now: datetime,
    title: str = _UNSET,
    context_summary: str = _UNSET,
    task_refs: list[str] | tuple[str, ...] = _UNSET,
    artifact_refs: list[str] | tuple[str, ...] = _UNSET,
    project_refs: list[str] | tuple[str, ...] = _UNSET,
    scene_ref: SceneRef | None = _UNSET,
    runtime_metadata: Mapping[str, Any] = _UNSET,
) -> Board:
    """Renommer ou éditer le contexte d'un Board non archivé. Seuls les champs passés changent."""

    _require_open_board(board)
    changes: dict[str, Any] = {"updated_at": max(now, board.updated_at)}
    if title is not _UNSET:
        changes["title"] = title.strip() if isinstance(title, str) else title
    if context_summary is not _UNSET:
        changes["context_summary"] = context_summary
    for name, value in (("task_refs", task_refs), ("artifact_refs", artifact_refs), ("project_refs", project_refs)):
        if value is not _UNSET:
            # `tuple("abc")` rendrait ("a", "b", "c") : seule une liste ou un
            # tuple est une collection de références.
            if not isinstance(value, (list, tuple)):
                raise _fail(BoardErrorCode.INVALID_BOARD, f"{name} must be a list of references, got {preview(value)}")
            changes[name] = tuple(value)
    if scene_ref is not _UNSET:
        changes["scene_ref"] = scene_ref
    if runtime_metadata is not _UNSET:
        changes["runtime_metadata"] = runtime_metadata
    return replace(board, **changes)


def set_interaction_mode(
    board: Board, mode: InteractionMode, *, now: datetime, origin: InteractionModeOrigin = InteractionModeOrigin.USER
) -> Board:
    """Mode choisi pour ce Board (06 section F). `origin=unset` n'est pas un choix."""

    _require_open_board(board)
    if origin is InteractionModeOrigin.UNSET:
        raise _fail(BoardErrorCode.INVALID_BOARD, "a chosen interaction mode needs origin user or migrated")
    return replace(board, interaction_mode=mode, interaction_mode_origin=origin, updated_at=max(now, board.updated_at))


def adopt_legacy_interaction_mode(board: Board, mode: InteractionMode, *, now: datetime) -> Board:
    """Reprise unique du mode global historique (06 section H), idempotente.

    Seul un Board `unset` l'adopte (origine `migrated`) ; un Board déjà
    migré ou choisi par l'utilisateur est rendu inchangé, pour qu'un rejeu de
    la migration n'écrase jamais un choix.
    """

    if board.interaction_mode_origin is not InteractionModeOrigin.UNSET:
        return board
    return set_interaction_mode(board, mode, now=now, origin=InteractionModeOrigin.MIGRATED)


def archive_board(board: Board, *, active_board_id: str | None, now: datetime) -> Board:
    """Archiver un Board ; refusé pour le Board actif. Déjà archivé : inchangé."""

    if board.board_id == active_board_id:
        raise _fail(BoardErrorCode.BOARD_IS_ACTIVE, f"board {board.board_id} is the active board")
    if board.status is BoardStatus.ARCHIVED:
        return board
    return replace(board, status=BoardStatus.ARCHIVED, updated_at=max(now, board.updated_at))


def mark_opened(board: Board, *, now: datetime) -> Board:
    """Horodate l'ouverture d'un Board (bascule, nouvelle Session)."""

    _require_open_board(board)
    return replace(board, last_opened_at=now, updated_at=max(now, board.updated_at))


# ------------------------------------------------------------------ transitions : Session


def ensure_open(session: JarvisSession) -> None:
    """Garde d'immuabilité : toute mutation d'une Session passe par ici."""

    if not session.is_open:
        raise _fail(BoardErrorCode.SESSION_CLOSED, f"session {session.jarvis_session_id} is closed")


def open_session(board: Board, *, now: datetime, jarvis_session_id: str | None = None) -> JarvisSession:
    """Nouvelle Session ouverte sur `board`, qui doit être actif."""

    _require_open_board(board)
    return JarvisSession(
        jarvis_session_id=jarvis_session_id or new_session_id(),
        started_at=now,
        active_board_id=board.board_id,
        visited_board_ids=(board.board_id,),
    )


def close_session(session: JarvisSession, *, reason: SessionEndReason, now: datetime) -> JarvisSession:
    """Fermeture définitive. Refermer une Session close lève `session_closed`."""

    ensure_open(session)
    if now < session.started_at:
        raise _fail(BoardErrorCode.INVALID_SESSION, "ended_at cannot be before started_at")
    return replace(session, status=SessionStatus.CLOSED, ended_at=now, end_reason=SessionEndReason(reason))


def visit_board(session: JarvisSession, board: Board) -> JarvisSession:
    """Rendre `board` actif dans la Session. Première visite : ajouté à la fin.

    Revisiter un Board ne le duplique pas : A/B/A donne `visited=(A, B)` et
    `active=A`. Visiter le Board déjà actif rend la Session inchangée.
    """

    ensure_open(session)
    _require_open_board(board)
    if board.board_id == session.active_board_id:
        return session
    visited = session.visited_board_ids
    if board.board_id not in visited:
        visited = (*visited, board.board_id)
    return replace(session, active_board_id=board.board_id, visited_board_ids=visited)


# ------------------------------------------------------------------ transitions : liaisons


def check_bindings(bindings: Iterable[BoardConversationBinding]) -> None:
    """Invariants d'un ensemble de liaisons : unicité `(session, board)`, un seul foreground par Session."""

    seen: set[tuple[str, str]] = set()
    foreground: set[str] = set()
    for binding in bindings:
        if binding.key in seen:
            raise _fail(BoardErrorCode.BINDING_CONFLICT, f"two bindings for session/board {binding.key}")
        seen.add(binding.key)
        if binding.lifecycle is BrainLifecycle.FOREGROUND:
            if binding.jarvis_session_id in foreground:
                raise _fail(
                    BoardErrorCode.BINDING_CONFLICT,
                    f"session {binding.jarvis_session_id} has more than one foreground binding",
                )
            foreground.add(binding.jarvis_session_id)


def find_binding(
    bindings: Iterable[BoardConversationBinding], jarvis_session_id: str, board_id: str
) -> BoardConversationBinding | None:
    """La liaison de ce couple, ou `None` : A/B/A retrouve la liaison de la première visite."""

    return next((b for b in bindings if b.key == (jarvis_session_id, board_id)), None)


def new_binding(
    session: JarvisSession,
    board: Board,
    *,
    conversation_id: str,
    agent_cli: str,
    now: datetime,
    existing: Iterable[BoardConversationBinding] = (),
) -> BoardConversationBinding:
    """Liaison neuve, `suspended` : la promotion passe par `promote_binding`.

    Refusée si le couple `(session, board)` est déjà lié (`binding_conflict`) :
    c'est l'appelant qui doit d'abord chercher avec `find_binding`.
    """

    ensure_open(session)
    _require_open_board(board)
    if find_binding(existing, session.jarvis_session_id, board.board_id) is not None:
        raise _fail(
            BoardErrorCode.BINDING_CONFLICT,
            f"session {session.jarvis_session_id} is already bound to board {board.board_id}",
        )
    return BoardConversationBinding(
        jarvis_session_id=session.jarvis_session_id,
        board_id=board.board_id,
        conversation_id=conversation_id,
        agent_cli=agent_cli,
        created_at=now,
        last_active_at=now,
    )


def promote_binding(
    session: JarvisSession,
    bindings: Iterable[BoardConversationBinding],
    target: BoardConversationBinding,
    *,
    now: datetime,
    demote_to: BrainLifecycle = BrainLifecycle.SUSPENDED,
) -> tuple[BoardConversationBinding, ...]:
    """Rend `target` seul `foreground` de `session` ; l'ancien passe en `demote_to`.

    `session` doit être ouverte (`session_closed` sinon) et porter `target`
    (`binding_conflict` sinon) : une liaison d'une Session close ne redevient
    jamais foreground. La règle « un seul foreground » est **par Session** ;
    une seule Session est ouverte à la fois et une Session se ferme avec ses
    liaisons (`close_session_with_bindings`), donc seule la Session ouverte a
    un foreground. Les liaisons d'autres Sessions présentes dans `bindings`
    ne sont pas touchées.

    `demote_to` est choisi par l'appelant (le pool sait si le CLI a encore des
    sous-agents : `background_running`, sinon `suspended`). Rend l'ensemble
    complet, dans l'ordre reçu, `target` compris ; vérifié par `check_bindings`.
    """

    ensure_open(session)
    if target.jarvis_session_id != session.jarvis_session_id:
        raise _fail(
            BoardErrorCode.BINDING_CONFLICT,
            f"binding {target.key} does not belong to session {session.jarvis_session_id}",
        )
    if demote_to is BrainLifecycle.FOREGROUND:
        raise _fail(BoardErrorCode.INVALID_BINDING, "demote_to cannot be foreground")
    if target.status is BindingStatus.CLOSED:
        raise _fail(BoardErrorCode.SESSION_CLOSED, f"binding {target.key} belongs to a closed session")
    items = tuple(bindings)
    if target not in items:
        raise _fail(BoardErrorCode.BINDING_NOT_FOUND, f"binding {target.key} is not in the given set")
    result = []
    for binding in items:
        if binding.key == target.key:
            binding = replace(binding, lifecycle=BrainLifecycle.FOREGROUND, last_active_at=max(now, binding.last_active_at))
        elif binding.jarvis_session_id == target.jarvis_session_id and binding.lifecycle is BrainLifecycle.FOREGROUND:
            binding = replace(binding, lifecycle=demote_to, last_active_at=max(now, binding.last_active_at))
        result.append(binding)
    out = tuple(result)
    check_bindings(out)
    return out


def set_lifecycle(binding: BoardConversationBinding, lifecycle: BrainLifecycle, *, now: datetime) -> BoardConversationBinding:
    """Démotion/suspension d'une liaison. La promotion passe par `promote_binding`."""

    if lifecycle is BrainLifecycle.FOREGROUND:
        raise _fail(BoardErrorCode.INVALID_BINDING, "use promote_binding to make a binding foreground")
    return replace(binding, lifecycle=lifecycle, last_active_at=max(now, binding.last_active_at))


def record_agent_session(
    binding: BoardConversationBinding, agent_session_id: str | None, *, now: datetime
) -> BoardConversationBinding:
    """Identifiant de reprise rapporté par le CC (activation, résultat d'un tour)."""

    return replace(binding, agent_session_id=agent_session_id, last_active_at=max(now, binding.last_active_at))


def close_binding(
    binding: BoardConversationBinding, *, now: datetime, lifecycle: BrainLifecycle = BrainLifecycle.SUSPENDED
) -> BoardConversationBinding:
    """Clôt la liaison avec sa Session. Son CLI est rétrogradé, jamais tué ici."""

    if lifecycle is BrainLifecycle.FOREGROUND:
        raise _fail(BoardErrorCode.INVALID_BINDING, "a closed binding cannot be foreground")
    if binding.status is BindingStatus.CLOSED:
        # Déjà close : rien ne change, pas même l'horodatage.
        return binding
    return replace(binding, status=BindingStatus.CLOSED, lifecycle=lifecycle, last_active_at=max(now, binding.last_active_at))


def close_session_with_bindings(
    session: JarvisSession,
    bindings: Iterable[BoardConversationBinding],
    *,
    reason: SessionEndReason,
    now: datetime,
    foreground_to: BrainLifecycle = BrainLifecycle.SUSPENDED,
) -> tuple[JarvisSession, tuple[BoardConversationBinding, ...]]:
    """Ferme la Session **et** toutes ses liaisons, d'un seul geste (06 section C).

    `bindings` est l'ensemble des liaisons de cette Session (une liaison d'une
    autre Session lève `binding_conflict`). La liaison foreground passe en
    `foreground_to` (le pool dit si son CLI a encore des sous-agents) ; les
    autres gardent leur cycle de vie : un CLI `background_running` finit son
    travail. Rend `(session_close, liaisons_closes)` dans l'ordre reçu, à
    écrire ensemble (`BoardRepository.commit_switch`).
    """

    closed = close_session(session, reason=reason, now=now)
    result = []
    for binding in bindings:
        if binding.jarvis_session_id != session.jarvis_session_id:
            raise _fail(
                BoardErrorCode.BINDING_CONFLICT,
                f"binding {binding.key} does not belong to session {session.jarvis_session_id}",
            )
        lifecycle = foreground_to if binding.lifecycle is BrainLifecycle.FOREGROUND else binding.lifecycle
        result.append(close_binding(binding, now=now, lifecycle=lifecycle))
    return closed, tuple(result)
