"""Contrat pur du ledger d'activité de Session (handoff session-context-recording, Slice 04).

Le **ledger d'activité** est la vérité factuelle, écrite par le backend, de ce
qui arrive à une Session : Context créé, activé, endormi ; capture démarrée,
arrêtée, trouée ; Artifact créé, finalisé, enrichi, supprimé (D10). Il est
distinct :

- des conversation events (`docs/conversation-events.md`), vérité de la
  conversation **adressée** à Jarvis : aucun texte ambiant n'y entre comme tour
  (D17) ;
- de `RuntimeJournal` (`runtime/trace.jsonl`), diagnostic : il peut refléter
  un événement (identifiants seulement), jamais en être la source.

Un événement porte des identifiants et de petites données bornées ; jamais de
média, jamais de texte de transcription. Contrat : `docs/artifacts.md` ›
*Activity ledger*.

Pur : aucune E/S, aucune horloge implicite. `seq` est attribué par le magasin
(monotone par base, jamais réutilisé).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
import uuid

from jarvis.domain._checks import (
    TOKEN, check_aware, check_prefixed_id, freeze_runtime_metadata, parse_dt, parse_enum, preview, strict_keys,
)
from jarvis.domain.artifacts import ARTIFACT_ID_PREFIX
from jarvis.domain.session_context import CONTEXT_ID_PREFIX, ContextTransition
from jarvis.domain.workspace_board import SESSION_ID_PREFIX

ACTIVITY_ID_PREFIX = "jact_"
MAX_ACTIVITY_REFS = 16
MAX_CAPTURE_ID_CHARS = 128
MAX_ACTIVITY_DATA_KEYS = 16
MAX_ACTIVITY_DATA_KEY_CHARS = 64
#: Une valeur de données reste courte : un code, un compte, un nom de source.
#: Jamais un texte de transcription.
MAX_ACTIVITY_DATA_VALUE_CHARS = 256
DEFAULT_ACTIVITY_LIMIT = 100
MAX_ACTIVITY_LIMIT = 500
MAX_ACTIVITY_KINDS_FILTER = 16


class ActivityErrorCode(StrEnum):
    INVALID_ACTIVITY = "invalid_activity"


class ActivityError(ValueError):
    """Événement ou requête refusé (`invalid_activity`, HTTP 400)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = ActivityErrorCode.INVALID_ACTIVITY
        self.status = 400


def _invalid(message: str) -> ActivityError:
    return ActivityError(message)


class ActivityKind(StrEnum):
    """Vocabulaire fermé (docs/02-architecture §3 du handoff, plus Session et suppression)."""

    SESSION_OPENED = "session.opened"
    SESSION_RESUMED = "session.resumed"
    SESSION_CLOSED = "session.closed"
    CONTEXT_CREATED = "context.created"
    CONTEXT_ACTIVATED = "context.activated"
    CONTEXT_DORMANT = "context.dormant"
    CAPTURE_STARTED = "capture.started"
    CAPTURE_STOPPED = "capture.stopped"
    CAPTURE_GAP = "capture.gap"
    #: La Session ou le Context actif a changé pendant une capture ouverte ; la
    #: capture garde son association de démarrage (Slice 05, `docs/capture.md`).
    CAPTURE_ASSOCIATION_CHANGED = "capture.association_changed"
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_FINALIZED = "artifact.finalized"
    ARTIFACT_ENRICHMENT_UPDATED = "artifact.enrichment.updated"
    ARTIFACT_DELETED = "artifact.deleted"
    TRANSCRIPT_SEGMENT_CREATED = "transcript.segment.created"
    TRANSCRIPT_PROJECTION_UPDATED = "transcript.projection.updated"

    @property
    def family(self) -> str:
        return self.value.split(".", 1)[0]


#: Familles dont l'événement nomme toujours sa Session (et son Context pour `context`).
_SESSION_FAMILIES = frozenset({"session", "context", "capture"})


def new_activity_id() -> str:
    return f"{ACTIVITY_ID_PREFIX}{uuid.uuid4().hex}"


def _check_capture_id(value: object) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_CAPTURE_ID_CHARS or not TOKEN.fullmatch(value):
        raise _invalid(f"capture_ids must hold short tokens, got {preview(value)}")


def _freeze_data(value: object) -> Mapping[str, Any]:
    def fail(message: str) -> ActivityError:
        return _invalid(message.replace("runtime_metadata", "data"))

    return freeze_runtime_metadata(fail, value, max_keys=MAX_ACTIVITY_DATA_KEYS,
                                   max_key_chars=MAX_ACTIVITY_DATA_KEY_CHARS,
                                   max_value_chars=MAX_ACTIVITY_DATA_VALUE_CHARS)


@dataclass(frozen=True, slots=True)
class ActivityDraft:
    """Événement à ajouter ; le magasin lui donne son `seq`."""

    kind: ActivityKind
    occurred_at: datetime
    jarvis_session_id: str | None = None
    context_id: str | None = None
    artifact_ids: tuple[str, ...] = ()
    capture_ids: tuple[str, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=new_activity_id)

    def __post_init__(self) -> None:
        check_prefixed_id(_invalid, "event_id", self.event_id, ACTIVITY_ID_PREFIX)
        if not isinstance(self.kind, ActivityKind):
            raise _invalid(f"kind must be an ActivityKind, got {preview(self.kind)}")
        check_aware(_invalid, "occurred_at", self.occurred_at)
        if self.jarvis_session_id is not None:
            check_prefixed_id(_invalid, "jarvis_session_id", self.jarvis_session_id, SESSION_ID_PREFIX)
        if self.context_id is not None:
            check_prefixed_id(_invalid, "context_id", self.context_id, CONTEXT_ID_PREFIX)
            if self.jarvis_session_id is None:
                raise _invalid("an event with a context_id must name its jarvis_session_id")
        if self.kind.family in _SESSION_FAMILIES and self.jarvis_session_id is None:
            raise _invalid(f"{self.kind.value} must name its jarvis_session_id")
        if self.kind.family == "context" and self.context_id is None:
            raise _invalid(f"{self.kind.value} must name its context_id")
        for name in ("artifact_ids", "capture_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > MAX_ACTIVITY_REFS:
                raise _invalid(f"{name} must be a tuple of at most {MAX_ACTIVITY_REFS} ids")
            if len(set(values)) != len(values):
                raise _invalid(f"{name} must not repeat an id")
        for artifact_id in self.artifact_ids:
            check_prefixed_id(_invalid, "artifact_ids", artifact_id, ARTIFACT_ID_PREFIX)
        for capture_id in self.capture_ids:
            _check_capture_id(capture_id)
        object.__setattr__(self, "data", _freeze_data(self.data))

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "kind": self.kind.value, "occurred_at": self.occurred_at.isoformat(),
            "jarvis_session_id": self.jarvis_session_id, "context_id": self.context_id,
            "artifact_ids": list(self.artifact_ids), "capture_ids": list(self.capture_ids), "data": dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """Événement du ledger, ordonné par `seq` (monotone par base, jamais réutilisé)."""

    seq: int
    draft: ActivityDraft

    def __post_init__(self) -> None:
        if type(self.seq) is not int or self.seq < 1:
            raise _invalid(f"seq must be a positive integer, got {preview(self.seq)}")
        if not isinstance(self.draft, ActivityDraft):
            raise _invalid("draft must be an ActivityDraft")

    def __getattr__(self, name: str) -> Any:
        # Lecture directe des champs de l'événement (`event.kind`, `event.context_id`...).
        return getattr(object.__getattribute__(self, "draft"), name)

    def to_payload(self) -> dict[str, Any]:
        return {"seq": self.seq, **self.draft.to_payload()}

    @classmethod
    def from_payload(cls, payload: object) -> ActivityEvent:
        payload = strict_keys(_invalid, "activity", payload, _KEYS, required=_KEYS)
        for name in ("artifact_ids", "capture_ids"):
            if not isinstance(payload[name], list):
                raise _invalid(f"{name} must be a list")
        draft = ActivityDraft(
            event_id=payload["event_id"],
            kind=parse_enum(_invalid, "kind", payload["kind"], ActivityKind),
            occurred_at=parse_dt(_invalid, "occurred_at", payload["occurred_at"]),
            jarvis_session_id=payload["jarvis_session_id"], context_id=payload["context_id"],
            artifact_ids=tuple(payload["artifact_ids"]), capture_ids=tuple(payload["capture_ids"]),
            data=payload["data"],
        )
        return cls(seq=payload["seq"], draft=draft)


_KEYS = frozenset({"seq", "event_id", "kind", "occurred_at", "jarvis_session_id", "context_id", "artifact_ids",
                   "capture_ids", "data"})


@dataclass(frozen=True, slots=True)
class ActivityQuery:
    """Lecture bornée du ledger, par `seq` croissant : `after_seq` exclu (curseur de queue)."""

    after_seq: int = 0
    limit: int = DEFAULT_ACTIVITY_LIMIT
    jarvis_session_id: str | None = None
    context_id: str | None = None
    kinds: tuple[ActivityKind, ...] = ()
    since: datetime | None = None
    until: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.after_seq) is not int or self.after_seq < 0:
            raise _invalid("after_seq must be a non-negative integer")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_ACTIVITY_LIMIT:
            raise _invalid(f"limit must be an integer in 1..{MAX_ACTIVITY_LIMIT}")
        if self.jarvis_session_id is not None:
            check_prefixed_id(_invalid, "jarvis_session_id", self.jarvis_session_id, SESSION_ID_PREFIX)
        if self.context_id is not None:
            check_prefixed_id(_invalid, "context_id", self.context_id, CONTEXT_ID_PREFIX)
        if (not isinstance(self.kinds, tuple) or len(self.kinds) > MAX_ACTIVITY_KINDS_FILTER
                or not all(isinstance(kind, ActivityKind) for kind in self.kinds)):
            raise _invalid(f"kinds must be a tuple of at most {MAX_ACTIVITY_KINDS_FILTER} ActivityKind values")
        check_aware(_invalid, "since", self.since, required=False)
        check_aware(_invalid, "until", self.until, required=False)
        if self.since is not None and self.until is not None and self.until < self.since:
            raise _invalid("until must not precede since")


# ------------------------------------------------------------------ événements des transitions de Session/Context


def session_event(kind: ActivityKind, jarvis_session_id: str, *, now: datetime, origin: str,
                  context_id: str | None = None) -> ActivityDraft:
    """`session.opened|resumed|closed` ; `origin` dit qui l'a provoqué (`core_start`, `protocol`...)."""

    if kind.family != "session":
        raise _invalid(f"{kind.value} is not a session event")
    return ActivityDraft(kind=kind, occurred_at=now, jarvis_session_id=jarvis_session_id, context_id=context_id,
                         data={"origin": origin})


def context_transition_events(transition: ContextTransition, *, now: datetime, origin: str,
                              created: bool) -> tuple[ActivityDraft, ...]:
    """Événements d'une création ou d'une activation : l'ancien actif s'endort, puis le nouveau.

    Ordre identique à l'écriture (`context.dormant` avant
    `context.created|activated`) ; rien quand la transition ne change rien.
    """

    if not transition.changed:
        return ()
    return (*context_dormant_events(() if transition.dormanted is None else (transition.dormanted,),
                                    now=now, origin=origin),
            context_event(ActivityKind.CONTEXT_CREATED if created else ActivityKind.CONTEXT_ACTIVATED,
                          transition.active.jarvis_session_id, transition.active.context_id, now=now,
                          origin=origin, extra={"context_origin": transition.active.origin.value}))


def context_dormant_events(contexts: Iterable[Any], *, now: datetime, origin: str) -> tuple[ActivityDraft, ...]:
    return tuple(context_event(ActivityKind.CONTEXT_DORMANT, c.jarvis_session_id, c.context_id, now=now,
                               origin=origin) for c in contexts)


def context_event(kind: ActivityKind, jarvis_session_id: str, context_id: str, *, now: datetime, origin: str,
                  extra: Mapping[str, Any] | None = None) -> ActivityDraft:
    if kind.family != "context":
        raise _invalid(f"{kind.value} is not a context event")
    return ActivityDraft(kind=kind, occurred_at=now, jarvis_session_id=jarvis_session_id, context_id=context_id,
                         data={"origin": origin, **(extra or {})})

