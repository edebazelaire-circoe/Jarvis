"""Contrat pur du Context de Session (handoff session-context-recording, Slice 01).

Un **Context** (`SessionContext`) est l'espace de travail libre d'une Session
Jarvis : un dossier que l'agent organise comme il veut. Le domaine n'en porte
que l'identité, le cycle de vie et l'emplacement ; jamais le contenu (D04).
Glossaire et règles : `docs/session-context.md`.

Invariants portés ici, que ni le magasin, ni l'UI, ni MCP ne contournent :

- un Context appartient à **une** Session (`jarvis_session_id`) ; il n'a aucune
  clé `board_id` (D06) ;
- une Session ouverte a **exactement un** Context actif dès qu'elle en a un ;
  créer ou activer un Context rend l'ancien actif `dormant`, dans le même
  résultat (`ContextTransition`) à écrire d'un seul geste ;
- aucun Context ne se crée ni ne s'active dans une Session close
  (`session_closed`) ; fermer une Session endort son Context actif ;
- un Context dormant n'est pas une cible d'écriture implicite
  (`context_dormant`) : seule une réactivation explicite le rend actif ;
- le chemin du dossier est **dérivé** des identifiants validés
  (`context_workspace_path`), jamais reçu en entrée ;
- toute chaîne et toute collection est bornée ; la validation refuse, elle ne
  tronque pas.

Pur : aucune E/S, aucune horloge implicite (chaque transition reçoit `now`).
La persistance (v5, Slice 02) et le service (Slice 03, `SessionManager`)
appliquent ces fonctions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any
import re
import uuid

from jarvis.domain._checks import MAX_ID_CHARS, TOKEN, preview
from jarvis.domain.workspace_board import (
    MAX_RUNTIME_METADATA_KEY_CHARS, MAX_RUNTIME_METADATA_KEYS, MAX_RUNTIME_METADATA_VALUE_CHARS, MAX_TITLE_CHARS,
    SESSION_ID_PREFIX, JarvisSession,
)

# ------------------------------------------------------------------ constantes

CONTEXT_ID_PREFIX = "jctx_"
#: Contexts sources d'un passage de relais (D05) : quelques références
#: choisies, pas un héritage en bloc.
MAX_SOURCE_CONTEXTS = 8
#: Racine relative à la racine de données ; voir `context_workspace_path`.
SESSIONS_DIR = "sessions"
CONTEXTS_DIR = "contexts"

#: Identifiant sûr comme segment de chemin : préfixe, puis lettres, chiffres,
#: `_` ou `-`. Ni `.`, ni séparateur, ni espace : `..`, `a/b` ou `C:` sont
#: refusés avant de devenir un dossier.
_PATH_SAFE = re.compile(r"[A-Za-z0-9_-]+")


# ------------------------------------------------------------------ erreurs


class SessionContextErrorCode(StrEnum):
    """Motif stable d'un refus : se compare, se journalise, voyage en HTTP/MCP."""

    INVALID_CONTEXT = "invalid_context"
    CONTEXT_NOT_FOUND = "context_not_found"
    #: Deux Contexts actifs dans une Session, identifiant répété, Context d'une
    #: autre Session, ou adoption d'une Session qui a déjà des Contexts.
    CONTEXT_CONFLICT = "context_conflict"
    #: Écriture implicite visant un Context dormant.
    CONTEXT_DORMANT = "context_dormant"
    #: Même valeur sur le fil que `BoardErrorCode.SESSION_CLOSED` : un client
    #: n'a qu'un seul « Session close » à reconnaître.
    SESSION_CLOSED = "session_closed"


HTTP_STATUS: Mapping[SessionContextErrorCode, int] = MappingProxyType({
    SessionContextErrorCode.INVALID_CONTEXT: 400,
    SessionContextErrorCode.CONTEXT_NOT_FOUND: 404,
    SessionContextErrorCode.CONTEXT_CONFLICT: 409,
    SessionContextErrorCode.CONTEXT_DORMANT: 409,
    SessionContextErrorCode.SESSION_CLOSED: 409,
})


class SessionContextError(ValueError):
    """Refus nommé du contrat Context ; `code` stable, `status` HTTP (forme de `BoardError`)."""

    def __init__(self, code: SessionContextErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = SessionContextErrorCode(code)
        self.status = HTTP_STATUS[self.code]


def _fail(code: SessionContextErrorCode, message: str) -> SessionContextError:
    return SessionContextError(code, message)


_INVALID = SessionContextErrorCode.INVALID_CONTEXT


# ------------------------------------------------------------------ énumérations


class ContextStatus(StrEnum):
    #: Le Context de travail de la Session ; un seul par Session ouverte.
    ACTIVE = "active"
    #: Lisible, jamais modifié implicitement ; réactivable explicitement.
    DORMANT = "dormant"


class ContextOrigin(StrEnum):
    #: Créé explicitement (utilisateur, agent, démarrage d'une Session neuve).
    CREATED = "created"
    #: Context par défaut donné à une Session ouverte héritée, d'avant les
    #: Contexts (D-CTX) ; aucun historique fabriqué.
    ADOPTED = "adopted"


# ------------------------------------------------------------------ validation


def _check_aware(name: str, value: object) -> None:
    if not isinstance(value, datetime):
        raise _fail(_INVALID, f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise _fail(_INVALID, f"{name} must be timezone-aware")


def _check_id(name: str, value: object, prefix: str) -> None:
    if not isinstance(value, str):
        raise _fail(_INVALID, f"{name} must be a string, got {preview(value)}")
    if (len(value) > MAX_ID_CHARS or not value.startswith(prefix) or len(value) == len(prefix)
            or not _PATH_SAFE.fullmatch(value)):
        raise _fail(
            _INVALID,
            f"{name} must be {prefix!r} followed by letters, digits, '_' or '-' "
            f"(<= {MAX_ID_CHARS} chars), got {preview(value)}",
        )


def check_context_id(value: object, name: str = "context_id") -> None:
    _check_id(name, value, CONTEXT_ID_PREFIX)


def check_session_id(value: object, name: str = "jarvis_session_id") -> None:
    """Plus strict que `JarvisSession` (préfixe seul) : l'id devient un segment de chemin."""

    _check_id(name, value, SESSION_ID_PREFIX)


def _check_title(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise _fail(_INVALID, f"title must be a string, got {preview(value)}")
    if len(value) > MAX_TITLE_CHARS:
        raise _fail(_INVALID, f"title exceeds {MAX_TITLE_CHARS} characters")
    if not value.strip() or value != value.strip() or not value.isprintable():
        raise _fail(_INVALID, "title must be a non-empty printable line without surrounding spaces")


def _freeze_metadata(value: object) -> Mapping[str, Any]:
    """Même forme que les métadonnées d'un Board : dict plat de scalaires JSON bornés."""

    if not isinstance(value, Mapping):
        raise _fail(_INVALID, "runtime_metadata must be a mapping")
    if len(value) > MAX_RUNTIME_METADATA_KEYS:
        raise _fail(_INVALID, f"runtime_metadata holds at most {MAX_RUNTIME_METADATA_KEYS} keys")
    for key, item in value.items():
        if not isinstance(key, str) or not TOKEN.fullmatch(key) or len(key) > MAX_RUNTIME_METADATA_KEY_CHARS:
            raise _fail(_INVALID, f"runtime_metadata key must be a short token, got {preview(key)}")
        if item is None or isinstance(item, (bool, int, float)):
            continue
        if isinstance(item, str) and len(item) <= MAX_RUNTIME_METADATA_VALUE_CHARS:
            continue
        raise _fail(_INVALID, f"runtime_metadata[{key!r}] must be a JSON scalar (string <= {MAX_RUNTIME_METADATA_VALUE_CHARS})")
    return MappingProxyType(dict(value))


# ------------------------------------------------------------------ identifiants et chemin


def new_context_id() -> str:
    return f"{CONTEXT_ID_PREFIX}{uuid.uuid4().hex}"


def context_workspace_path(jarvis_session_id: str, context_id: str) -> PurePosixPath:
    """Dossier du Context, **relatif** à la racine de données (D-CTX).

    `sessions/<jarvis_session_id>/contexts/<context_id>` ; les deux ids sont
    validés comme segments sûrs (`invalid_context` sinon), si bien qu'aucune
    entrée ne peut sortir de `sessions/`. L'adaptateur le joint à la racine.
    """

    check_session_id(jarvis_session_id)
    check_context_id(context_id)
    return PurePosixPath(SESSIONS_DIR, jarvis_session_id, CONTEXTS_DIR, context_id)


# ------------------------------------------------------------------ valeur


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Context de travail d'une Session. Voir `docs/session-context.md`.

    `activated_at` : dernière (ré)activation. `last_active_at` : dernier
    instant où il était actif (touché, ou endormi). Ordre :
    `created_at <= activated_at <= last_active_at`.
    """

    context_id: str
    jarvis_session_id: str
    created_at: datetime
    activated_at: datetime
    last_active_at: datetime
    status: ContextStatus = ContextStatus.ACTIVE
    origin: ContextOrigin = ContextOrigin.CREATED
    title: str | None = None
    source_context_ids: tuple[str, ...] = ()
    runtime_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        check_context_id(self.context_id)
        check_session_id(self.jarvis_session_id)
        for name in ("created_at", "activated_at", "last_active_at"):
            _check_aware(name, getattr(self, name))
        if not self.created_at <= self.activated_at <= self.last_active_at:
            raise _fail(_INVALID, "timestamps must satisfy created_at <= activated_at <= last_active_at")
        if not isinstance(self.status, ContextStatus):
            raise _fail(_INVALID, "status must be a ContextStatus")
        if not isinstance(self.origin, ContextOrigin):
            raise _fail(_INVALID, "origin must be a ContextOrigin")
        _check_title(self.title)
        sources = self.source_context_ids
        if not isinstance(sources, tuple):
            raise _fail(_INVALID, "source_context_ids must be a tuple")
        if len(sources) > MAX_SOURCE_CONTEXTS:
            raise _fail(_INVALID, f"source_context_ids holds at most {MAX_SOURCE_CONTEXTS} contexts")
        for source in sources:
            check_context_id(source, "source_context_ids")
        if len(set(sources)) != len(sources):
            raise _fail(_INVALID, "source_context_ids must not repeat a context")
        if self.context_id in sources:
            raise _fail(_INVALID, "a context cannot be its own source")
        # Immuable jusque dans ses métadonnées (même règle que `Board`).
        object.__setattr__(self, "runtime_metadata", _freeze_metadata(self.runtime_metadata))

    @property
    def is_active(self) -> bool:
        return self.status is ContextStatus.ACTIVE

    @property
    def workspace_path(self) -> PurePosixPath:
        return context_workspace_path(self.jarvis_session_id, self.context_id)

    def to_payload(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "jarvis_session_id": self.jarvis_session_id,
            "status": self.status.value,
            "origin": self.origin.value,
            "created_at": self.created_at.isoformat(),
            "activated_at": self.activated_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            "title": self.title,
            "source_context_ids": list(self.source_context_ids),
            "runtime_metadata": dict(self.runtime_metadata),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SessionContext:
        """Strict : champ inconnu ou manquant, type faux, date naïve, énum inconnue -> `invalid_context`."""

        if not isinstance(payload, dict):
            raise _fail(_INVALID, "context payload must be an object")
        unknown = sorted(str(key)[:40] for key in payload if key not in _KEYS)
        if unknown:
            raise _fail(_INVALID, f"context has unknown fields: {unknown[:5]}")
        missing = sorted(_REQUIRED - payload.keys())
        if missing:
            raise _fail(_INVALID, f"context is missing fields: {missing}")
        sources = payload.get("source_context_ids", [])
        if not isinstance(sources, list):
            raise _fail(_INVALID, "source_context_ids must be a list")
        return cls(
            context_id=payload["context_id"],
            jarvis_session_id=payload["jarvis_session_id"],
            status=_parse_enum("status", payload["status"], ContextStatus),
            origin=_parse_enum("origin", payload["origin"], ContextOrigin),
            created_at=_parse_dt("created_at", payload["created_at"]),
            activated_at=_parse_dt("activated_at", payload["activated_at"]),
            last_active_at=_parse_dt("last_active_at", payload["last_active_at"]),
            title=payload.get("title"),
            source_context_ids=tuple(sources),
            runtime_metadata=payload.get("runtime_metadata", {}),
        )


_KEYS = frozenset({
    "context_id", "jarvis_session_id", "status", "origin", "created_at", "activated_at", "last_active_at",
    "title", "source_context_ids", "runtime_metadata",
})
_REQUIRED = frozenset({
    "context_id", "jarvis_session_id", "status", "origin", "created_at", "activated_at", "last_active_at",
})


def _parse_dt(name: str, raw: object) -> datetime:
    if not isinstance(raw, str):
        raise _fail(_INVALID, f"{name} must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise _fail(_INVALID, f"{name} is not ISO 8601: {preview(raw)}") from None


def _parse_enum(name: str, raw: object, enum: type[StrEnum]) -> Any:
    try:
        return enum(raw)
    except ValueError:
        raise _fail(_INVALID, f"{name} is not a {enum.__name__}: {preview(raw)}") from None


# ------------------------------------------------------------------ transitions


@dataclass(frozen=True, slots=True)
class ContextTransition:
    """Résultat d'une création/activation : à écrire **en une seule transaction**.

    `contexts` : l'ensemble complet de la Session, dans l'ordre reçu (nouveau
    Context à la fin), vérifié par `check_contexts`. `changed` : les seules
    valeurs à écrire (ancien actif endormi, puis Context actif) ; vide quand
    rien ne change.
    """

    active: SessionContext
    dormanted: SessionContext | None
    contexts: tuple[SessionContext, ...]
    changed: tuple[SessionContext, ...]


def check_contexts(session: JarvisSession, contexts: Iterable[SessionContext]) -> tuple[SessionContext, ...]:
    """Invariants de l'ensemble des Contexts d'une Session ; rend le tuple vérifié.

    Tous appartiennent à `session`, sans identifiant répété ; Session ouverte :
    exactement un actif dès qu'il y a un Context (aucun Context : Session pas
    encore adoptée) ; Session close : aucun actif.
    """

    items = tuple(contexts)
    seen: set[str] = set()
    active = 0
    for context in items:
        if not isinstance(context, SessionContext):
            raise _fail(_INVALID, f"expected a SessionContext, got {preview(context)}")
        if context.jarvis_session_id != session.jarvis_session_id:
            raise _fail(
                SessionContextErrorCode.CONTEXT_CONFLICT,
                f"context {context.context_id} does not belong to session {session.jarvis_session_id}",
            )
        if context.context_id in seen:
            raise _fail(SessionContextErrorCode.CONTEXT_CONFLICT, f"context {context.context_id} appears twice")
        seen.add(context.context_id)
        active += context.is_active
    expected = (1 if items else 0) if session.is_open else 0
    if active != expected:
        state = "open" if session.is_open else "closed"
        raise _fail(
            SessionContextErrorCode.CONTEXT_CONFLICT,
            f"{state} session {session.jarvis_session_id} must have {expected} active context(s), found {active}",
        )
    return items


def _require_open(session: JarvisSession) -> None:
    if not session.is_open:
        raise _fail(SessionContextErrorCode.SESSION_CLOSED, f"session {session.jarvis_session_id} is closed")


def ensure_active(context: SessionContext) -> None:
    """Garde des écritures implicites : un Context dormant n'est pas une cible."""

    if not context.is_active:
        raise _fail(SessionContextErrorCode.CONTEXT_DORMANT, f"context {context.context_id} is dormant")


def _dormant(context: SessionContext, now: datetime) -> SessionContext:
    return replace(context, status=ContextStatus.DORMANT, last_active_at=max(now, context.last_active_at))


def _switch_to(
    items: tuple[SessionContext, ...], target: SessionContext, now: datetime, *, append: bool,
) -> ContextTransition:
    """Endort l'actif courant (s'il y en a un) et rend `target` actif, en un seul résultat."""

    dormanted = None
    result = []
    for context in items:
        if context.is_active and context.context_id != target.context_id:
            dormanted = _dormant(context, now)
            context = dormanted
        elif context.context_id == target.context_id:
            context = target
        result.append(context)
    if append:
        result.append(target)
    changed = tuple(c for c in (dormanted, target) if c is not None)
    return ContextTransition(active=target, dormanted=dormanted, contexts=tuple(result), changed=changed)


def create_context(
    session: JarvisSession,
    contexts: Iterable[SessionContext],
    *,
    now: datetime,
    title: str | None = None,
    source_context_ids: Iterable[str] = (),
    runtime_metadata: Mapping[str, Any] | None = None,
    origin: ContextOrigin = ContextOrigin.CREATED,
    context_id: str | None = None,
) -> ContextTransition:
    """Nouveau Context actif ; l'actif précédent devient dormant dans le même résultat.

    `contexts` : tous les Contexts de `session`. Le titre est débarrassé de
    ses espaces de bord ; une chaîne vide vaut « sans titre ». Les sources sont
    des références de relais (D05), pas un héritage du dossier.
    """

    _require_open(session)
    items = check_contexts(session, contexts)
    new_id = context_id or new_context_id()
    if any(c.context_id == new_id for c in items):
        raise _fail(SessionContextErrorCode.CONTEXT_CONFLICT, f"context {new_id} already exists")
    if isinstance(source_context_ids, str):
        raise _fail(_INVALID, "source_context_ids must be a list of context ids")
    clean = title.strip() if isinstance(title, str) else title
    if now < max((c.last_active_at for c in items if c.is_active), default=now):
        # L'ancien actif garde sa dernière activité ; le nouveau ne peut pas
        # naître avant : horloge reculée = refus explicite, pas de bricolage.
        raise _fail(_INVALID, "a context cannot be created before the current active context's last activity")
    created = SessionContext(
        context_id=new_id,
        jarvis_session_id=session.jarvis_session_id,
        created_at=now,
        activated_at=now,
        last_active_at=now,
        origin=origin,
        title=clean or None,
        source_context_ids=tuple(source_context_ids),
        runtime_metadata={} if runtime_metadata is None else runtime_metadata,
    )
    return _switch_to(items, created, now, append=True)


def adopt_context(session: JarvisSession, contexts: Iterable[SessionContext], *, now: datetime) -> ContextTransition:
    """Context `adopted` d'une Session ouverte héritée, qui n'en a encore aucun (D-CTX).

    Refusé (`context_conflict`) si la Session a déjà un Context : l'adoption
    n'a lieu qu'une fois et ne fabrique aucun historique.
    """

    _require_open(session)
    items = check_contexts(session, contexts)
    if items:
        raise _fail(
            SessionContextErrorCode.CONTEXT_CONFLICT,
            f"session {session.jarvis_session_id} already has contexts; adoption happens once",
        )
    return create_context(session, (), now=now, origin=ContextOrigin.ADOPTED)


def activate_context(
    session: JarvisSession, contexts: Iterable[SessionContext], context_id: str, *, now: datetime,
) -> ContextTransition:
    """Réactivation explicite d'un Context dormant ; l'actif courant s'endort.

    Activer le Context déjà actif ne change rien (`changed` vide). Context
    absent de la Session : `context_not_found`.
    """

    _require_open(session)
    items = check_contexts(session, contexts)
    target = next((c for c in items if c.context_id == context_id), None)
    if target is None:
        check_context_id(context_id)
        raise _fail(
            SessionContextErrorCode.CONTEXT_NOT_FOUND,
            f"context {context_id} is not in session {session.jarvis_session_id}",
        )
    if target.is_active:
        return ContextTransition(active=target, dormanted=None, contexts=items, changed=())
    if now < max(target.last_active_at, *(c.last_active_at for c in items if c.is_active)):
        raise _fail(_INVALID, "a context cannot be activated before its own or the active context's last activity")
    reactivated = replace(target, status=ContextStatus.ACTIVE, activated_at=now, last_active_at=now)
    return _switch_to(items, reactivated, now, append=False)


def touch_context(context: SessionContext, *, now: datetime) -> SessionContext:
    """Horodate une activité dans le Context actif ; un Context dormant est refusé."""

    ensure_active(context)
    return replace(context, last_active_at=max(now, context.last_active_at))


def dormant_contexts_of_closed_session(
    session: JarvisSession, contexts: Iterable[SessionContext], *, now: datetime,
) -> tuple[SessionContext, ...]:
    """À la fermeture d'une Session (`new_session`) : son Context actif s'endort.

    `session` est la valeur **close**, écrite dans la même transaction que le
    résultat. Rend les seuls Contexts changés (zéro ou un).
    """

    if session.is_open:
        raise _fail(_INVALID, f"session {session.jarvis_session_id} is still open")
    changed = []
    for context in contexts:
        if context.jarvis_session_id != session.jarvis_session_id:
            raise _fail(
                SessionContextErrorCode.CONTEXT_CONFLICT,
                f"context {context.context_id} does not belong to session {session.jarvis_session_id}",
            )
        if context.is_active:
            changed.append(_dormant(context, now))
    return tuple(changed)
