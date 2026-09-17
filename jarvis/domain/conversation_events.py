"""Canonical Conversation Event contract, schema version 1.

Binding contract: `docs/conversation-events.md`. This module is the Level 3
implementation of that page: typed envelope, closed vocabularies, strict codec,
deterministic identity, duplicate/conflict rule, trace join and a pure
reconstruction of the chronological conversation.

Invariants:

- pure domain: no I/O, no implicit clock, no provider/transport import. The
  storage (Slice 02) and the producers (Slice 03) live elsewhere;
- allowlist only: envelope fields, event types, actors and attribute keys are
  closed sets. Unknown fields are rejected, never ignored;
- no hidden reasoning, raw audio/bytes, prompt, secret or raw tool argument is
  representable (Decision 12, Decision 43). Forbidden keys are rejected at any
  depth of a raw payload, with the path, never the value;
- `agent.event` (raw provider stream, thinking blocks included) is never a
  valid source: no event type maps to it and a `TraceRef` naming it is refused;
- error messages name fields and rules, never echo content or attribute values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.voice_state import state_id

CONVERSATION_EVENT_SCHEMA_VERSION = 1

#: Same bound as canonical voice admission text (`voice_admission.MAX_ADMISSION_TEXT`).
MAX_CONTENT_CHARS = 8192
MAX_ATTRIBUTES = 24
MAX_ATTRIBUTE_TEXT_CHARS = 512
MAX_ATTRIBUTE_LIST_ITEMS = 16
MAX_ATTRIBUTES_JSON_BYTES = 4096
MAX_SOURCE_IDS = 8
#: Deepest container nesting a valid payload needs is 3 (event.attributes.key[i]).
#: The redaction scan stops well above that instead of recursing without bound.
MAX_PAYLOAD_DEPTH = 8
#: Largest integer a JSON consumer (JavaScript) reads exactly.
MAX_ATTRIBUTE_INT = 2**53

_EVENT_ID = re.compile(r"cev-[0-9a-f]{64}")
_PRODUCER = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*")
_JOURNAL_KIND = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+")
_WIRE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_MAX_PRODUCER_CHARS = 64
_MAX_JOURNAL_KIND_CHARS = 96
_MAX_NAME_IN_MESSAGE = 64


class ConversationEventError(ValueError):
    """Invalid conversation event. The message names the field, never its value."""


class ConversationEventRedactionError(ConversationEventError):
    """A forbidden (private/unsafe) key or raw byte payload was offered."""


class ConversationEventConflictError(ConversationEventError):
    """Same `event_id`, different payload: two facts claim one identity."""


class ConversationActor(StrEnum):
    USER = "user"
    #: Jarvis voice output: brain speech played by the surface, and reflexes.
    MOUTH = "mouth"
    BRAIN = "brain"
    SUBAGENT = "subagent"
    TOOL = "tool"
    SYSTEM = "system"


class ConversationVisibility(StrEnum):
    #: What the user said, heard, or was shown.
    PUBLIC = "public"
    #: Execution evidence for the debug timeline only.
    DIAGNOSTIC = "diagnostic"


class EventShape(StrEnum):
    INSTANT = "instant"
    SPAN_OPEN = "span_open"
    SPAN_CLOSE = "span_close"


class ConversationEventType(StrEnum):
    USER_TRANSCRIPT_ACCEPTED = "user.transcript.accepted"
    BRAIN_TURN_ACCEPTED = "brain.turn.accepted"
    BRAIN_TURN_FAILED = "brain.turn.failed"
    BRAIN_MESSAGE_PUBLISHED = "brain.message.published"
    BRAIN_SPEECH_REQUESTED = "brain.speech.requested"
    BRAIN_WORK_STARTED = "brain.work.started"
    BRAIN_WORK_COMPLETED = "brain.work.completed"
    BRAIN_WORK_FAILED = "brain.work.failed"
    BRAIN_WORK_CANCELLED = "brain.work.cancelled"
    MOUTH_SPEECH_QUEUED = "mouth.speech.queued"
    MOUTH_SPEECH_STARTED = "mouth.speech.started"
    MOUTH_SPEECH_COMPLETED = "mouth.speech.completed"
    MOUTH_SPEECH_INTERRUPTED = "mouth.speech.interrupted"
    MOUTH_SPEECH_SUPERSEDED = "mouth.speech.superseded"
    MOUTH_SPEECH_EXPIRED = "mouth.speech.expired"
    MOUTH_SPEECH_FAILED = "mouth.speech.failed"
    MOUTH_REFLEX_STARTED = "mouth.reflex.started"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_FINISHED = "subagent.finished"
    SUBAGENT_FAILED = "subagent.failed"
    SUBAGENT_STOPPED = "subagent.stopped"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_FINISHED = "tool.call.finished"
    SYSTEM_FAILURE = "system.failure"


@dataclass(frozen=True, slots=True)
class _Spec:
    actor: ConversationActor
    shape: EventShape
    visibility: ConversationVisibility
    required: frozenset[str]
    content: str  # "required" | "optional" | "forbidden"
    #: Correlation field `span_id` must equal, when the span has a natural id.
    span_field: str | None = None


_A, _S, _V, _T = ConversationActor, EventShape, ConversationVisibility, ConversationEventType


def _spec(actor, shape, visibility, required=(), content="optional", span_field=None) -> _Spec:
    return _Spec(actor, shape, visibility, frozenset(required), content, span_field)


_SPECS: dict[ConversationEventType, _Spec] = {
    _T.USER_TRANSCRIPT_ACCEPTED: _spec(_A.USER, _S.INSTANT, _V.PUBLIC, ("correlation_id", "turn_id"), "required"),
    _T.BRAIN_TURN_ACCEPTED: _spec(_A.BRAIN, _S.INSTANT, _V.DIAGNOSTIC, ("correlation_id", "turn_id"), "forbidden"),
    # A failure's only text today is a raw error string (`core.brain.turn_failed`
    # data.error): never content, only allowlisted code/error_class attributes.
    _T.BRAIN_TURN_FAILED: _spec(_A.BRAIN, _S.INSTANT, _V.DIAGNOSTIC, ("correlation_id",), "forbidden"),
    _T.BRAIN_MESSAGE_PUBLISHED: _spec(_A.BRAIN, _S.INSTANT, _V.PUBLIC, ("correlation_id", "outcome_id"), "required"),
    _T.BRAIN_SPEECH_REQUESTED: _spec(_A.BRAIN, _S.INSTANT, _V.DIAGNOSTIC, ("correlation_id", "speech_id"), "required"),
    _T.BRAIN_WORK_STARTED: _spec(_A.BRAIN, _S.SPAN_OPEN, _V.DIAGNOSTIC, ("correlation_id", "work_id"), span_field="work_id"),
    _T.BRAIN_WORK_COMPLETED: _spec(_A.BRAIN, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("correlation_id", "work_id"), span_field="work_id"),
    _T.BRAIN_WORK_FAILED: _spec(_A.BRAIN, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("correlation_id", "work_id"), span_field="work_id"),
    _T.BRAIN_WORK_CANCELLED: _spec(_A.BRAIN, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("correlation_id", "work_id"), span_field="work_id"),
    _T.MOUTH_SPEECH_QUEUED: _spec(_A.MOUTH, _S.INSTANT, _V.DIAGNOSTIC, ("correlation_id", "speech_id")),
    _T.MOUTH_SPEECH_STARTED: _spec(_A.MOUTH, _S.SPAN_OPEN, _V.PUBLIC, ("correlation_id", "speech_id"), span_field="speech_id"),
    _T.MOUTH_SPEECH_COMPLETED: _spec(_A.MOUTH, _S.SPAN_CLOSE, _V.PUBLIC, ("correlation_id", "speech_id"), span_field="speech_id"),
    _T.MOUTH_SPEECH_INTERRUPTED: _spec(_A.MOUTH, _S.SPAN_CLOSE, _V.PUBLIC, ("correlation_id", "speech_id"), span_field="speech_id"),
    _T.MOUTH_SPEECH_SUPERSEDED: _spec(_A.MOUTH, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("correlation_id", "speech_id"), span_field="speech_id"),
    _T.MOUTH_SPEECH_EXPIRED: _spec(_A.MOUTH, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("correlation_id", "speech_id"), span_field="speech_id"),
    _T.MOUTH_SPEECH_FAILED: _spec(_A.MOUTH, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("correlation_id", "speech_id"), span_field="speech_id"),
    # Instant on purpose: the journal has `voice.reflex.started` but no reflex
    # completion/interruption, so a span would stay open forever.
    _T.MOUTH_REFLEX_STARTED: _spec(_A.MOUTH, _S.INSTANT, _V.PUBLIC, ("correlation_id",)),
    _T.SUBAGENT_STARTED: _spec(_A.SUBAGENT, _S.SPAN_OPEN, _V.DIAGNOSTIC, ("task_id",), span_field="task_id"),
    _T.SUBAGENT_FINISHED: _spec(_A.SUBAGENT, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("task_id",), span_field="task_id"),
    _T.SUBAGENT_FAILED: _spec(_A.SUBAGENT, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("task_id",), span_field="task_id"),
    _T.SUBAGENT_STOPPED: _spec(_A.SUBAGENT, _S.SPAN_CLOSE, _V.DIAGNOSTIC, ("task_id",), span_field="task_id"),
    _T.TOOL_CALL_STARTED: _spec(_A.TOOL, _S.SPAN_OPEN, _V.DIAGNOSTIC, content="forbidden"),
    _T.TOOL_CALL_FINISHED: _spec(_A.TOOL, _S.SPAN_CLOSE, _V.DIAGNOSTIC, content="forbidden"),
    _T.SYSTEM_FAILURE: _spec(_A.SYSTEM, _S.INSTANT, _V.DIAGNOSTIC, content="forbidden"),
}

#: Span close type -> the open type it closes. Pairing key: (open type, span_id).
SPAN_OPENER: dict[ConversationEventType, ConversationEventType] = {
    _T.BRAIN_WORK_COMPLETED: _T.BRAIN_WORK_STARTED,
    _T.BRAIN_WORK_FAILED: _T.BRAIN_WORK_STARTED,
    _T.BRAIN_WORK_CANCELLED: _T.BRAIN_WORK_STARTED,
    _T.MOUTH_SPEECH_COMPLETED: _T.MOUTH_SPEECH_STARTED,
    _T.MOUTH_SPEECH_INTERRUPTED: _T.MOUTH_SPEECH_STARTED,
    _T.MOUTH_SPEECH_SUPERSEDED: _T.MOUTH_SPEECH_STARTED,
    _T.MOUTH_SPEECH_EXPIRED: _T.MOUTH_SPEECH_STARTED,
    _T.MOUTH_SPEECH_FAILED: _T.MOUTH_SPEECH_STARTED,
    _T.SUBAGENT_FINISHED: _T.SUBAGENT_STARTED,
    _T.SUBAGENT_FAILED: _T.SUBAGENT_STARTED,
    _T.SUBAGENT_STOPPED: _T.SUBAGENT_STARTED,
    _T.TOOL_CALL_FINISHED: _T.TOOL_CALL_STARTED,
}


def event_actor(event_type: ConversationEventType) -> ConversationActor:
    return _SPECS[event_type].actor


def event_shape(event_type: ConversationEventType) -> EventShape:
    return _SPECS[event_type].shape


def event_visibility(event_type: ConversationEventType) -> ConversationVisibility:
    return _SPECS[event_type].visibility


# --------------------------------------------------------------- redaction

#: Attribute allowlist. Anything else is rejected, whatever its value.
ATTRIBUTE_KEYS = frozenset({
    "addressing", "arguments_redacted", "background", "code", "delivery", "depth", "duplicate",
    "duration_ms", "error_class", "interrupted_speech_id", "job_id", "kind", "model",
    "output_id", "played_ms", "priority", "provider", "reason", "revision", "source", "status",
    "subagent_type", "tokens", "tool_name", "tool_uses",
})

#: Defense in depth over the allowlist: these names are refused anywhere in a
#: raw payload (top level, trace_ref, attributes, nested values) with a
#: redaction error, so a leak is reported as a leak, not as a typo.
_FORBIDDEN_KEYS = frozenset({
    "chain_of_thought", "chainofthought", "system_prompt", "systemprompt", "api_key", "apikey",
    "raw_arguments", "tool_input", "input", "access_token", "refresh_token",
})
_FORBIDDEN_SEGMENTS = frozenset({
    "reasoning", "thinking", "thought", "thoughts", "scratchpad", "cot", "audio", "pcm", "wav",
    "bytes", "prompt", "prompts", "secret", "secrets", "password", "token", "credential",
    "credentials", "authorization", "cookie", "arguments", "args", "signature",
})


def is_forbidden_key(key: str) -> bool:
    """True when a key names private/unsafe data. Allowlisted attribute names never are."""
    if key in ATTRIBUTE_KEYS:
        return False
    normalized = _CAMEL.sub("_", key).lower().replace("-", "_").replace(".", "_").replace(" ", "_")
    return normalized in _FORBIDDEN_KEYS or any(part in _FORBIDDEN_SEGMENTS for part in normalized.split("_"))


def _name(value: object) -> str:
    """Field name safe to put in a message: bounded, and lone surrogates escaped."""
    text = str(value)
    text = text if len(text) <= _MAX_NAME_IN_MESSAGE else text[:_MAX_NAME_IN_MESSAGE] + "..."
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _utf8_text(value: str, name: str) -> None:
    """Lone surrogates cannot be stored or sent as UTF-8 JSON: reject them as invalid data."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ConversationEventError(f"{name} must be valid Unicode text (lone surrogate)") from None


def _scan_forbidden(value: object, path: str, depth: int = 0) -> None:
    if depth > MAX_PAYLOAD_DEPTH:
        raise ConversationEventError(f"{path}: nesting exceeds {MAX_PAYLOAD_DEPTH} levels")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ConversationEventRedactionError(f"{path}: raw bytes are forbidden in conversation events")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConversationEventError(f"{path}: object keys must be strings")
            if is_forbidden_key(key):
                raise ConversationEventRedactionError(f"{path}.{_name(key)}: forbidden field (private or unsafe data)")
            _scan_forbidden(item, f"{path}.{_name(key)}", depth + 1)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_forbidden(item, f"{path}[{index}]", depth + 1)


def _attribute_scalar(value: object, path: str) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > MAX_ATTRIBUTE_INT:
            raise ConversationEventError(f"{path} integer exceeds {MAX_ATTRIBUTE_INT}")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ConversationEventError(f"{path} must be a finite number")
        return
    if isinstance(value, str):
        if len(value) > MAX_ATTRIBUTE_TEXT_CHARS:
            raise ConversationEventError(f"{path} exceeds {MAX_ATTRIBUTE_TEXT_CHARS} characters")
        _utf8_text(value, path)
        return
    raise ConversationEventError(f"{path} must be a JSON scalar or a list of JSON scalars")


def _frozen_attributes(attributes: object) -> Mapping[str, Any]:
    if not isinstance(attributes, Mapping):
        raise ConversationEventError("attributes must be an object")
    _scan_forbidden(attributes, "attributes")
    if len(attributes) > MAX_ATTRIBUTES:
        raise ConversationEventError(f"attributes exceed {MAX_ATTRIBUTES} keys")
    frozen: dict[str, Any] = {}
    for key, value in attributes.items():
        path = f"attributes.{_name(key)}"
        if key not in ATTRIBUTE_KEYS:
            raise ConversationEventError(f"{path}: attribute is not in the allowlist")
        if isinstance(value, (list, tuple)):
            if len(value) > MAX_ATTRIBUTE_LIST_ITEMS:
                raise ConversationEventError(f"{path} exceeds {MAX_ATTRIBUTE_LIST_ITEMS} items")
            for index, item in enumerate(value):
                _attribute_scalar(item, f"{path}[{index}]")
            value = tuple(value)
        else:
            _attribute_scalar(value, path)
        frozen[key] = value
    size = len(json.dumps(frozen, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_ATTRIBUTES_JSON_BYTES:
        raise ConversationEventError(f"attributes exceed {MAX_ATTRIBUTES_JSON_BYTES} encoded bytes")
    return MappingProxyType(frozen)


# ------------------------------------------------------------ small checks

def _opaque_id(value: object, name: str, *, optional: bool = False) -> None:
    """Opaque id, compared exactly (code points, no Unicode normalization, no case folding)."""
    try:
        state_id(value, name, optional=optional)
    except ValueError as exc:
        raise ConversationEventError(str(exc)) from None
    if value is not None:
        _utf8_text(value, name)


def _event_id(value: object, name: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        raise ConversationEventError(f"{name} must match cev-<64 lowercase hex>")


def _producer(value: object) -> None:
    if not isinstance(value, str) or len(value) > _MAX_PRODUCER_CHARS or not _PRODUCER.fullmatch(value):
        raise ConversationEventError(f"producer must be a dotted lowercase token of at most {_MAX_PRODUCER_CHARS} characters")


def _utc_ms(value: object, name: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ConversationEventError(f"{name} must be a timezone-aware datetime")
    if value.utcoffset().total_seconds() != 0:
        raise ConversationEventError(f"{name} must be UTC")
    if value.microsecond % 1000:
        raise ConversationEventError(f"{name} must have millisecond precision (use to_event_time)")


def to_event_time(value: datetime) -> datetime:
    """Normalize a producer clock reading to the contract: UTC, millisecond precision."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ConversationEventError("event time must be a timezone-aware datetime")
    value = value.astimezone(timezone.utc)
    return value.replace(microsecond=value.microsecond - value.microsecond % 1000)


def _format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def format_event_time(value: datetime) -> str:
    """Wire form `YYYY-MM-DDTHH:MM:SS.mmmZ` of any aware time (normalized by `to_event_time`).

    Fixed width, so wire times sort lexicographically in chronological order:
    the store (Slice 02) indexes and compares them as text.
    """
    return _format_time(to_event_time(value))


def parse_event_time(value: object, name: str = "time") -> datetime:
    """Strict inverse of `format_event_time`: only `YYYY-MM-DDTHH:MM:SS.mmmZ` of a real calendar time.

    Raises `ConversationEventError` naming `name`, never echoing the value.
    """
    if value is None:
        raise ConversationEventError(f"{name} is required")
    return _parse_time(value, name)


def _parse_time(value: object, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _WIRE_TIME.fullmatch(value):
        raise ConversationEventError(f"{name} must be UTC ISO-8601 with milliseconds (YYYY-MM-DDTHH:MM:SS.mmmZ)")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ConversationEventError(f"{name} is not a valid calendar time") from None


# --------------------------------------------------------------- trace join

class TraceSource(StrEnum):
    #: `runtime/trace.jsonl` (`RuntimeJournal`), joined by kind + keys.
    RUNTIME_JOURNAL = "runtime_journal"
    #: Control Center agent task trace, opened by `task_id` (`AgentTaskTracker.find`).
    AGENT_TASK = "agent_task"


#: Event correlation fields a trace join may require, named as in journal `data`.
TRACE_JOIN_FIELDS = ("conversation_id", "session_id", "turn_id", "correlation_id", "task_id", "work_id",
                     "speech_id", "outcome_id")
#: Journal `data` key carrying the conversation event id (instrumentation, Slice 03).
TRACE_EVENT_ID_KEY = "conversation_event_id"
_RAW_PROVIDER_STREAM_KIND = "agent.event"


@dataclass(frozen=True, slots=True)
class TraceRef:
    """How to find the diagnostic evidence of an event. `trace_id` does not exist in Jarvis."""

    source: TraceSource
    journal_kind: str | None = None
    join_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, TraceSource):
            raise ConversationEventError("trace_ref.source has an invalid value")
        if not isinstance(self.join_keys, tuple) or any(not isinstance(key, str) for key in self.join_keys):
            raise ConversationEventError("trace_ref.join_keys must be a list of field names")
        if len(set(self.join_keys)) != len(self.join_keys) or not set(self.join_keys) <= set(TRACE_JOIN_FIELDS):
            raise ConversationEventError(f"trace_ref.join_keys must be distinct names among {', '.join(TRACE_JOIN_FIELDS)}")
        if self.source is TraceSource.AGENT_TASK:
            if self.journal_kind is not None or self.join_keys != ("task_id",):
                raise ConversationEventError("trace_ref agent_task requires join_keys [task_id] and no journal_kind")
            return
        kind = self.journal_kind
        if (not isinstance(kind, str) or len(kind) > _MAX_JOURNAL_KIND_CHARS
                or not _JOURNAL_KIND.fullmatch(kind)):
            raise ConversationEventError("trace_ref.journal_kind must be a dotted RuntimeJournal kind")
        if kind == _RAW_PROVIDER_STREAM_KIND or kind.startswith(_RAW_PROVIDER_STREAM_KIND + "."):
            raise ConversationEventRedactionError(
                "trace_ref.journal_kind: agent.event (raw provider stream) is never a conversation event source")


def trace_entry_matches(event: ConversationEvent, entry: Mapping[str, Any]) -> bool:
    """True when a decoded `RuntimeJournal` line is diagnostic evidence of `event`.

    Rule: same `kind`; then `data.conversation_event_id` decides when present;
    otherwise every `join_keys` field must be equal in `data`. No keys and no
    event id means no join (never a kind-only match).
    """
    ref = event.trace_ref
    if ref is None:
        return False
    if ref.source is not TraceSource.RUNTIME_JOURNAL:
        raise ConversationEventError("trace_entry_matches only joins runtime_journal references")
    data = entry.get("data")
    if entry.get("kind") != ref.journal_kind or not isinstance(data, Mapping):
        return False
    if TRACE_EVENT_ID_KEY in data:
        return data[TRACE_EVENT_ID_KEY] == event.event_id
    return bool(ref.join_keys) and all(data.get(key) == getattr(event, key) for key in ref.join_keys)


# ------------------------------------------------------------------ envelope

_OPTIONAL_IDS = ("span_id", "session_id", "turn_id", "correlation_id", "task_id", "work_id", "speech_id", "outcome_id")


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    """One backend-observed conversation fact. Construct validates; invalid never exists."""

    event_id: str
    event_type: ConversationEventType
    actor: ConversationActor
    conversation_id: str
    producer: str
    visibility: ConversationVisibility
    occurred_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    span_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    correlation_id: str | None = None
    parent_event_id: str | None = None
    task_id: str | None = None
    work_id: str | None = None
    speech_id: str | None = None
    outcome_id: str | None = None
    trace_ref: TraceRef | None = None
    content: str | None = None
    #: Read-only after construction (`MappingProxyType`); lists become tuples.
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = CONVERSATION_EVENT_SCHEMA_VERSION

    def __hash__(self) -> int:
        # Equal events share an event_id, so hashing the id is consistent with
        # __eq__; the attribute mapping itself is not hashable.
        return hash(self.event_id)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != CONVERSATION_EVENT_SCHEMA_VERSION:
            raise ConversationEventError(f"unsupported schema_version; expected {CONVERSATION_EVENT_SCHEMA_VERSION}")
        _event_id(self.event_id, "event_id")
        _event_id(self.parent_event_id, "parent_event_id", optional=True)
        if self.parent_event_id == self.event_id:
            raise ConversationEventError("parent_event_id must differ from event_id")
        if not isinstance(self.event_type, ConversationEventType):
            raise ConversationEventError("event_type is not in the vocabulary")
        spec = _SPECS[self.event_type]
        if not isinstance(self.actor, ConversationActor):
            raise ConversationEventError("actor is not in the vocabulary")
        if self.actor is not spec.actor:
            raise ConversationEventError(f"actor for {self.event_type.value} must be {spec.actor.value}")
        if not isinstance(self.visibility, ConversationVisibility):
            raise ConversationEventError("visibility has an invalid value")
        if self.visibility is not spec.visibility:
            raise ConversationEventError(f"visibility for {self.event_type.value} must be {spec.visibility.value}")
        _opaque_id(self.conversation_id, "conversation_id")
        _producer(self.producer)
        for name in _OPTIONAL_IDS:
            _opaque_id(getattr(self, name), name, optional=True)
        for name in sorted(spec.required):
            if getattr(self, name) is None:
                raise ConversationEventError(f"{name} is required for {self.event_type.value}")
        self._check_times(spec)
        self._check_content(spec)
        if self.trace_ref is not None:
            if not isinstance(self.trace_ref, TraceRef):
                raise ConversationEventError("trace_ref must be a TraceRef")
            if (spec.actor is ConversationActor.TOOL and self.trace_ref.source is TraceSource.RUNTIME_JOURNAL
                    and self.trace_ref.join_keys):
                # `tool.call` / `tool.result` lines carry only {call_id, arguments}:
                # a key join would be ambiguous, only conversation_event_id may join.
                raise ConversationEventError("trace_ref for tool events must join by conversation_event_id only (no join_keys)")
            for key in self.trace_ref.join_keys:
                if getattr(self, key) is None:
                    raise ConversationEventError(f"trace_ref.join_keys names {key}, which is not set on the event")
        object.__setattr__(self, "attributes", _frozen_attributes(self.attributes))

    def _check_times(self, spec: _Spec) -> None:
        _utc_ms(self.occurred_at, "occurred_at")
        _utc_ms(self.started_at, "started_at", optional=True)
        _utc_ms(self.ended_at, "ended_at", optional=True)
        kind = self.event_type.value
        if spec.shape is EventShape.INSTANT:
            if self.started_at is not None or self.ended_at is not None or self.span_id is not None:
                raise ConversationEventError(f"{kind} is instant: started_at, ended_at and span_id must be null")
            return
        if self.span_id is None:
            raise ConversationEventError(f"span_id is required for {kind}")
        if spec.span_field is not None and self.span_id != getattr(self, spec.span_field):
            raise ConversationEventError(f"span_id for {kind} must equal {spec.span_field}")
        if spec.shape is EventShape.SPAN_OPEN:
            if self.started_at != self.occurred_at or self.ended_at is not None:
                raise ConversationEventError(f"{kind} opens a span: started_at must equal occurred_at and ended_at must be null")
            return
        if self.ended_at != self.occurred_at:
            raise ConversationEventError(f"{kind} closes a span: ended_at must equal occurred_at")
        if self.started_at is not None and self.started_at > self.ended_at:
            raise ConversationEventError(f"{kind}: span ends before it starts")

    def _check_content(self, spec: _Spec) -> None:
        if self.content is None:
            if spec.content == "required":
                raise ConversationEventError(f"content is required for {self.event_type.value}")
            return
        if spec.content == "forbidden":
            raise ConversationEventError(f"content must be null for {self.event_type.value}")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ConversationEventError("content must be nonblank text or null")
        if len(self.content) > MAX_CONTENT_CHARS:
            raise ConversationEventError(f"content exceeds {MAX_CONTENT_CHARS} characters")
        _utf8_text(self.content, "content")


EVENT_FIELDS = tuple(item.name for item in fields(ConversationEvent))
_TRACE_REF_FIELDS = frozenset({"source", "journal_kind", "join_keys"})


# -------------------------------------------------------------- identity

def derive_conversation_event_id(*, producer: str, event_type: ConversationEventType,
                                 conversation_id: str, source_ids: tuple[str, ...]) -> str:
    """Deterministic id from the source identity. Same fact re-emitted -> same id.

    `source_ids` are the producer's own ids for the fact (see the contract's
    table), never a list position, counter or wall-clock reading.
    """
    _producer(producer)
    if not isinstance(event_type, ConversationEventType):
        raise ConversationEventError("event_type is not in the vocabulary")
    _opaque_id(conversation_id, "conversation_id")
    if not isinstance(source_ids, tuple) or not source_ids or len(source_ids) > MAX_SOURCE_IDS:
        raise ConversationEventError(f"source_ids must be a tuple of 1 to {MAX_SOURCE_IDS} ids")
    for index, value in enumerate(source_ids):
        _opaque_id(value, f"source_ids[{index}]")
    material = json.dumps(["conversation-event", producer, event_type.value, conversation_id, *source_ids],
                          ensure_ascii=False, separators=(",", ":"))
    return "cev-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def is_duplicate_event(existing: ConversationEvent, incoming: ConversationEvent) -> bool:
    """Append rule. True: identical replay (no-op). False: distinct events. Raises on conflict."""
    if existing.event_id != incoming.event_id:
        return False
    if existing != incoming:
        raise ConversationEventConflictError("event_id already recorded with a different payload")
    return True


def unsequenced_order_key(event: ConversationEvent) -> tuple[datetime, str]:
    """Deterministic order when no store sequence is available: (occurred_at, event_id)."""
    return (event.occurred_at, event.event_id)


# ------------------------------------------------------------------- codec

def encode_conversation_event(event: ConversationEvent) -> dict[str, Any]:
    """JSON-ready dict. Re-decoded before return: a mutated attribute dict cannot leak out."""
    if not isinstance(event, ConversationEvent):
        raise ConversationEventError("only ConversationEvent can be encoded")
    ref = event.trace_ref
    payload: dict[str, Any] = {
        "schema_version": event.schema_version,
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "actor": event.actor.value,
        "conversation_id": event.conversation_id,
        "producer": event.producer,
        "visibility": event.visibility.value,
        "occurred_at": _format_time(event.occurred_at),
        "started_at": _format_time(event.started_at),
        "ended_at": _format_time(event.ended_at),
        **{name: getattr(event, name) for name in ("span_id", "session_id", "turn_id", "correlation_id",
                                                   "parent_event_id", "task_id", "work_id", "speech_id",
                                                   "outcome_id")},
        "trace_ref": None if ref is None else {"source": ref.source.value, "journal_kind": ref.journal_kind,
                                               "join_keys": list(ref.join_keys)},
        "content": event.content,
        "attributes": {key: list(value) if isinstance(value, tuple) else value
                       for key, value in event.attributes.items()},
    }
    decode_conversation_event(payload)
    return payload


def _enum(enum: type[StrEnum], value: object, name: str) -> Any:
    if not isinstance(value, str):
        raise ConversationEventError(f"{name} must be a string")
    try:
        return enum(value)
    except ValueError:
        raise ConversationEventError(f"{name} is not in the vocabulary") from None


def _decode_trace_ref(value: object) -> TraceRef | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConversationEventError("trace_ref must be an object or null")
    if set(value) != _TRACE_REF_FIELDS:
        raise ConversationEventError(f"trace_ref must have exactly the fields {', '.join(sorted(_TRACE_REF_FIELDS))}")
    if not isinstance(value["join_keys"], list):
        raise ConversationEventError("trace_ref.join_keys must be a list of field names")
    return TraceRef(_enum(TraceSource, value["source"], "trace_ref.source"), value["journal_kind"],
                    tuple(value["join_keys"]))


def decode_conversation_event(payload: object) -> ConversationEvent:
    """Strict decode: exact fields, version 1, closed vocabularies, redaction first."""
    if not isinstance(payload, Mapping):
        raise ConversationEventError("conversation event must be a JSON object")
    _scan_forbidden(payload, "event")
    unknown = sorted(_name(key) for key in set(payload) - set(EVENT_FIELDS))
    if unknown:
        raise ConversationEventError(f"unknown field(s): {', '.join(unknown)}")
    missing = sorted(set(EVENT_FIELDS) - set(payload))
    if missing:
        raise ConversationEventError(f"missing field(s): {', '.join(missing)}")
    version = payload["schema_version"]
    if type(version) is not int or version != CONVERSATION_EVENT_SCHEMA_VERSION:
        raise ConversationEventError(f"unsupported schema_version; expected {CONVERSATION_EVENT_SCHEMA_VERSION}")
    data = dict(payload)
    data["event_type"] = _enum(ConversationEventType, data["event_type"], "event_type")
    data["actor"] = _enum(ConversationActor, data["actor"], "actor")
    data["visibility"] = _enum(ConversationVisibility, data["visibility"], "visibility")
    if data["occurred_at"] is None:
        raise ConversationEventError("occurred_at is required")
    for name in ("occurred_at", "started_at", "ended_at"):
        data[name] = _parse_time(data[name], name)
    data["trace_ref"] = _decode_trace_ref(data["trace_ref"])
    return ConversationEvent(**data)


def validate_conversation_event(payload: object) -> None:
    """Raise `ConversationEventError` (or a subclass) with a precise message when invalid."""
    decode_conversation_event(payload)


# ---------------------------------------------------------- reconstruction

#: Anomaly codes recorded on an item, each as "<code>:<event_id>" of the event concerned.
ANOMALY_CONFLICTING_DUPLICATE = "conflicting_duplicate"
ANOMALY_DUPLICATE_SPAN_OPEN = "duplicate_span_open"
ANOMALY_DUPLICATE_SPAN_CLOSE = "duplicate_span_close"
ANOMALY_CLOSE_BEFORE_OPEN = "close_before_open"


@dataclass(frozen=True, slots=True)
class ConversationItem:
    """One row of the reconstructed conversation: an instant or a (possibly open) span."""

    item_id: str
    actor: ConversationActor
    event_type: ConversationEventType
    status: str
    visibility: ConversationVisibility
    started_at: datetime
    #: Equal to `started_at` for an instant; None while a span is still open.
    ended_at: datetime | None
    text: str | None
    span_id: str | None
    event_ids: tuple[str, ...]
    #: Inconsistent evidence absorbed while building this item (see ANOMALY_*).
    anomalies: tuple[str, ...] = ()


def _status(event_type: ConversationEventType) -> str:
    return event_type.value.rsplit(".", 1)[1]


def _item(event: ConversationEvent, *, status: str, started_at: datetime, ended_at: datetime | None,
          text: str | None, event_ids: tuple[str, ...], anomalies: list[str]) -> ConversationItem:
    return ConversationItem(event.event_id, event.actor, event.event_type, status, event.visibility, started_at,
                            ended_at, text, event.span_id, event_ids, tuple(anomalies))


def reconstruct_conversation(events: Iterable[ConversationEvent], *,
                             include_diagnostic: bool = True) -> tuple[ConversationItem, ...]:
    """Chronological conversation of one `conversation_id`, from events alone.

    Never raises on inconsistent data, because a viewer must still render a
    damaged record; it records `anomalies` on the affected item instead:

    - same event_id, different payload: the first copy received is kept;
    - several opens/closes for one span: the earliest by (occurred_at, event_id)
      is used, the others are listed;
    - close earlier than its open: `ended_at` is clamped to the start.

    Spans pair by (open type, span_id) regardless of arrival order; a close
    without its open is shown from its `started_at` (or as an instant); an open
    without close stays `open`. Items sort by (started_at, item_id). Raises
    only for non-event input or events of several conversations.
    """
    unique: dict[str, ConversationEvent] = {}
    conflicts: dict[str, None] = {}
    conversation_id: str | None = None
    for event in events:
        if not isinstance(event, ConversationEvent):
            raise ConversationEventError("reconstruction accepts ConversationEvent values only")
        if conversation_id is None:
            conversation_id = event.conversation_id
        elif event.conversation_id != conversation_id:
            raise ConversationEventError("reconstruction received events from several conversations")
        known = unique.setdefault(event.event_id, event)
        if known != event:
            conflicts[event.event_id] = None
    ordered = sorted(unique.values(), key=unsequenced_order_key)
    opens: dict[tuple[ConversationEventType, str], list[ConversationEvent]] = {}
    closes: dict[tuple[ConversationEventType, str], list[ConversationEvent]] = {}
    for event in ordered:
        shape = _SPECS[event.event_type].shape
        if shape is EventShape.SPAN_OPEN:
            opens.setdefault((event.event_type, event.span_id), []).append(event)
        elif shape is EventShape.SPAN_CLOSE:
            closes.setdefault((SPAN_OPENER[event.event_type], event.span_id), []).append(event)

    items: list[ConversationItem] = []
    owner: dict[str, int] = {}

    def extras(code: str, candidates: list[ConversationEvent], anomalies: list[str]) -> None:
        for extra in candidates[1:]:
            anomalies.append(f"{code}:{extra.event_id}")
            owner[extra.event_id] = len(items)

    for event in ordered:
        shape = _SPECS[event.event_type].shape
        anomalies: list[str] = []
        if shape is EventShape.INSTANT:
            owner[event.event_id] = len(items)
            items.append(_item(event, status=_status(event.event_type), started_at=event.occurred_at,
                               ended_at=event.occurred_at, text=event.content, event_ids=(event.event_id,),
                               anomalies=anomalies))
        elif shape is EventShape.SPAN_OPEN:
            key = (event.event_type, event.span_id)
            if opens[key][0] is not event:
                continue
            extras(ANOMALY_DUPLICATE_SPAN_OPEN, opens[key], anomalies)
            owner[event.event_id] = len(items)
            close_list = closes.get(key)
            if not close_list:
                items.append(_item(event, status="open", started_at=event.occurred_at, ended_at=None,
                                   text=event.content, event_ids=(event.event_id,), anomalies=anomalies))
                continue
            close = close_list[0]
            extras(ANOMALY_DUPLICATE_SPAN_CLOSE, close_list, anomalies)
            owner[close.event_id] = len(items)
            ended_at = close.ended_at
            if ended_at < event.occurred_at:
                anomalies.append(f"{ANOMALY_CLOSE_BEFORE_OPEN}:{close.event_id}")
                ended_at = event.occurred_at
            items.append(_item(event, status=_status(close.event_type), started_at=event.occurred_at,
                               ended_at=ended_at, text=close.content if close.content is not None else event.content,
                               event_ids=(event.event_id, close.event_id), anomalies=anomalies))
        else:
            key = (SPAN_OPENER[event.event_type], event.span_id)
            if key in opens or closes[key][0] is not event:
                continue
            extras(ANOMALY_DUPLICATE_SPAN_CLOSE, closes[key], anomalies)
            owner[event.event_id] = len(items)
            started = event.started_at if event.started_at is not None else event.occurred_at
            items.append(_item(event, status=_status(event.event_type), started_at=started, ended_at=event.occurred_at,
                               text=event.content, event_ids=(event.event_id,), anomalies=anomalies))
    for event_id in conflicts:
        index = owner[event_id]
        item = items[index]
        items[index] = replace(item, anomalies=(*item.anomalies, f"{ANOMALY_CONFLICTING_DUPLICATE}:{event_id}"))
    if not include_diagnostic:
        items = [item for item in items if item.visibility is ConversationVisibility.PUBLIC]
    items.sort(key=lambda item: (item.started_at, item.item_id))
    return tuple(items)
