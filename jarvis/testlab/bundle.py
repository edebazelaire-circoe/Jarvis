"""DiagnosticBundle: the normalized, versioned evidence document of one real Jarvis session.

Binding contract: `docs/testlab.md` ("DiagnosticBundle"). Pure: no I/O, no
clock. The builder (`bundle_builder.py`) derives the document mechanically from
Conversation Events and `RuntimeJournal` lines; this module owns its schema and
strict codec.

Invariants checked by `DiagnosticBundle` construction and `from_dict`:

- self-describing (`schema` + `schema_version`), every object has exactly its
  fields, closed vocabularies, bounded lists and a bounded encoded size;
- provenance: every derived item (turn, speech, terminal, playback, barge-in episode,
  provider event, latency stage, reported measure, report, finding) lists at
  least one evidence reference, and every reference resolves in `references`;
- consistency: rule rows and findings, speech outcomes and terminals, and the
  sources behind references must agree (a re-fingerprinted edit is still refused);
- identity: `content_fingerprint` is the fingerprint of the document without
  `bundle_id`, `content_fingerprint` and `capture` (capture context), and
  `bundle_id` is `format_bundle_id(<id time>, content_fingerprint[:16])`, so the
  same evidence always yields the same id (idempotent re-import);
- privacy: the private-name rule is applied at every depth (`scan_private`).
  Text appears only in `turns[].content` (public conversation content).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.conversation_events import MAX_CONTENT_CHARS, ConversationEventType, ConversationVisibility
from jarvis.domain.voice_state import state_id
from jarvis.testlab.identity import (
    DIAGNOSTIC_BUNDLE_SCHEMA,
    TESTLAB_SCHEMA_VERSION,
    check_bundle_id,
    format_bundle_id,
)
from jarvis.testlab.validation import (
    LIMIT_EXCEEDED,
    MAX_JSON_INT,
    REFERENCE_INVALID,
    canonical_json,
    check_document_header,
    content_fingerprint,
    decode_json_document,
    exact_fields,
    fail,
    parse_time,
    scan_private,
)

BUNDLE_SCHEMA_VERSION = TESTLAB_SCHEMA_VERSION
#: Largest encoded bundle (canonical JSON). The builder caps sections well below it.
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_REFS = 32
MAX_IDS = 64

#: Section caps. Items past a cap are dropped by the builder and counted in `coverage.limits`.
SECTION_LIMITS: Mapping[str, int] = MappingProxyType({
    "turns": 4096,
    "speech": 2048,
    "playback": 2048,
    "barge_in": 1024,
    "provider": 1024,
    "user_activity": 4096,
    "lifecycle": 1024,
    "brain": 2048,
    "usage": 1024,
    "latency": 2048,
    "segments": 256,
    "findings": 1024,
    "conversation_events": 20000,
    "trace_lines": 20000,
})


class SourceStatus(StrEnum):
    #: Read, whole, at least one matching record.
    AVAILABLE = "available"
    #: Read, whole, nothing matched the selector.
    EMPTY = "empty"
    #: Read, but a bound stopped it: evidence may be missing.
    TRUNCATED = "truncated"
    #: The source does not exist (no file, no path given for a default source).
    MISSING = "missing"
    #: The source exists but could not be read (I/O error, schema absent).
    UNAVAILABLE = "unavailable"
    #: The caller did not ask for this source.
    NOT_REQUESTED = "not_requested"


READ_STATUSES = frozenset({SourceStatus.AVAILABLE, SourceStatus.EMPTY, SourceStatus.TRUNCATED})


class TurnActor(StrEnum):
    USER = "user"
    MOUTH = "mouth"
    BRAIN = "brain"


class TurnKind(StrEnum):
    USER_TURN = "user_turn"
    TURN_ACCEPTED = "turn_accepted"
    TURN_FAILED = "turn_failed"
    MESSAGE_PUBLISHED = "message_published"
    SPEECH = "speech"
    REFLEX = "reflex"


class SpeechOutcome(StrEnum):
    #: Brain request seen, no voice-side record while voice-side evidence was read.
    DROPPED = "dropped"
    #: Brain request only and no voice-side source was read: undecidable.
    UNKNOWN = "unknown"
    #: Delivered as paragraph chunks with their own speech ids (`chunk_speech_ids`).
    CHUNKED = "chunked"
    QUEUED = "queued"
    STARTED = "started"
    SPOKEN = "spoken"
    INTERRUPTED = "interrupted"
    SUPERSEDED = "superseded"
    #: Retired as out of date (`mouth.speech.expired` / `voice.speech.expired`: TTL, voice background).
    STALE = "stale"
    FAILED = "failed"


TERMINAL_OUTCOMES = (SpeechOutcome.SPOKEN, SpeechOutcome.INTERRUPTED, SpeechOutcome.SUPERSEDED, SpeechOutcome.STALE,
                     SpeechOutcome.FAILED)


class BargeInOutcome(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    IGNORED = "ignored"
    DEGRADED = "degraded"
    ADVISORY = "advisory"
    #: A pending local candidate with no confirmation or rejection in the evidence.
    UNRESOLVED = "unresolved"


class ProviderEvent(StrEnum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    KEEPALIVE_FAILED = "keepalive_failed"
    REFUSED = "refused"
    FAILURE = "failure"
    RESPONSE_SILENT = "response_silent"
    CANCEL_REQUESTED = "cancel_requested"
    MODELS_FAILED = "models_failed"


class UserActivity(StrEnum):
    #: Server VAD detected the START of user speech (`voice.speech_started`, logged when no Jarvis output
    #: is live; a speech start that itself triggers a barge-in is not logged separately).
    SPEECH_STARTED = "speech_started"
    #: Server VAD (or manual key) committed the user's input at the end of the utterance (`voice.input_submitted`).
    INPUT_SUBMITTED = "input_submitted"
    #: The provider transcribed a user utterance (`voice.transcript`, timing and addressing only).
    TRANSCRIPT = "transcript"
    #: The voice runtime submitted a user turn to the brain (`voice.brain_turn_submitted`, timing only).
    TURN_SUBMITTED = "turn_submitted"
    TURN_COMPLETED = "turn_completed"
    TRANSCRIPT_DROPPED = "transcript_dropped"
    MANUAL_SUBMIT = "manual_submit"


#: The start of a user utterance.
USER_ONSET_ACTIVITIES = (UserActivity.SPEECH_STARTED,)
#: Facts that close a user utterance (commit, transcription, submission).
USER_CLOSING_ACTIVITIES = (UserActivity.INPUT_SUBMITTED, UserActivity.TRANSCRIPT, UserActivity.TURN_SUBMITTED)
#: A closing fact with no onset after an episode proves an utterance already in progress at the episode
#: only when it comes within this bound (a longer silence is not the same utterance).
MAX_UTTERANCE_MS = 60_000
#: An id-only selection longer than this gets the `long_selection` coverage warning.
MAX_SELECTION_HOURS = 6


class LifecycleEvent(StrEnum):
    STARTED = "started"
    STOPPED = "stopped"
    OUTPUT_STOPPED = "output_stopped"
    DEVICE_CLOSED = "device_closed"
    NATIVE_FAILED = "native_failed"
    STREAM_CLOSED = "stream_closed"
    TIMEOUT = "timeout"


class BrainEvent(StrEnum):
    REPLIES_SUPERSEDED = "replies_superseded"
    TURN_SLOW = "turn_slow"
    TURN_OVER_BUDGET = "turn_over_budget"
    WORK_COMPLETED = "work_completed"


class CoverageWarning(StrEnum):
    #: An id-only selector (no window) spans more than one voice session segment.
    MULTI_SESSION_SELECTION = "multi_session_selection"
    #: An id-only selector spans more than `MAX_SELECTION_HOURS`.
    LONG_SELECTION = "long_selection"
    #: The requested window ends after the journal end or after the capture: a recapture may differ.
    OPEN_WINDOW = "open_window"
    #: The journal ends with a line that has no newline yet (not decoded).
    TORN_TAIL = "torn_tail"


#: Ordered latency stages of one speech (docs/testlab.md, "Latency joins").
LATENCY_STAGES = ("user_turn_end", "brain_turn_accepted", "speech_requested", "speech_queued", "speech_queue_free",
                  "speech_dispatched", "speech_started", "provider_first_pcm", "first_audio", "speech_ended")
#: Joined measures: (name, from stage, to stage). A measure exists when both stages exist.
LATENCY_MEASURES = (
    ("user_turn_end_to_brain_turn_accepted_ms", "user_turn_end", "brain_turn_accepted"),
    ("brain_turn_accepted_to_speech_requested_ms", "brain_turn_accepted", "speech_requested"),
    ("speech_requested_to_queued_ms", "speech_requested", "speech_queued"),
    ("speech_queued_to_started_ms", "speech_queued", "speech_started"),
    #: Queue wait without serial playback: from max(queued, end of the previous live output) to start.
    ("speech_queue_free_to_started_ms", "speech_queue_free", "speech_started"),
    ("speech_started_to_first_audio_ms", "speech_started", "first_audio"),
    ("user_turn_end_to_first_audio_ms", "user_turn_end", "first_audio"),
    ("first_audio_to_speech_ended_ms", "first_audio", "speech_ended"),
)

_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_KIND = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_DOTTED = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_SUMMARY_PATH = re.compile(r"[a-z0-9_./-]{1,160}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REF = re.compile(r"cev-[0-9a-f]{64}|trace:(?:0|[1-9][0-9]{0,14})|report:[0-9a-f]{16}")


def trace_ref(offset: int) -> str:
    """Evidence reference of the `RuntimeJournal` line starting at byte `offset`."""
    return f"trace:{offset}"


def report_ref(sha256: str) -> str:
    """Evidence reference of a voice session metrics report (first 16 hex of its sha256)."""
    return f"report:{sha256[:16]}"


# ------------------------------------------------------------ value rules

Rule = Callable[[object, str], None]


def is_code_token(value: object) -> bool:
    return isinstance(value, str) and _CODE.fullmatch(value) is not None


def is_opaque_id(value: object) -> bool:
    try:
        state_id(value, "id")
        value.encode("utf-8")  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return False
    return True


def _id(value: object, path: str) -> None:
    if not is_opaque_id(value):
        raise fail(f"{path} must be a nonempty bounded opaque identifier")


def _code(value: object, path: str) -> None:
    if not is_code_token(value):
        raise fail(f"{path} must be a lowercase code token of at most 64 characters")


def _kind(value: object, path: str) -> None:
    if not isinstance(value, str) or not _KIND.fullmatch(value):
        raise fail(f"{path} must be a dotted lowercase journal kind")


def _time(value: object, path: str) -> None:
    parse_time(value, path)


def _bool(value: object, path: str) -> None:
    if type(value) is not bool:
        raise fail(f"{path} must be a boolean")


def _integer(minimum: int, maximum: int) -> Rule:
    def rule(value: object, path: str) -> None:
        if type(value) is not int or not minimum <= value <= maximum:
            raise fail(f"{path} must be an integer from {minimum} to {maximum}")
    return rule


def _number(minimum: float = -MAX_JSON_INT) -> Rule:
    def rule(value: object, path: str) -> None:
        if type(value) not in (int, float) or value != value or not minimum <= value <= MAX_JSON_INT:
            raise fail(f"{path} must be a finite number >= {minimum}")
    return rule


def _pattern(pattern: re.Pattern[str], shape: str) -> Rule:
    def rule(value: object, path: str) -> None:
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise fail(f"{path} must be {shape}")
    return rule


def _text(max_chars: int) -> Rule:
    def rule(value: object, path: str) -> None:
        if not isinstance(value, str) or not value or len(value) > max_chars:
            raise fail(f"{path} must be nonempty text of at most {max_chars} characters")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise fail(f"{path} must be valid Unicode text (lone surrogate)") from None
    return rule


def _enum(vocabulary: type[StrEnum] | Sequence[str]) -> Rule:
    allowed = frozenset(item.value if isinstance(item, StrEnum) else item for item in vocabulary)

    def rule(value: object, path: str) -> None:
        if not isinstance(value, str) or value not in allowed:
            raise fail(f"{path} is not in the vocabulary")
    return rule


def _nullable(inner: Rule) -> Rule:
    def rule(value: object, path: str) -> None:
        if value is not None:
            inner(value, path)
    return rule


def _scalar(value: object, path: str) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) in (int, float):
        _number()(value, path)
        return
    _text(128)(value, path)


def _list(item: Rule, max_items: int, *, min_items: int = 0, unique: bool = False) -> Rule:
    def rule(value: object, path: str) -> None:
        if not isinstance(value, (list, tuple)):
            raise fail(f"{path} must be a list")
        if len(value) > max_items:
            raise fail(f"{path} exceeds {max_items} items", LIMIT_EXCEEDED)
        if len(value) < min_items:
            raise fail(f"{path} needs at least {min_items} item(s)", REFERENCE_INVALID)
        for index, element in enumerate(value):
            item(element, f"{path}[{index}]")
        if unique and len(set(value)) != len(value):
            raise fail(f"{path} must not repeat a value")
    return rule


def _object(fields: Mapping[str, Rule]) -> Rule:
    expected = frozenset(fields)

    def rule(value: object, path: str) -> None:
        data = exact_fields(value, expected, path)
        for name, check in fields.items():
            check(data[name], f"{path}.{name}")
    return rule


_OPT_ID = _nullable(_id)
_OPT_CODE = _nullable(_code)
_OPT_TIME = _nullable(_time)
_NONNEG = _integer(0, MAX_JSON_INT)
_SIGNED = _integer(-MAX_JSON_INT, MAX_JSON_INT)
_EVIDENCE = _list(_pattern(_REF, "an evidence reference"), MAX_EVIDENCE_REFS, min_items=1, unique=True)
_STATUS = _enum(SourceStatus)
_IDS = _list(_id, MAX_IDS, unique=True)
_CODES = _list(_code, 16, unique=True)
_HEX = _pattern(_HEX64, "64 lowercase hex characters")

_SELECTOR = _object({"conversation_id": _OPT_ID, "session_id": _OPT_ID, "start": _OPT_TIME, "end": _OPT_TIME})
_CAPTURE = _object({
    "captured_at": _time,
    "code": _object({"status": _enum(("capture_time", "unknown")),
                     "git_revision": _nullable(_pattern(_REVISION, "40 or 64 lowercase hex characters")),
                     "dirty": _nullable(_bool)}),
    "config": _object({"status": _enum(("capture_time", "unknown")), "fingerprint": _nullable(_HEX)}),
})
_SESSION = _object({"selector": _SELECTOR, "conversation_ids": _IDS, "session_ids": _IDS, "started_at": _OPT_TIME,
                    "ended_at": _OPT_TIME, "duration_ms": _nullable(_NONNEG)})
_IDENTITY = _object({"status": _enum(("evidence", "unknown")), "voice_configuration_ids": _list(_HEX, 16, unique=True),
                     "architectures": _CODES, "evidence": _list(_pattern(_REF, "an evidence reference"),
                                                                MAX_EVIDENCE_REFS, unique=True)})
_COVERAGE = _object({
    "conversation_events": _object({"status": _STATUS, "origin": _nullable(_enum(("store", "export"))),
                                    "events": _NONNEG, "skipped_rows": _NONNEG, "export_complete": _nullable(_bool),
                                    "truncated": _bool, "reason": _OPT_CODE}),
    "runtime_journal": _object({"status": _STATUS, "lines_in_window": _NONNEG, "lines_selected": _NONNEG,
                                "corrupt_lines": _NONNEG, "oversized_lines": _NONNEG, "untimed_lines": _NONNEG,
                                "truncated": _bool, "start_truncated": _bool, "torn_tail": _bool,
                                "window_open": _bool, "stopped_by": _OPT_CODE, "reason": _OPT_CODE}),
    "voice_session_reports": _object({"status": _STATUS, "reports": _NONNEG, "reason": _OPT_CODE}),
    "content": _object({"included": _bool, "max_chars": _integer(0, MAX_CONTENT_CHARS), "items": _NONNEG,
                        "truncated_items": _NONNEG, "redactions": _NONNEG}),
    "limits": _list(_object({"section": _code, "kept": _NONNEG, "dropped": _NONNEG}), 16),
    "segments": _object({
        "count": _NONNEG, "idle_gap_ms": _NONNEG, "dropped": _NONNEG,
        "items": _list(_object({"index": _NONNEG, "session_id": _OPT_ID, "started_at": _time, "ended_at": _time,
                                "end_kind": _nullable(_kind), "items": _NONNEG}), SECTION_LIMITS["segments"]),
    }),
    "warnings": _list(_enum(CoverageWarning), len(CoverageWarning), unique=True),
})
_TURN = _object({
    "item_id": _text(600), "actor": _enum(TurnActor), "kind": _enum(TurnKind), "at": _time, "status": _OPT_CODE,
    "conversation_id": _OPT_ID, "session_id": _OPT_ID, "turn_id": _OPT_ID, "correlation_id": _OPT_ID,
    "speech_id": _OPT_ID, "outcome_id": _OPT_ID, "content": _nullable(_text(MAX_CONTENT_CHARS)),
    "content_truncated": _bool, "evidence": _EVIDENCE,
})
_TERMINAL = _object({"outcome": _enum([item.value for item in TERMINAL_OUTCOMES]), "at": _time, "reason": _OPT_CODE,
                     "evidence": _EVIDENCE})
_SPEECH = _object({
    "speech_id": _id, "conversation_id": _OPT_ID, "correlation_id": _OPT_ID, "work_id": _OPT_ID,
    "parent_speech_id": _OPT_ID, "chunk_speech_ids": _IDS, "output_ids": _list(_id, 16, unique=True),
    "kind": _OPT_CODE, "priority": _OPT_CODE, "outcome": _enum(SpeechOutcome), "reason": _OPT_CODE,
    "played_ms": _nullable(_number(0)), "queue_wait_ms": _nullable(_number(0)), "requested_at": _OPT_TIME,
    "queued_at": _OPT_TIME, "dispatched_at": _OPT_TIME, "started_at": _OPT_TIME, "ended_at": _OPT_TIME,
    "codes": _CODES, "terminals": _list(_TERMINAL, len(TERMINAL_OUTCOMES)), "spoken_divergences": _NONNEG,
    "state_divergences": _NONNEG, "spoken_diverged_at": _OPT_TIME, "evidence": _EVIDENCE,
})
_PLAYBACK = _object({
    "output_id": _id, "speech_id": _OPT_ID, "conversation_id": _OPT_ID, "source": _OPT_CODE, "started_at": _time,
    "provider_chunk_at": _OPT_TIME, "first_write_at": _OPT_TIME, "ended_at": _OPT_TIME, "end_status": _OPT_CODE,
    "drain_ms": _nullable(_number(0)), "evidence": _EVIDENCE,
})
_EPISODE = _object({
    "episode_id": _text(64), "started_at": _time, "ended_at": _time, "outcome": _enum(BargeInOutcome),
    "authority": _OPT_CODE, "trigger": _OPT_CODE, "speech_id": _OPT_ID, "output_id": _OPT_ID,
    "played_ms": _nullable(_number(0)), "stop_latency_ms": _nullable(_number(0)), "device_stopped": _nullable(_bool),
    "codes": _CODES, "jarvis_speaking": _nullable(_bool), "audible": _nullable(_bool),
    "next_user_activity_ms": _nullable(_NONNEG),
    "next_user_activity_basis": _nullable(_enum(("onset", "ongoing_onset", "closed_without_onset", "closing"))),
    "evidence": _EVIDENCE,
})
_PROVIDER = _object({"at": _time, "event": _enum(ProviderEvent), "code": _OPT_CODE, "status": _OPT_CODE,
                     "provider": _OPT_CODE, "conversation_id": _OPT_ID, "evidence": _EVIDENCE})
_USER_ACTIVITY = _object({"at": _time, "event": _enum(UserActivity), "conversation_id": _OPT_ID, "code": _OPT_CODE,
                          "near_playback": _nullable(_bool), "evidence": _EVIDENCE})
_LIFECYCLE = _object({"at": _time, "event": _enum(LifecycleEvent), "code": _OPT_CODE, "conversation_id": _OPT_ID,
                      "session_id": _OPT_ID, "evidence": _EVIDENCE})
_BRAIN = _object({"at": _time, "event": _enum(BrainEvent), "conversation_id": _OPT_ID, "correlation_id": _OPT_ID,
                  "work_ids": _list(_id, 16, unique=True), "measure": _OPT_CODE, "ms": _nullable(_number(0)),
                  "budget_ms": _nullable(_number(0)), "evidence": _EVIDENCE})
_USAGE = _object({"at": _time, "conversation_id": _OPT_ID, "session_id": _OPT_ID,
                  "input_tokens": _nullable(_NONNEG), "output_tokens": _nullable(_NONNEG),
                  "duration_seconds": _nullable(_number(0)), "source": _OPT_CODE, "evidence": _EVIDENCE})
_STAGE_RULE = _enum(LATENCY_STAGES)
_LATENCY = _object({
    "join_id": _text(300), "speech_id": _OPT_ID, "correlation_id": _OPT_ID,
    "stages": _list(_object({"stage": _STAGE_RULE, "at": _time, "evidence": _EVIDENCE}), len(LATENCY_STAGES)),
    "measures": _list(_object({"name": _enum([item[0] for item in LATENCY_MEASURES]), "ms": _SIGNED,
                               "from_stage": _STAGE_RULE, "to_stage": _STAGE_RULE}), len(LATENCY_MEASURES)),
    "reported": _list(_object({"measure": _code, "ms": _number(), "evidence": _EVIDENCE}), 32),
})
_REPORT = _object({
    "session_id": _id, "architecture": _OPT_CODE, "configuration_id": _nullable(_HEX),
    "session_fingerprint": _nullable(_HEX), "terminal_status": _OPT_CODE, "trace_evidence_complete": _nullable(_bool),
    "latency": _list(_object({"name": _code, "count": _NONNEG, "min_ms": _nullable(_number()),
                              "max_ms": _nullable(_number()), "mean_ms": _nullable(_number())}), 32),
    "counts": _list(_object({"name": _code, "value": _NONNEG}), 32),
    "evidence": _EVIDENCE,
})
_AGGREGATES = _object({
    "trace_summary": _nullable(_list(_object({"path": _pattern(_SUMMARY_PATH, "a summary path"), "value": _scalar}),
                                     512)),
    "voice_session_reports": _list(_REPORT, 16),
})
_ANOMALIES = _object({
    "rules": _list(_object({"rule_id": _pattern(_DOTTED, "a dotted rule id"), "version": _integer(1, 2**31 - 1),
                            "evaluated": _bool, "skipped_reason": _OPT_CODE,
                            "thresholds": _list(_object({"name": _code, "value": _number()}), 16)}), 64),
    "findings": _list(_object({
        "rule_id": _pattern(_DOTTED, "a dotted rule id"), "rule_version": _integer(1, 2**31 - 1), "at": _time,
        "subject_kind": _code, "subject_id": _text(600),
        "measured": _list(_object({"name": _code, "value": _scalar}), 16), "evidence": _EVIDENCE,
    }), SECTION_LIMITS["findings"]),
})
_REFERENCES = _object({
    "conversation_events": _list(_object({"ref": _pattern(re.compile(r"cev-[0-9a-f]{64}"), "an event id"),
                                          "sequence": _NONNEG, "event_type": _enum(ConversationEventType),
                                          "occurred_at": _time, "visibility": _enum(ConversationVisibility)}),
                                 SECTION_LIMITS["conversation_events"]),
    "trace_lines": _list(_object({"ref": _pattern(re.compile(r"trace:[0-9]{1,15}"), "a trace reference"),
                                  "offset": _NONNEG, "ts": _time, "kind": _kind, "level": _OPT_CODE}),
                         SECTION_LIMITS["trace_lines"]),
    "voice_session_reports": _list(_object({"ref": _pattern(re.compile(r"report:[0-9a-f]{16}"), "a report reference"),
                                            "sha256": _HEX}), 16),
})

_DOCUMENT_RULES: Mapping[str, Rule] = MappingProxyType({
    "capture": _CAPTURE,
    "session": _SESSION,
    "identity": _IDENTITY,
    "coverage": _COVERAGE,
    "turns": _list(_TURN, SECTION_LIMITS["turns"]),
    "speech": _list(_SPEECH, SECTION_LIMITS["speech"]),
    "playback": _list(_PLAYBACK, SECTION_LIMITS["playback"]),
    "barge_in": _list(_EPISODE, SECTION_LIMITS["barge_in"]),
    "provider": _list(_PROVIDER, SECTION_LIMITS["provider"]),
    "user_activity": _list(_USER_ACTIVITY, SECTION_LIMITS["user_activity"]),
    "lifecycle": _list(_LIFECYCLE, SECTION_LIMITS["lifecycle"]),
    "brain": _list(_BRAIN, SECTION_LIMITS["brain"]),
    "usage": _list(_USAGE, SECTION_LIMITS["usage"]),
    "latency": _list(_LATENCY, SECTION_LIMITS["latency"]),
    "aggregates": _AGGREGATES,
    "anomalies": _ANOMALIES,
    "references": _REFERENCES,
})
BUNDLE_FIELDS = frozenset({"schema", "schema_version", "bundle_id", "content_fingerprint", *_DOCUMENT_RULES})
#: Fields outside the content fingerprint: the id and fingerprint themselves, and the capture context.
UNFINGERPRINTED_FIELDS = frozenset({"bundle_id", "content_fingerprint", "capture"})


# ------------------------------------------------------------- identity

def bundle_content_fingerprint(document: Mapping[str, Any]) -> str:
    """Fingerprint of the evidence content: the document without `bundle_id`, `content_fingerprint`, `capture`."""
    return content_fingerprint({key: value for key, value in document.items() if key not in UNFINGERPRINTED_FIELDS})


def bundle_id_time(document: Mapping[str, Any]) -> datetime:
    """The id time: session start, else selector start, else capture time (an empty bundle)."""
    session = document["session"]
    for value in (session["started_at"], session["selector"]["start"], document["capture"]["captured_at"]):
        if value is not None:
            return parse_time(value, "bundle id time")  # type: ignore[return-value]
    raise fail("bundle id time is undeterminable")


def derive_bundle_id(document: Mapping[str, Any], fingerprint: str) -> str:
    return format_bundle_id(bundle_id_time(document), fingerprint[:16])


# ---------------------------------------------------------------- checks

def _collect_evidence(document: Mapping[str, Any]) -> list[tuple[str, Sequence[str]]]:
    lists: list[tuple[str, Sequence[str]]] = [("identity", document["identity"]["evidence"])]
    for name in ("turns", "speech", "playback", "barge_in", "provider", "user_activity", "lifecycle", "brain", "usage"):
        for index, item in enumerate(document[name]):
            lists.append((f"{name}[{index}]", item["evidence"]))
    for index, item in enumerate(document["speech"]):
        lists.extend((f"speech[{index}].terminals", terminal["evidence"]) for terminal in item["terminals"])
    for index, item in enumerate(document["latency"]):
        lists.extend((f"latency[{index}].stages", stage["evidence"]) for stage in item["stages"])
        lists.extend((f"latency[{index}].reported", entry["evidence"]) for entry in item["reported"])
    lists.extend((f"aggregates.voice_session_reports[{index}]", report["evidence"])
                 for index, report in enumerate(document["aggregates"]["voice_session_reports"]))
    lists.extend((f"anomalies.findings[{index}]", finding["evidence"])
                 for index, finding in enumerate(document["anomalies"]["findings"]))
    return lists


def _check_references(document: Mapping[str, Any]) -> None:
    references = document["references"]
    declared: set[str] = set()
    for item in references["conversation_events"]:
        declared.add(item["ref"])
    for item in references["trace_lines"]:
        if item["ref"] != trace_ref(item["offset"]):
            raise fail("references.trace_lines: ref must be trace:<offset>", REFERENCE_INVALID)
        declared.add(item["ref"])
    for item in references["voice_session_reports"]:
        if item["ref"] != report_ref(item["sha256"]):
            raise fail("references.voice_session_reports: ref must be report:<sha256 prefix>", REFERENCE_INVALID)
        declared.add(item["ref"])
    total = (len(references["conversation_events"]) + len(references["trace_lines"])
             + len(references["voice_session_reports"]))
    if len(declared) != total:
        raise fail("references must not repeat a ref", REFERENCE_INVALID)
    for where, refs in _collect_evidence(document):
        if any(ref not in declared for ref in refs):
            raise fail(f"{where}.evidence names a reference absent from references", REFERENCE_INVALID)
    for index, item in enumerate(document["latency"]):
        stages = {stage["stage"] for stage in item["stages"]}
        if len(stages) != len(item["stages"]):
            raise fail(f"latency[{index}].stages must not repeat a stage", REFERENCE_INVALID)
        if not item["stages"] and not item["reported"]:
            raise fail(f"latency[{index}] needs a stage or a reported measure", REFERENCE_INVALID)
        if any(measure["from_stage"] not in stages or measure["to_stage"] not in stages for measure in item["measures"]):
            raise fail(f"latency[{index}].measures names a stage the join does not hold", REFERENCE_INVALID)


_READ = frozenset({SourceStatus.AVAILABLE.value, SourceStatus.EMPTY.value, SourceStatus.TRUNCATED.value})


def _check_sources(document: Mapping[str, Any]) -> None:
    """A reference can only come from a source that was read, and every read event is referenced."""
    coverage, references = document["coverage"], document["references"]
    for section, source in (("conversation_events", "conversation_events"), ("trace_lines", "runtime_journal"),
                            ("voice_session_reports", "voice_session_reports")):
        if references[section] and coverage[source]["status"] not in _READ:
            raise fail(f"references.{section} names evidence of a source that was not read", REFERENCE_INVALID)
    if coverage["conversation_events"]["events"] != len(references["conversation_events"]):
        raise fail("coverage.conversation_events.events must count the referenced events", REFERENCE_INVALID)
    segments = coverage["segments"]
    if segments["count"] != len(segments["items"]) + segments["dropped"]:
        raise fail("coverage.segments.count must equal listed plus dropped segments", REFERENCE_INVALID)


def _first_terminal(terminals: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    order = {outcome.value: index for index, outcome in enumerate(TERMINAL_OUTCOMES)}
    return min(terminals, key=lambda item: (item["at"], order[item["outcome"]])) if terminals else None


def _check_speech(document: Mapping[str, Any]) -> None:
    """A speech outcome must be what its own terminals and stages say."""
    terminal_values = {outcome.value for outcome in TERMINAL_OUTCOMES}
    for index, speech in enumerate(document["speech"]):
        where, outcome, terminals = f"speech[{index}]", speech["outcome"], speech["terminals"]
        if len({item["outcome"] for item in terminals}) != len(terminals):
            raise fail(f"{where}.terminals must not repeat an outcome", REFERENCE_INVALID)
        first = _first_terminal(terminals)
        if outcome in terminal_values:
            consistent = first is not None and first["outcome"] == outcome and speech["ended_at"] == first["at"]
        else:
            consistent = first is None and speech["ended_at"] is None and {
                SpeechOutcome.CHUNKED.value: bool(speech["chunk_speech_ids"]),
                SpeechOutcome.STARTED.value: speech["started_at"] is not None and not speech["chunk_speech_ids"],
                SpeechOutcome.QUEUED.value: (speech["started_at"] is None and not speech["chunk_speech_ids"]
                                             and (speech["queued_at"] or speech["dispatched_at"]) is not None),
            }.get(outcome, speech["requested_at"] is not None and speech["chunk_speech_ids"] == []
                  and speech["started_at"] is None and speech["queued_at"] is None
                  and speech["dispatched_at"] is None)
        if not consistent:
            raise fail(f"{where}.outcome contradicts its terminals or stages", REFERENCE_INVALID)
        if (speech["spoken_divergences"] > 0) != (speech["spoken_diverged_at"] is not None):
            raise fail(f"{where}.spoken_diverged_at is set exactly when spoken_divergences > 0", REFERENCE_INVALID)


def _check_rules(document: Mapping[str, Any]) -> None:
    """Rule rows are unique and self-consistent; every finding belongs to an evaluated row with its version."""
    rows: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(document["anomalies"]["rules"]):
        if row["rule_id"] in rows:
            raise fail(f"anomalies.rules[{index}] repeats a rule_id", REFERENCE_INVALID)
        if (row["skipped_reason"] is None) != row["evaluated"]:
            raise fail(f"anomalies.rules[{index}].skipped_reason is set exactly when not evaluated", REFERENCE_INVALID)
        if len({item["name"] for item in row["thresholds"]}) != len(row["thresholds"]):
            raise fail(f"anomalies.rules[{index}].thresholds must not repeat a name", REFERENCE_INVALID)
        rows[row["rule_id"]] = row
    for index, finding in enumerate(document["anomalies"]["findings"]):
        where, row = f"anomalies.findings[{index}]", rows.get(finding["rule_id"])
        if row is None or not row["evaluated"] or row["version"] != finding["rule_version"]:
            raise fail(f"{where} must belong to an evaluated rule row of the same version", REFERENCE_INVALID)
        measured = {item["name"]: item["value"] for item in finding["measured"]}
        if "threshold_ms" in measured:
            thresholds = {item["name"]: item["value"] for item in row["thresholds"]}
            if thresholds.get(measured.get("measure")) != measured["threshold_ms"]:
                raise fail(f"{where}.measured.threshold_ms differs from its rule threshold", REFERENCE_INVALID)


def _in_order(items: Sequence[Any], key: Callable[[Any], Any], where: str) -> None:
    keys = [key(item) for item in items]
    if any(left > right for left, right in zip(keys, keys[1:])):
        raise fail(f"{where} is not in its documented order", REFERENCE_INVALID)


def _speech_first_time(speech: Mapping[str, Any]) -> str:
    moments = [speech[name] for name in ("requested_at", "queued_at", "dispatched_at", "started_at")
               if speech[name] is not None]
    return min(moments + [terminal["at"] for terminal in speech["terminals"]])


def _check_order(document: Mapping[str, Any]) -> None:
    """Every list is in the order the builder documents (so an edit cannot reorder evidence silently)."""
    _in_order(document["turns"], lambda item: (item["at"], item["item_id"]), "turns")
    _in_order(document["speech"], lambda item: (_speech_first_time(item), item["speech_id"]), "speech")
    _in_order(document["playback"], lambda item: (item["started_at"], item["output_id"]), "playback")
    _in_order(document["barge_in"], lambda item: (item["started_at"], item["episode_id"]), "barge_in")
    for name in ("provider", "user_activity", "lifecycle", "brain", "usage"):
        _in_order(document[name], lambda item: (item["at"], item["evidence"]), name)
    _in_order(document["latency"], lambda item: ((item["stages"][0]["at"] if item["stages"] else ""), item["join_id"]),
              "latency")
    _in_order(document["anomalies"]["findings"], lambda item: (item["at"], item["rule_id"], item["subject_id"]),
              "anomalies.findings")
    references = document["references"]
    _in_order(references["conversation_events"], lambda item: (item["sequence"], item["ref"]),
              "references.conversation_events")
    _in_order(references["trace_lines"], lambda item: item["offset"], "references.trace_lines")
    measures = {name: (source, target) for name, source, target in LATENCY_MEASURES}
    for index, join in enumerate(document["latency"]):
        where = f"latency[{index}]"
        _in_order(join["stages"], lambda stage: LATENCY_STAGES.index(stage["stage"]), f"{where}.stages")
        at = {stage["stage"]: parse_time(stage["at"], "stage") for stage in join["stages"]}
        for measure in join["measures"]:
            if (measures[measure["name"]] != (measure["from_stage"], measure["to_stage"])
                    or measure["ms"] != int((at[measure["to_stage"]] - at[measure["from_stage"]])
                                            / timedelta(milliseconds=1))):
                raise fail(f"{where}.measures disagrees with its stages", REFERENCE_INVALID)


def _check_segments(document: Mapping[str, Any]) -> None:
    """Segments are ordered, non-overlapping, indexed from 0, non-empty; warnings follow coverage."""
    coverage, session = document["coverage"], document["session"]
    items = coverage["segments"]["items"]
    for index, item in enumerate(items):
        where = f"coverage.segments.items[{index}]"
        if item["index"] != index or item["items"] < 1 or item["started_at"] > item["ended_at"]:
            raise fail(f"{where} must have index {index}, at least one item and start <= end", REFERENCE_INVALID)
        if index and items[index - 1]["ended_at"] > item["started_at"]:
            raise fail(f"{where} overlaps or precedes the previous segment", REFERENCE_INVALID)
    selector = session["selector"]
    id_only = selector["start"] is None and selector["end"] is None
    long = (session["started_at"] is not None and session["ended_at"] is not None
            and parse_time(session["ended_at"], "t") - parse_time(session["started_at"], "t")  # type: ignore[operator]
            > timedelta(hours=MAX_SELECTION_HOURS))
    expected = {
        CoverageWarning.MULTI_SESSION_SELECTION.value: id_only and coverage["segments"]["count"] > 1,
        CoverageWarning.LONG_SELECTION.value: id_only and long,
        CoverageWarning.OPEN_WINDOW.value: coverage["runtime_journal"]["window_open"],
        CoverageWarning.TORN_TAIL.value: coverage["runtime_journal"]["torn_tail"],
    }
    if set(coverage["warnings"]) != {name for name, present in expected.items() if present}:
        raise fail("coverage.warnings disagree with the coverage they summarize", REFERENCE_INVALID)


def _segment_at(document: Mapping[str, Any], at: str) -> Mapping[str, Any] | None:
    candidates = [item for item in document["coverage"]["segments"]["items"] if item["started_at"] <= at]
    return candidates[-1] if candidates else None


def _check_subjects(document: Mapping[str, Any]) -> None:
    """A finding's subject exists in its section and still shows the signature the rule reported."""
    rows = {row["rule_id"]: row for row in document["anomalies"]["rules"]}
    speech = {item["speech_id"]: item for item in document["speech"]}
    episodes = {item["episode_id"]: item for item in document["barge_in"]}
    joins = {item["join_id"]: item for item in document["latency"]}
    events = {item["ref"] for item in document["references"]["conversation_events"]}
    retired = {SpeechOutcome.SUPERSEDED.value, SpeechOutcome.STALE.value}
    for index, finding in enumerate(document["anomalies"]["findings"]):
        where, rule_id, subject = f"anomalies.findings[{index}]", finding["rule_id"], finding["subject_id"]
        measured = {item["name"]: item["value"] for item in finding["measured"]}
        thresholds = {item["name"]: item["value"] for item in rows[rule_id]["thresholds"]}
        if rule_id == "voice.self_barge_in":
            episode = episodes.get(subject)
            window = thresholds.get("user_activity_window_ms")
            consistent = (episode is not None and episode["outcome"] == BargeInOutcome.CONFIRMED.value
                          and episode["jarvis_speaking"] is True and episode["audible"] is True
                          and measured.get("next_user_activity_ms") == episode["next_user_activity_ms"]
                          and (episode["next_user_activity_ms"] is None
                               or (window is not None and episode["next_user_activity_ms"] > window)))
        elif rule_id == "speech.missing_delivery_outcome":
            item, segment = speech.get(subject), _segment_at(document, finding["at"])
            consistent = (item is not None and item["outcome"] in {SpeechOutcome.QUEUED.value, SpeechOutcome.STARTED.value,
                                                                   SpeechOutcome.DROPPED.value}
                          and not item["terminals"] and measured.get("state") == item["outcome"]
                          and (segment is None or segment["end_kind"] == measured.get("segment_end")))
        elif rule_id == "speech.delivered_after_supersession":
            item = speech.get(subject)
            consistent = item is not None and any(terminal["outcome"] in retired for terminal in item["terminals"])
        elif rule_id == "speech.duplicate_payload":
            item = speech.get(subject)
            consistent = item is not None and item["started_at"] is not None
        elif rule_id == "latency.above_threshold":
            join_id, _, name = subject.partition("#")
            join = joins.get(join_id)
            found = [measure for measure in (join["measures"] if join else ()) if measure["name"] == name]
            consistent = (bool(found) and measured.get("measure") == name and measured.get("ms") == found[0]["ms"]
                          and thresholds.get(name) is not None and found[0]["ms"] > thresholds[name])
        elif rule_id == "events.reconstruction_anomaly":
            consistent = subject in events  # the item id is its first event; evidence names the anomalous one
        else:
            consistent = True  # a registered custom rule: rows and versions are still checked
        if not consistent:
            raise fail(f"{where} names a subject that does not show its rule's signature", REFERENCE_INVALID)


def check_bundle_document(payload: object) -> Mapping[str, Any]:
    """Strict validation of a decoded bundle document (redaction scan first). Returns the mapping."""
    scan_private(payload, "bundle")
    data = exact_fields(payload, BUNDLE_FIELDS, "bundle")
    check_document_header(data, DIAGNOSTIC_BUNDLE_SCHEMA, BUNDLE_SCHEMA_VERSION, "bundle")
    check_bundle_id(data["bundle_id"])
    for name, rule in _DOCUMENT_RULES.items():
        rule(data[name], name)
    _pattern(_HEX64, "64 lowercase hex characters")(data["content_fingerprint"], "content_fingerprint")
    _check_references(data)
    _check_sources(data)
    _check_speech(data)
    _check_rules(data)
    _check_segments(data)
    _check_order(data)
    _check_subjects(data)
    if bundle_content_fingerprint(data) != data["content_fingerprint"]:
        raise fail("content_fingerprint differs from the bundle content", REFERENCE_INVALID)
    if data["bundle_id"] != derive_bundle_id(data, data["content_fingerprint"]):
        raise fail("bundle_id must be derived from the id time and the content fingerprint", REFERENCE_INVALID)
    return data


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


# -------------------------------------------------------------- document

@dataclass(frozen=True, slots=True)
class DiagnosticBundle:
    """A validated, read-only bundle document. Construct with `from_dict` or `decode`."""

    document: Mapping[str, Any]

    def __post_init__(self) -> None:
        plain = _thaw(self.document)
        check_bundle_document(plain)
        encoded = canonical_json(plain).encode("utf-8")
        if len(encoded) > MAX_BUNDLE_BYTES:
            raise fail(f"bundle exceeds {MAX_BUNDLE_BYTES} encoded bytes", LIMIT_EXCEEDED)
        object.__setattr__(self, "document", _freeze(plain))

    def __hash__(self) -> int:
        return hash(self.bundle_id)

    @property
    def bundle_id(self) -> str:
        return self.document["bundle_id"]

    @property
    def content_fingerprint(self) -> str:
        return self.document["content_fingerprint"]

    @property
    def captured_at(self) -> datetime:
        return parse_time(self.document["capture"]["captured_at"], "captured_at")  # type: ignore[return-value]

    @property
    def started_at(self) -> datetime | None:
        return parse_time(self.document["session"]["started_at"], "started_at", optional=True)

    @property
    def ended_at(self) -> datetime | None:
        return parse_time(self.document["session"]["ended_at"], "ended_at", optional=True)

    @property
    def conversation_ids(self) -> tuple[str, ...]:
        return self.document["session"]["conversation_ids"]

    @property
    def session_ids(self) -> tuple[str, ...]:
        return self.document["session"]["session_ids"]

    @property
    def findings(self) -> tuple[Mapping[str, Any], ...]:
        return self.document["anomalies"]["findings"]

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.document)

    def encode(self) -> bytes:
        """Canonical JSON bytes (sorted keys, compact UTF-8): equal bundles, equal bytes."""
        return canonical_json(self.to_dict()).encode("utf-8")

    @classmethod
    def from_dict(cls, payload: object) -> DiagnosticBundle:
        if not isinstance(payload, Mapping):
            raise fail("bundle must be a JSON object")
        return cls(payload)  # type: ignore[arg-type]

    @classmethod
    def decode(cls, data: bytes | str) -> DiagnosticBundle:
        """Strict decode of an encoded bundle (UTF-8, size bound, duplicate keys and NaN refused)."""
        if isinstance(data, bytes):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError:
                raise fail("bundle is not UTF-8 text", "testlab_json_invalid") from None
        return cls.from_dict(decode_json_document(data, max_bytes=MAX_BUNDLE_BYTES))

