"""Pure DiagnosticBundle builder: mechanical aggregation of one session's evidence.

Binding contract: `docs/testlab.md` ("DiagnosticBundle"). Pure: no I/O, no clock
(the capture time is an input), no model. The capture service
(`bundle_capture.py`) reads and selects the evidence; this module only derives:

- inputs are already selected: Conversation Events (`StoredConversationEvent`),
  **projected** `RuntimeJournal` lines (allowlisted scalar data only, never a raw
  payload or message), voice session metric reports, and the `trace_summary`
  aggregate. The builder does not select again;
- every derived item keeps the references of the evidence that produced it
  (`cev-...` event ids, `trace:<offset>` lines, `report:<sha16>` reports);
- public conversation content (`visibility == public` events only) is copied
  into `turns[].content` when enabled, redacted with `redact_identifying_text`
  and bounded. Diagnostic content (speech requests, withheld speech) is read in
  memory for the duplicate-payload rule and never emitted;
- sections are sorted, capped (`SECTION_LIMITS`, drops counted in
  `coverage.limits`) and encoded canonically, so equal inputs give equal bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from types import MappingProxyType
from typing import Any

from jarvis.domain.conversation_event_store import StoredConversationEvent
from jarvis.domain.conversation_events import (
    MAX_CONTENT_CHARS,
    ConversationEvent,
    ConversationEventType,
    ConversationVisibility,
    reconstruct_conversation,
)
from jarvis.testlab.bundle import (
    BUNDLE_SCHEMA_VERSION,
    LATENCY_MEASURES,
    LATENCY_STAGES,
    MAX_EVIDENCE_REFS,
    MAX_IDS,
    READ_STATUSES,
    SECTION_LIMITS,
    TERMINAL_OUTCOMES,
    MAX_SELECTION_HOURS,
    MAX_UTTERANCE_MS,
    USER_CLOSING_ACTIVITIES,
    USER_ONSET_ACTIVITIES,
    BargeInOutcome,
    BrainEvent,
    CoverageWarning,
    DiagnosticBundle,
    LifecycleEvent,
    ProviderEvent,
    SourceStatus,
    SpeechOutcome,
    TurnActor,
    TurnKind,
    UserActivity,
    bundle_content_fingerprint,
    derive_bundle_id,
    is_code_token,
    is_opaque_id,
    report_ref,
    trace_ref,
)
from jarvis.testlab.bundle_rules import (
    DEFAULT_RULES,
    SOURCE_CONVERSATION_EVENTS,
    SOURCE_RUNTIME_JOURNAL,
    AnomalyRule,
    RuleContext,
    Segment,
    check_rules,
    evaluate_rules,
    normalize_payload,
    segment_of,
)
from jarvis.testlab.identity import DIAGNOSTIC_BUNDLE_SCHEMA
from jarvis.testlab.redaction import redact_identifying_text
from jarvis.testlab.runs import CodeIdentity
from jarvis.testlab.validation import MAX_JSON_INT, check_hex, check_time, fail, format_time, parse_time

_T = ConversationEventType
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_SUMMARY_ENTRIES = 512
_PENDING_RESOLUTION = timedelta(seconds=30)
_ATTACH_WINDOW = timedelta(seconds=5)


# ------------------------------------------------------------------ inputs

@dataclass(frozen=True, slots=True)
class SessionSelector:
    """Which session a bundle describes: a conversation, a voice session, and/or a time window [start, end]."""

    conversation_id: str | None = None
    session_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("conversation_id", "session_id"):
            value = getattr(self, name)
            if value is not None and not is_opaque_id(value):
                raise fail(f"selector.{name} must be a nonempty bounded opaque identifier")
        check_time(self.start, "selector.start", optional=True)
        check_time(self.end, "selector.end", optional=True)
        if self.conversation_id is None and self.session_id is None and (self.start is None or self.end is None):
            raise fail("selector needs a conversation_id, a session_id, or both start and end")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise fail("selector.end must be after selector.start")

    def to_dict(self) -> dict[str, Any]:
        return {"conversation_id": self.conversation_id, "session_id": self.session_id,
                "start": format_time(self.start), "end": format_time(self.end)}


@dataclass(frozen=True, slots=True)
class TraceLine:
    """One `RuntimeJournal` line after projection: allowlisted scalar `data`, no message, no raw payload."""

    #: Byte offset of the line start in the trace file (the stable reference).
    offset: int
    ts: datetime
    kind: str
    level: str | None
    data: Mapping[str, Any]
    #: True when the line itself carries the selected conversation or session id (else included by time window).
    matched: bool = True

    def __post_init__(self) -> None:
        if type(self.offset) is not int or not 0 <= self.offset <= MAX_JSON_INT:
            raise fail("trace line offset must be a nonnegative integer")
        check_time(self.ts, "trace line ts")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class TraceEvidence:
    status: SourceStatus
    lines: tuple[TraceLine, ...] = ()
    lines_in_window: int = 0
    corrupt_lines: int = 0
    oversized_lines: int = 0
    untimed_lines: int = 0
    truncated: bool = False
    start_truncated: bool = False
    #: The file ended with a line without newline (being written, or torn): not decoded.
    torn_tail: bool = False
    #: A window was requested and the journal ended before a line later than its end: a recapture may differ.
    window_open: bool = False
    stopped_by: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class EventEvidence:
    status: SourceStatus
    #: `store` (a `ConversationEventStore`) or `export` (a `jarvis.conversation-events.export` file).
    origin: str | None = None
    events: tuple[StoredConversationEvent, ...] = ()
    skipped_rows: int = 0
    export_complete: bool | None = None
    truncated: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class VoiceSessionReport:
    """Projection of one `jarvis.voice_benchmark.session` report (`VoiceSessionMetricRecorder`)."""

    sha256: str
    session_id: str
    architecture: str | None = None
    configuration_id: str | None = None
    session_fingerprint: str | None = None
    terminal_status: str | None = None
    trace_evidence_complete: bool | None = None
    #: (name, count, min_ms, max_ms, mean_ms)
    latency: tuple[tuple[str, int, float | None, float | None, float | None], ...] = ()
    #: (name, value)
    counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ReportEvidence:
    status: SourceStatus
    reports: tuple[VoiceSessionReport, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CaptureContext:
    """Capture-time facts (outside the content fingerprint): when, and which code/config captured it."""

    captured_at: datetime
    code: CodeIdentity | None = None
    config_fingerprint: str | None = None

    def __post_init__(self) -> None:
        check_time(self.captured_at, "captured_at")
        if self.code is not None and not isinstance(self.code, CodeIdentity):
            raise fail("capture code must be a CodeIdentity")
        check_hex(self.config_fingerprint, "config_fingerprint", lengths=(64,), optional=True)


@dataclass(frozen=True, slots=True)
class BundleOptions:
    #: Copy public conversation content (redacted, bounded). False: every `content` is null.
    include_public_content: bool = True
    max_content_chars: int = 512
    rules: tuple[AnomalyRule, ...] = DEFAULT_RULES

    def __post_init__(self) -> None:
        if type(self.include_public_content) is not bool:
            raise fail("include_public_content must be a boolean")
        if type(self.max_content_chars) is not int or not 1 <= self.max_content_chars <= MAX_CONTENT_CHARS:
            raise fail(f"max_content_chars must be an integer from 1 to {MAX_CONTENT_CHARS}")
        check_rules(self.rules)


NOT_REQUESTED_EVENTS = EventEvidence(SourceStatus.NOT_REQUESTED)
NOT_REQUESTED_TRACE = TraceEvidence(SourceStatus.NOT_REQUESTED)
NOT_REQUESTED_REPORTS = ReportEvidence(SourceStatus.NOT_REQUESTED)


# ----------------------------------------------------------------- helpers

def _id(value: object) -> str | None:
    return value if is_opaque_id(value) else None


def _code(value: object) -> str | None:
    return value if is_code_token(value) else None


def _number(value: object) -> int | float | None:
    if type(value) in (int, float) and value == value and 0 <= value <= MAX_JSON_INT:
        return value
    return None


def _ms(delta: timedelta) -> int:
    return int(delta / timedelta(milliseconds=1))


def _by_time(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Time order, then evidence order (a journal offset or event id), so equal inputs give equal lists."""
    return sorted(items, key=lambda item: (item["at"], item["evidence"]))


def _wire_time(value: str) -> datetime:
    return parse_time(value, "time")  # type: ignore[return-value]


class _Evidence:
    """Insertion-ordered, deduplicated, capped evidence references."""

    __slots__ = ("refs",)

    def __init__(self) -> None:
        self.refs: dict[str, None] = {}

    def add(self, ref: str) -> None:
        if len(self.refs) < MAX_EVIDENCE_REFS:
            self.refs.setdefault(ref, None)

    def emit(self) -> list[str]:
        return list(self.refs)


class _Times:
    """Earliest moment of one kind of observation, with every reference that observed it."""

    __slots__ = ("at", "evidence")

    def __init__(self) -> None:
        self.at: datetime | None = None
        self.evidence = _Evidence()

    def note(self, at: datetime, ref: str) -> None:
        if self.at is None or at < self.at:
            self.at = at
        self.evidence.add(ref)


# ------------------------------------------------------------------ speech

class _Speech:
    def __init__(self, speech_id: str) -> None:
        self.speech_id = speech_id
        self.conversation_id: str | None = None
        self.correlation_id: str | None = None
        self.work_id: str | None = None
        self.parent_speech_id: str | None = None
        self.chunks: set[str] = set()
        self.output_ids: set[str] = set()
        self.kind: str | None = None
        self.priority: str | None = None
        self.stages = {name: _Times() for name in ("requested", "queued", "dispatched", "started")}
        self.terminals: dict[SpeechOutcome, _Times] = {}
        self.terminal_reasons: dict[SpeechOutcome, str] = {}
        self.played_ms: int | float | None = None
        self.queue_wait_ms: int | float | None = None
        self.codes: set[str] = set()
        self.evidence = _Evidence()
        self.payload: str | None = None
        self.request_payload: str | None = None
        self.spoken_divergences = 0
        self.spoken_diverged_at: datetime | None = None
        self.state_divergences = 0

    def fill(self, *, conversation_id: object = None, correlation_id: object = None, work_id: object = None,
             kind: object = None, priority: object = None, output_id: object = None) -> None:
        self.conversation_id = self.conversation_id or _id(conversation_id)
        self.correlation_id = self.correlation_id or _id(correlation_id)
        self.work_id = self.work_id or _id(work_id)
        self.kind = self.kind or _code(kind)
        self.priority = self.priority or _code(priority)
        if _id(output_id) and len(self.output_ids) < 16:
            self.output_ids.add(output_id)  # type: ignore[arg-type]

    def stage(self, name: str, at: datetime, ref: str) -> None:
        self.stages[name].note(at, ref)
        self.evidence.add(ref)

    def terminal(self, outcome: SpeechOutcome, at: datetime, ref: str, reason: object = None) -> None:
        self.terminals.setdefault(outcome, _Times()).note(at, ref)
        if _code(reason) and outcome not in self.terminal_reasons:
            self.terminal_reasons[outcome] = reason  # type: ignore[assignment]
        self.evidence.add(ref)

    def first_terminal(self) -> tuple[SpeechOutcome, _Times] | None:
        if not self.terminals:
            return None
        order = {outcome: index for index, outcome in enumerate(TERMINAL_OUTCOMES)}
        return min(self.terminals.items(), key=lambda item: (item[1].at, order[item[0]]))

    def first_known_time(self) -> datetime | None:
        moments = [times.at for times in (*self.stages.values(), *self.terminals.values()) if times.at is not None]
        return min(moments) if moments else None


_CE_SPEECH_TERMINALS: Mapping[ConversationEventType, SpeechOutcome] = MappingProxyType({
    _T.MOUTH_SPEECH_COMPLETED: SpeechOutcome.SPOKEN,
    _T.MOUTH_SPEECH_INTERRUPTED: SpeechOutcome.INTERRUPTED,
    _T.MOUTH_SPEECH_SUPERSEDED: SpeechOutcome.SUPERSEDED,
    _T.MOUTH_SPEECH_EXPIRED: SpeechOutcome.STALE,
    _T.MOUTH_SPEECH_FAILED: SpeechOutcome.FAILED,
})
_TRACE_SPEECH_STAGES: Mapping[str, str] = MappingProxyType({
    "voice.speech.queued": "queued",
    "voice.speech.dispatched": "dispatched",
    "voice.speech.started": "started",
})
_TRACE_SPEECH_TERMINALS: Mapping[str, SpeechOutcome] = MappingProxyType({
    "voice.speech.completed": SpeechOutcome.SPOKEN,
    "voice.speech.interrupted": SpeechOutcome.INTERRUPTED,
    "voice.speech.superseded": SpeechOutcome.SUPERSEDED,
    "voice.speech.expired": SpeechOutcome.STALE,
    "voice.speech.speak_failed": SpeechOutcome.FAILED,
})
#: Speech lines that only add a code to their speech (`codes`).
_TRACE_SPEECH_CODES = frozenset({"voice.speech.output_stalled"})

#: Provider connection, error and cancel journal kinds (docs/testlab.md, "Evidence sources").
PROVIDER_KINDS: Mapping[str, ProviderEvent] = MappingProxyType({
    "provider.models_failed": ProviderEvent.MODELS_FAILED,
    "voice.connecting": ProviderEvent.CONNECTING,
    "voice.active": ProviderEvent.CONNECTED,
    "provider.disconnected": ProviderEvent.DISCONNECTED,
    "provider.error": ProviderEvent.ERROR,
    "voice.provider_error": ProviderEvent.ERROR,
    "provider.keepalive_failed": ProviderEvent.KEEPALIVE_FAILED,
    "voice.provider_refused": ProviderEvent.REFUSED,
    "voice.failure": ProviderEvent.FAILURE,
    "voice.response_silent": ProviderEvent.RESPONSE_SILENT,
    "voice.manual_cancel": ProviderEvent.CANCEL_REQUESTED,
})
#: Output-level journal kinds that describe one playback (keyed by `output_id`).
PLAYBACK_KINDS = frozenset({
    "voice.output_started", "voice.latency.provider_first_pcm", "voice.latency.playback_attempted",
    "voice.latency.output_first_write", "voice.latency.first_audible_write", "audio.drain_requested",
    "audio.drain_result",
})
_BARGE_IN_KINDS = frozenset({
    "voice.barge_in_pending", "voice.barge_in", "voice.barge_in_rejected", "voice.barge_in_ignored",
    "voice.barge_in_degraded", "voice.barge_in.owner_confirmed", "voice.barge_in.provider_advisory",
})
#: Voice-side latency lines whose `elapsed_ms` is a producer-measured duration (`reported`).
_REPORTED_LATENCY_PREFIX = "voice.latency."
_IDENTITY_KINDS = frozenset({"voice.stack", "voice.active"})
#: User activity (timing and ids only, never text).
USER_ACTIVITY_KINDS: Mapping[str, UserActivity] = MappingProxyType({
    "voice.speech_started": UserActivity.SPEECH_STARTED,
    "voice.input_submitted": UserActivity.INPUT_SUBMITTED,
    "voice.transcript": UserActivity.TRANSCRIPT,
    "voice.brain_turn_submitted": UserActivity.TURN_SUBMITTED,
    "voice.turn_completed": UserActivity.TURN_COMPLETED,
    "voice.transcript_dropped": UserActivity.TRANSCRIPT_DROPPED,
    "voice.manual_submit": UserActivity.MANUAL_SUBMIT,
})
#: Voice runtime and audio device lifecycle.
LIFECYCLE_KINDS: Mapping[str, LifecycleEvent] = MappingProxyType({
    "voice.start": LifecycleEvent.STARTED,
    "voice.stop": LifecycleEvent.STOPPED,
    "audio.output_stopped": LifecycleEvent.OUTPUT_STOPPED,
    "audio.device_closed": LifecycleEvent.DEVICE_CLOSED,
    "audio.native_failed": LifecycleEvent.NATIVE_FAILED,
    "voice.speech.stream_closed": LifecycleEvent.STREAM_CLOSED,
    "voice.timeout": LifecycleEvent.TIMEOUT,
})
#: Brain supersession, budget and latency facts.
BRAIN_KINDS: Mapping[str, BrainEvent] = MappingProxyType({
    "core.brain.replies_superseded": BrainEvent.REPLIES_SUPERSEDED,
    "core.brain.turn_slow": BrainEvent.TURN_SLOW,
    "core.brain.turn_over_budget": BrainEvent.TURN_OVER_BUDGET,
    "core.brain.latency.work_completed": BrainEvent.WORK_COMPLETED,
})
USAGE_KIND = "voice.realtime.usage"
#: Output lines proving that Jarvis audio reached the device (a barge-in can only cut audible output).
AUDIBLE_WRITE_KINDS = frozenset({"voice.latency.first_audible_write", "voice.latency.output_first_write"})
#: Voice state divergence observations, counted on the speech they name.
DIVERGENCE_KINDS: Mapping[str, str] = MappingProxyType({
    "voice.state.spoken_diverged": "spoken",
    "voice.state.diverged": "state",
})
#: Voice session segmentation (docs/testlab.md, "Voice session segments"). Declared data.
SEGMENT_START_KINDS = frozenset({"voice.start", "voice.connecting"})
SEGMENT_END_KINDS = frozenset({"voice.stop", "voice.failure", "audio.device_closed"})
#: Two evidence items further apart than this belong to different segments.
SEGMENT_IDLE_GAP_MS = 10 * 60 * 1000
#: Facts that can explain a missing delivery outcome (`cause`): lifecycle and provider events.
FAILURE_CAUSES = frozenset({LifecycleEvent.NATIVE_FAILED.value, LifecycleEvent.DEVICE_CLOSED.value,
                            LifecycleEvent.STREAM_CLOSED.value, LifecycleEvent.STOPPED.value,
                            LifecycleEvent.TIMEOUT.value, ProviderEvent.ERROR.value, ProviderEvent.DISCONNECTED.value,
                            ProviderEvent.FAILURE.value, ProviderEvent.KEEPALIVE_FAILED.value,
                            ProviderEvent.REFUSED.value})

#: Every journal kind the builder reads (plus the `voice.latency.` prefix). The capture service
#: selects only these (and the `trace_summary` inputs), so unused kinds never eat the selection budget.
MAPPED_JOURNAL_KINDS = frozenset({
    *_TRACE_SPEECH_STAGES, *_TRACE_SPEECH_TERMINALS, *_TRACE_SPEECH_CODES, "voice.brain_turn_submitted",
    "core.brain.turn_failed", "core.brain.outcome_retained", "voice.reflex.started", *PLAYBACK_KINDS,
    *_BARGE_IN_KINDS, *PROVIDER_KINDS, *_IDENTITY_KINDS, *USER_ACTIVITY_KINDS, *LIFECYCLE_KINDS, *BRAIN_KINDS,
    USAGE_KIND, *DIVERGENCE_KINDS, *SEGMENT_START_KINDS, *SEGMENT_END_KINDS,
})
MAPPED_JOURNAL_PREFIXES = (_REPORTED_LATENCY_PREFIX,)


def is_mapped_journal_kind(kind: str) -> bool:
    return kind in MAPPED_JOURNAL_KINDS or kind.startswith(MAPPED_JOURNAL_PREFIXES)


# ---------------------------------------------------------------- builder

class _Builder:
    def __init__(self, selector: SessionSelector, context: CaptureContext, events: EventEvidence,
                 trace: TraceEvidence, reports: ReportEvidence, trace_summary: Mapping[str, Any] | None,
                 options: BundleOptions) -> None:
        self.selector, self.context, self.options = selector, context, options
        self.events_evidence, self.trace_evidence, self.report_evidence = events, trace, reports
        #: At most 16 reports (the schema bound), in a stable order.
        self.report_list = sorted(reports.reports, key=lambda item: (item.session_id, item.sha256))[:16]
        self.trace_summary = trace_summary
        self.limits: list[dict[str, Any]] = []
        self.events = self._unique_events(events.events)
        self.lines = self._unique_lines(trace.lines)
        self.used_lines: dict[int, TraceLine] = {}
        self.content_items = self.truncated_items = self.redactions = 0
        self.speech: dict[str, _Speech] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.turn_evidence: dict[str, _Evidence] = {}
        self.turn_times: dict[str, datetime] = {}
        self.user_activity: list[dict[str, Any]] = []
        self.lifecycle: list[dict[str, Any]] = []
        self.brain: list[dict[str, Any]] = []
        self.usage: list[dict[str, Any]] = []
        self.segments: list[Segment] = []
        self.segment_rows: list[dict[str, Any]] = []

    # -------------------------------------------------------- input caps

    def _cap(self, section: str, items: list[Any]) -> list[Any]:
        limit = SECTION_LIMITS[section]
        if len(items) > limit:
            self.limits.append({"section": section, "kept": limit, "dropped": len(items) - limit})
            return items[:limit]
        return items

    def _unique_events(self, stored: Sequence[StoredConversationEvent]) -> list[StoredConversationEvent]:
        by_id: dict[str, StoredConversationEvent] = {}
        for item in stored:
            if not isinstance(item, StoredConversationEvent):
                raise fail("events must be StoredConversationEvent values")
            known = by_id.get(item.event.event_id)
            if known is None or item.sequence < known.sequence:
                by_id[item.event.event_id] = item
        ordered = sorted(by_id.values(), key=lambda item: (item.sequence, item.event.event_id))
        return sorted(self._cap("conversation_events", ordered),
                      key=lambda item: (item.event.occurred_at, item.event.event_id))

    def _unique_lines(self, lines: Sequence[TraceLine]) -> list[TraceLine]:
        by_offset: dict[int, TraceLine] = {}
        for line in lines:
            if not isinstance(line, TraceLine):
                raise fail("trace lines must be TraceLine values")
            by_offset.setdefault(line.offset, line)
        return self._cap("trace_lines", [by_offset[offset] for offset in sorted(by_offset)])

    def ref(self, line: TraceLine) -> str:
        self.used_lines[line.offset] = line
        return trace_ref(line.offset)

    # ----------------------------------------------------------- content

    def content(self, event: ConversationEvent) -> tuple[str | None, bool]:
        if (not self.options.include_public_content or event.visibility is not ConversationVisibility.PUBLIC
                or event.content is None):
            return None, False
        text, changes = redact_identifying_text(event.content)
        self.redactions += changes
        truncated = len(text) > self.options.max_content_chars
        text = text[:self.options.max_content_chars]
        if not text.strip():
            return None, False
        self.content_items += 1
        self.truncated_items += truncated
        return text, truncated

    # -------------------------------------------------------------- turns

    def turn(self, item_id: str, *, actor: TurnActor, kind: TurnKind, at: datetime, ref: str,
             status: str | None = None, content: tuple[str | None, bool] = (None, False), **ids: object) -> None:
        item = self.turns.get(item_id)
        if item is None:
            item = {"item_id": item_id, "actor": actor.value, "kind": kind.value, "status": None,
                    "conversation_id": None, "session_id": None, "turn_id": None, "correlation_id": None,
                    "speech_id": None, "outcome_id": None, "content": None, "content_truncated": False}
            self.turns[item_id] = item
            self.turn_evidence[item_id] = _Evidence()
            self.turn_times[item_id] = at
        self.turn_times[item_id] = min(self.turn_times[item_id], at)
        item["status"] = item["status"] or _code(status)
        for name, value in ids.items():
            item[name] = item[name] or _id(value)
        if item["content"] is None and content[0] is not None:
            item["content"], item["content_truncated"] = content
        self.turn_evidence[item_id].add(ref)

    def speech_record(self, speech_id: str) -> _Speech:
        record = self.speech.get(speech_id)
        if record is None:
            record = self.speech[speech_id] = _Speech(speech_id)
        return record

    # -------------------------------------------------- conversation events

    def derive_events(self) -> None:
        requests: dict[str, str] = {}
        for stored in self.events:
            event = stored.event
            if event.event_type is _T.BRAIN_SPEECH_REQUESTED:
                requests[event.event_id] = event.speech_id  # type: ignore[assignment]
        for stored in self.events:
            event, ref, at = stored.event, stored.event.event_id, stored.event.occurred_at
            kind = event.event_type
            ids = {"conversation_id": event.conversation_id, "session_id": event.session_id,
                   "correlation_id": event.correlation_id}
            attributes = event.attributes
            if kind is _T.USER_TRANSCRIPT_ACCEPTED:
                self.turn(f"user:{event.correlation_id}", actor=TurnActor.USER, kind=TurnKind.USER_TURN, at=at,
                          ref=ref, status="accepted", content=self.content(event), turn_id=event.turn_id, **ids)
            elif kind is _T.BRAIN_TURN_ACCEPTED:
                self.turn(f"brain_accepted:{event.correlation_id}", actor=TurnActor.BRAIN,
                          kind=TurnKind.TURN_ACCEPTED, at=at, ref=ref, status=attributes.get("source"),
                          turn_id=event.turn_id, **ids)
            elif kind is _T.BRAIN_TURN_FAILED:
                self.turn(f"brain_failed:{event.correlation_id}", actor=TurnActor.BRAIN, kind=TurnKind.TURN_FAILED,
                          at=at, ref=ref, status=attributes.get("code"), **ids)
            elif kind is _T.BRAIN_MESSAGE_PUBLISHED:
                self.turn(f"brain_message:{event.outcome_id}", actor=TurnActor.BRAIN,
                          kind=TurnKind.MESSAGE_PUBLISHED, at=at, ref=ref, content=self.content(event),
                          outcome_id=event.outcome_id, **ids)
            elif kind is _T.MOUTH_REFLEX_STARTED:
                output = attributes.get("output_id") if _id(attributes.get("output_id")) else event.event_id
                self.turn(f"reflex:{event.correlation_id}:{output}", actor=TurnActor.MOUTH, kind=TurnKind.REFLEX,
                          at=at, ref=ref, content=self.content(event), **ids)
            elif kind is _T.BRAIN_SPEECH_REQUESTED:
                record = self.speech_record(event.speech_id)  # type: ignore[arg-type]
                record.fill(kind=attributes.get("kind"), priority=attributes.get("priority"), work_id=event.work_id,
                            **{key: value for key, value in ids.items() if key != "session_id"})
                record.stage("requested", at, ref)
                if event.content is not None:
                    record.request_payload = event.content  # in memory only (diagnostic content)
            elif kind.value.startswith("mouth.speech."):
                self._mouth_speech(event, ref, at, requests, ids)

    def _mouth_speech(self, event: ConversationEvent, ref: str, at: datetime, requests: Mapping[str, str],
                      ids: Mapping[str, object]) -> None:
        record = self.speech_record(event.speech_id)  # type: ignore[arg-type]
        attributes = event.attributes
        record.fill(kind=attributes.get("kind"), priority=attributes.get("priority"), work_id=event.work_id,
                    output_id=attributes.get("output_id"),
                    **{key: value for key, value in ids.items() if key != "session_id"})
        parent = requests.get(event.parent_event_id or "")
        if parent is not None and parent != record.speech_id:
            record.parent_speech_id = record.parent_speech_id or parent
            self.speech_record(parent).chunks.add(record.speech_id)
        kind = event.event_type
        if kind is _T.MOUTH_SPEECH_QUEUED:
            record.stage("queued", at, ref)
        elif kind is _T.MOUTH_SPEECH_STARTED:
            record.stage("started", at, ref)
            if event.content is not None:
                record.payload = event.content
            self.turn(f"mouth:{record.speech_id}", actor=TurnActor.MOUTH, kind=TurnKind.SPEECH, at=at, ref=ref,
                      content=self.content(event), speech_id=record.speech_id, **ids)
        else:
            outcome = _CE_SPEECH_TERMINALS[kind]
            record.terminal(outcome, at, ref, attributes.get("reason") or attributes.get("code"))
            played = _number(attributes.get("played_ms"))
            if outcome is SpeechOutcome.INTERRUPTED and played is not None:
                record.played_ms = played if record.played_ms is None else record.played_ms
            if event.content is not None and record.payload is None:
                record.request_payload = record.request_payload or event.content  # withheld text: memory only

    # --------------------------------------------------------- trace lines

    def derive_trace(self) -> None:
        output_speech: dict[str, str] = {}
        for line in self.lines:
            speech_id, output_id = _id(line.data.get("speech_id")), _id(line.data.get("output_id"))
            if speech_id and output_id:
                output_speech.setdefault(output_id, speech_id)
        for line in self.lines:
            kind, data = line.kind, line.data
            speech_id = _id(data.get("speech_id")) or output_speech.get(_id(data.get("output_id")) or "")
            if kind in USER_ACTIVITY_KINDS:
                near = data.get("near_playback")
                self.user_activity.append({
                    "at": format_time(line.ts), "event": USER_ACTIVITY_KINDS[kind].value,
                    "conversation_id": _id(data.get("conversation_id")),
                    "code": _code(data.get("reason")) or _code(data.get("code")) or _code(data.get("addressing")),
                    "near_playback": near if type(near) is bool else None, "evidence": [self.ref(line)]})
            if kind in _TRACE_SPEECH_STAGES or kind in _TRACE_SPEECH_TERMINALS or kind in _TRACE_SPEECH_CODES:
                if speech_id is None:
                    continue
                self._trace_speech(line, speech_id)
            elif kind == "voice.brain_turn_submitted":
                key = _id(data.get("correlation_id")) or f"trace:{line.offset}"
                self.turn(f"user:{key}", actor=TurnActor.USER, kind=TurnKind.USER_TURN, at=line.ts, ref=self.ref(line),
                          status="submitted", conversation_id=data.get("conversation_id"),
                          session_id=data.get("session_id"), turn_id=data.get("turn_id"),
                          correlation_id=data.get("correlation_id"))
            elif kind == "core.brain.turn_failed" and _id(data.get("correlation_id")):
                self.turn(f"brain_failed:{data['correlation_id']}", actor=TurnActor.BRAIN, kind=TurnKind.TURN_FAILED,
                          at=line.ts, ref=self.ref(line), conversation_id=data.get("conversation_id"),
                          correlation_id=data.get("correlation_id"))
            elif kind == "core.brain.outcome_retained" and _id(data.get("outcome_id")):
                self.turn(f"brain_message:{data['outcome_id']}", actor=TurnActor.BRAIN,
                          kind=TurnKind.MESSAGE_PUBLISHED, at=line.ts, ref=self.ref(line), status=data.get("kind"),
                          conversation_id=data.get("conversation_id"), correlation_id=data.get("correlation_id"),
                          outcome_id=data.get("outcome_id"))
            elif kind in LIFECYCLE_KINDS:
                self.lifecycle.append({
                    "at": format_time(line.ts), "event": LIFECYCLE_KINDS[kind].value, "code": _code(data.get("code")),
                    "conversation_id": _id(data.get("conversation_id")), "session_id": _id(data.get("session_id")),
                    "evidence": [self.ref(line)]})
            elif kind in BRAIN_KINDS:
                work_ids = data.get("work_ids") if isinstance(data.get("work_ids"), (list, tuple)) else ()
                ids = sorted({item for item in work_ids if _id(item)} | ({data["work_id"]} if _id(data.get("work_id"))
                                                                          else set()))[:16]
                self.brain.append({
                    "at": format_time(line.ts), "event": BRAIN_KINDS[kind].value,
                    "conversation_id": _id(data.get("conversation_id")),
                    "correlation_id": _id(data.get("correlation_id")), "work_ids": ids,
                    "measure": _code(data.get("measure")),
                    "ms": _number(data.get("elapsed_ms")) if _number(data.get("elapsed_ms")) is not None
                    else _number(data.get("duration_ms")),
                    "budget_ms": _number(data.get("budget_ms")), "evidence": [self.ref(line)]})
            elif kind == USAGE_KIND:
                tokens = {name: data.get(name) if type(data.get(name)) is int and data.get(name) >= 0 else None
                          for name in ("input_tokens", "output_tokens")}
                self.usage.append({
                    "at": format_time(line.ts), "conversation_id": _id(data.get("conversation_id")),
                    "session_id": _id(data.get("session_id")), **tokens,
                    "duration_seconds": _number(data.get("duration_seconds")), "source": _code(data.get("source")),
                    "evidence": [self.ref(line)]})
            elif kind in DIVERGENCE_KINDS and speech_id is not None:
                record = self.speech_record(speech_id)
                record.fill(conversation_id=data.get("conversation_id"))
                record.evidence.add(self.ref(line))
                if DIVERGENCE_KINDS[kind] == "spoken":
                    record.spoken_divergences += 1
                    if record.spoken_diverged_at is None or line.ts < record.spoken_diverged_at:
                        record.spoken_diverged_at = line.ts
                else:
                    record.state_divergences += 1
            elif kind == "voice.reflex.started" and _id(data.get("output_id")):
                self.turn(f"reflex:{data.get('correlation_id')}:{data['output_id']}", actor=TurnActor.MOUTH,
                          kind=TurnKind.REFLEX, at=line.ts, ref=self.ref(line),
                          conversation_id=data.get("conversation_id"), session_id=data.get("session_id"),
                          correlation_id=data.get("correlation_id"))

    def _trace_speech(self, line: TraceLine, speech_id: str) -> None:
        record, data, ref = self.speech_record(speech_id), line.data, self.ref(line)
        record.fill(conversation_id=data.get("conversation_id"), correlation_id=data.get("correlation_id"),
                    work_id=data.get("work_id"), kind=data.get("kind"), priority=data.get("priority"),
                    output_id=data.get("output_id"))
        kind = line.kind
        if kind in _TRACE_SPEECH_STAGES:
            record.stage(_TRACE_SPEECH_STAGES[kind], line.ts, ref)
            if kind == "voice.speech.dispatched" and record.queue_wait_ms is None:
                record.queue_wait_ms = _number(data.get("queue_wait_ms"))
            if kind == "voice.speech.started":
                self.turn(f"mouth:{speech_id}", actor=TurnActor.MOUTH, kind=TurnKind.SPEECH, at=line.ts, ref=ref,
                          conversation_id=data.get("conversation_id"), session_id=data.get("session_id"),
                          correlation_id=data.get("correlation_id"), speech_id=speech_id)
        elif kind in _TRACE_SPEECH_TERMINALS:
            outcome = _TRACE_SPEECH_TERMINALS[kind]
            record.terminal(outcome, line.ts, ref, data.get("reason") or data.get("code"))
            played = _number(data.get("played_ms"))
            if outcome is SpeechOutcome.INTERRUPTED and played is not None and record.played_ms is None:
                record.played_ms = played
        else:
            code = _code(data.get("code"))
            if code is not None and len(record.codes) < 16:
                record.codes.add(code)
            record.evidence.add(ref)

    # ------------------------------------------------------------ sections

    def voice_side_read(self) -> bool:
        return (self.trace_evidence.status in READ_STATUSES
                or any(stored.event.event_type.value.startswith("mouth.") for stored in self.events))

    def speech_items(self) -> list[dict[str, Any]]:
        voice_read = self.voice_side_read()
        items = []
        for record in self.speech.values():
            if record.first_known_time() is None and not record.chunks:
                continue  # only divergence lines named it: counted nowhere else, no stage to describe
            first = record.first_terminal()
            stages = record.stages
            if first is not None:
                outcome, ended = first[0], first[1].at
            elif record.chunks:
                outcome, ended = SpeechOutcome.CHUNKED, None
            elif stages["started"].at is not None:
                outcome, ended = SpeechOutcome.STARTED, None
            elif stages["queued"].at is not None or stages["dispatched"].at is not None:
                outcome, ended = SpeechOutcome.QUEUED, None
            else:
                outcome, ended = (SpeechOutcome.DROPPED if voice_read else SpeechOutcome.UNKNOWN), None
            terminals = [{"outcome": outcome_key.value, "at": format_time(times.at),
                          "reason": record.terminal_reasons.get(outcome_key), "evidence": times.evidence.emit()}
                         for outcome_key, times in sorted(record.terminals.items(),
                                                          key=lambda item: (item[1].at, item[0].value))]
            items.append({
                "speech_id": record.speech_id, "conversation_id": record.conversation_id,
                "correlation_id": record.correlation_id, "work_id": record.work_id,
                "parent_speech_id": record.parent_speech_id, "chunk_speech_ids": sorted(record.chunks)[:MAX_IDS],
                "output_ids": sorted(record.output_ids), "kind": record.kind, "priority": record.priority,
                "outcome": outcome.value, "reason": record.terminal_reasons.get(outcome) if first else None,
                "played_ms": record.played_ms, "queue_wait_ms": record.queue_wait_ms,
                "requested_at": format_time(stages["requested"].at), "queued_at": format_time(stages["queued"].at),
                "dispatched_at": format_time(stages["dispatched"].at), "started_at": format_time(stages["started"].at),
                "ended_at": format_time(ended), "codes": sorted(record.codes), "terminals": terminals,
                "spoken_divergences": record.spoken_divergences, "state_divergences": record.state_divergences,
                "spoken_diverged_at": format_time(record.spoken_diverged_at),
                "evidence": record.evidence.emit(),
            })
        order = {record.speech_id: record.first_known_time() or datetime.max.replace(tzinfo=None)
                 for record in self.speech.values()}
        items.sort(key=lambda item: (order[item["speech_id"]], item["speech_id"]))
        return self._cap("speech", items)

    def playback_items(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Playback episodes keyed by `output_id`, plus per-output stage times for latency joins."""
        outputs: dict[str, dict[str, Any]] = {}
        for line in self.lines:
            output_id = _id(line.data.get("output_id"))
            if line.kind not in PLAYBACK_KINDS or output_id is None:
                continue
            entry = outputs.setdefault(output_id, {"started": _Times(), "chunk": _Times(), "write": _Times(),
                                                   "ended": None, "end_status": None, "drain_ms": None,
                                                   "speech_id": None, "conversation_id": None, "source": None,
                                                   "evidence": _Evidence()})
            ref = self.ref(line)
            data = line.data
            entry["evidence"].add(ref)
            entry["started"].note(line.ts, ref)
            entry["speech_id"] = entry["speech_id"] or _id(data.get("speech_id"))
            entry["conversation_id"] = entry["conversation_id"] or _id(data.get("conversation_id"))
            entry["source"] = entry["source"] or _code(data.get("source"))
            if line.kind == "voice.latency.provider_first_pcm":
                entry["chunk"].note(line.ts, ref)
            elif line.kind in ("voice.latency.output_first_write", "voice.latency.first_audible_write"):
                entry["write"].note(line.ts, ref)
            elif line.kind == "audio.drain_result" and entry["ended"] is None:
                entry["ended"], entry["end_status"] = line.ts, _code(data.get("status"))
                entry["drain_ms"] = _number(data.get("elapsed_ms"))
        for line in self.lines:
            output_id = _id(line.data.get("output_id"))
            if line.kind == "voice.barge_in" and output_id in outputs and outputs[output_id]["ended"] is None:
                entry = outputs[output_id]
                entry["ended"], entry["end_status"] = line.ts, "interrupted"
                entry["evidence"].add(self.ref(line))
        items = [{
            "output_id": output_id, "speech_id": entry["speech_id"], "conversation_id": entry["conversation_id"],
            "source": entry["source"], "started_at": format_time(entry["started"].at),
            "provider_chunk_at": format_time(entry["chunk"].at), "first_write_at": format_time(entry["write"].at),
            "ended_at": format_time(entry["ended"]), "end_status": entry["end_status"], "drain_ms": entry["drain_ms"],
            "evidence": entry["evidence"].emit(),
        } for output_id, entry in outputs.items()]
        items.sort(key=lambda item: (item["started_at"], item["output_id"]))
        return self._cap("playback", items), outputs

    @staticmethod
    def speaking_intervals(speech: Sequence[Mapping[str, Any]],
                           playback: Sequence[Mapping[str, Any]]) -> list[tuple[str, str | None, str | None]]:
        """(start, end or None, speech_id) wire intervals where Jarvis output was live.

        A playback without its own end takes the end of the speech it played, when known.
        """
        intervals = [(item["started_at"], item["ended_at"], item["speech_id"]) for item in speech
                     if item["started_at"] is not None]
        speech_end = {item["speech_id"]: item["ended_at"] for item in speech}
        intervals += [(item["started_at"], item["ended_at"] or speech_end.get(item["speech_id"]), item["speech_id"])
                      for item in playback]
        return intervals

    def barge_in_items(self, speech: Sequence[Mapping[str, Any]],
                       playback: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        ordered = sorted((line for line in self.lines if line.kind in _BARGE_IN_KINDS),
                         key=lambda line: (line.ts, line.offset))

        def new(line: TraceLine, outcome: BargeInOutcome) -> dict[str, Any]:
            episode = {"episode_id": f"barge:{line.offset}", "started": line.ts, "ended": line.ts, "outcome": outcome,
                       "authority": _code(line.data.get("authority")), "trigger": None, "speech_id": None,
                       "output_id": None, "played_ms": None, "stop_latency_ms": None, "device_stopped": None,
                       "codes": set(), "evidence": _Evidence()}
            episode["evidence"].add(self.ref(line))
            episodes.append(episode)
            return episode

        def recent_confirmed(line: TraceLine) -> dict[str, Any] | None:
            for episode in reversed(episodes):
                if episode["outcome"] is BargeInOutcome.CONFIRMED and line.ts - episode["ended"] <= _ATTACH_WINDOW:
                    return episode
            return None

        for line in ordered:
            data, kind = line.data, line.kind
            if kind == "voice.barge_in_pending":
                pending.append(new(line, BargeInOutcome.UNRESOLVED))
                continue
            open_pending = next((episode for episode in reversed(pending)
                                 if line.ts - episode["started"] <= _PENDING_RESOLUTION), None)
            if kind in ("voice.barge_in", "voice.barge_in_rejected"):
                outcome = BargeInOutcome.CONFIRMED if kind == "voice.barge_in" else BargeInOutcome.REJECTED
                if open_pending is not None:
                    pending.remove(open_pending)
                    episode = open_pending
                    episode["outcome"], episode["ended"] = outcome, line.ts
                    episode["evidence"].add(self.ref(line))
                else:
                    episode = new(line, outcome)
                pending = [item for item in pending if line.ts - item["started"] <= _PENDING_RESOLUTION]
                episode["authority"] = episode["authority"] or _code(data.get("authority"))
                if outcome is BargeInOutcome.CONFIRMED:
                    episode["trigger"] = _code(data.get("trigger"))
                    episode["speech_id"] = _id(data.get("speech_id"))
                    episode["output_id"] = _id(data.get("output_id"))
                    episode["played_ms"] = _number(data.get("played_ms"))
                    episode["stop_latency_ms"] = _number(data.get("stop_latency_ms"))
                    stopped = data.get("device_stopped")
                    episode["device_stopped"] = stopped if type(stopped) is bool else None
                elif _code(data.get("code")):
                    episode["codes"].add(data["code"])
            elif kind == "voice.barge_in_ignored":
                episode = new(line, BargeInOutcome.IGNORED)
                if _code(data.get("code")):
                    episode["codes"].add(data["code"])
            else:
                target = recent_confirmed(line)
                if target is None:
                    outcome = (BargeInOutcome.CONFIRMED if kind == "voice.barge_in.owner_confirmed"
                               else BargeInOutcome.ADVISORY if kind == "voice.barge_in.provider_advisory"
                               else BargeInOutcome.DEGRADED)
                    target = new(line, outcome)
                else:
                    target["evidence"].add(self.ref(line))
                    target["ended"] = max(target["ended"], line.ts)
                if kind == "voice.barge_in_degraded" and _code(data.get("code")) and len(target["codes"]) < 16:
                    target["codes"].add(data["code"])
                if kind == "voice.barge_in.owner_confirmed":
                    target["trigger"] = target["trigger"] or "owner"
        intervals = self.speaking_intervals(speech, playback)
        speech_outputs = {item["speech_id"]: set(item["output_ids"]) for item in speech}
        items = []
        for episode in episodes:
            start_wire = format_time(episode["started"])
            following, basis = self.user_activity_at(episode["started"])
            outputs = set(speech_outputs.get(episode["speech_id"], ())) | ({episode["output_id"]}
                                                                           if episode["output_id"] else set())
            played = episode["played_ms"]
            if played is not None and played > 0:
                audible: bool | None = True
            elif any(line.kind in AUDIBLE_WRITE_KINDS and line.ts < episode["started"]
                     and line.data.get("output_id") in outputs for line in self.lines):
                audible = True
            else:
                audible = False if (played is not None or outputs) else None
            speaking: bool | None
            if not intervals:
                speaking = None
            else:
                speaking = any(begin <= start_wire and (end is None or end >= start_wire)
                               for begin, end, _ in intervals)
                if episode["speech_id"] is not None and any(sid == episode["speech_id"] for _, _, sid in intervals):
                    speaking = True
            items.append({
                "episode_id": episode["episode_id"], "started_at": start_wire, "ended_at": format_time(episode["ended"]),
                "outcome": episode["outcome"].value, "authority": episode["authority"], "trigger": episode["trigger"],
                "speech_id": episode["speech_id"], "output_id": episode["output_id"], "played_ms": episode["played_ms"],
                "stop_latency_ms": episode["stop_latency_ms"], "device_stopped": episode["device_stopped"],
                "codes": sorted(episode["codes"]), "jarvis_speaking": speaking, "audible": audible,
                "next_user_activity_ms": following, "next_user_activity_basis": basis,
                "evidence": episode["evidence"].emit(),
            })
        items.sort(key=lambda item: (item["started_at"], item["episode_id"]))
        return self._cap("barge_in", items)

    def provider_items(self) -> list[dict[str, Any]]:
        items = []
        for line in self.lines:
            event = PROVIDER_KINDS.get(line.kind)
            if event is None:
                continue
            items.append({"at": format_time(line.ts), "event": event.value, "code": _code(line.data.get("code")),
                          "status": _code(line.data.get("status")), "provider": _code(line.data.get("provider")),
                          "conversation_id": _id(line.data.get("conversation_id")), "evidence": [self.ref(line)]})
        return self._cap("provider", _by_time(items))

    def activity_timeline(self) -> list[tuple[datetime, str, str]]:
        """(time, `onset` or `closing`, reference) of user activity lines, in time then offset order."""
        onsets = {activity.value for activity in USER_ONSET_ACTIVITIES}
        closings = {activity.value for activity in USER_CLOSING_ACTIVITIES}
        timeline = []
        for line in self.lines:
            activity = USER_ACTIVITY_KINDS.get(line.kind)
            if activity is None or activity.value not in onsets | closings:
                continue
            timeline.append((line.ts, "onset" if activity.value in onsets else "closing", self.ref(line)))
        return timeline

    def user_activity_at(self, at: datetime) -> tuple[int | None, str | None]:
        """User activity relative to `at`, inside the segment of `at` (docs/testlab.md, "User activity").

        - an onset at or before `at` not closed before `at`: activity ongoing, 0 ms, `ongoing_onset`;
        - else the first activity after `at`: an onset gives its delay (`onset`); a closing fact with no
          onset in between closes an utterance already under way at `at` when it comes within
          `MAX_UTTERANCE_MS` (0 ms, `closed_without_onset`), otherwise its delay (`closing`);
        - no activity in the segment: (None, None).
        """
        segment = segment_of(self.segments, at)
        timeline = [entry for entry in self.activity_timeline()
                    if segment is None or segment.start <= entry[0] <= segment.end]
        before = [entry for entry in timeline if entry[0] <= at]
        last_onset = max((index for index, entry in enumerate(before) if entry[1] == "onset"), default=None)
        if last_onset is not None and all(entry[1] != "closing" for entry in before[last_onset + 1:]):
            return 0, "ongoing_onset"
        after = [entry for entry in timeline if entry[0] > at]
        if not after:
            return None, None
        delay = _ms(after[0][0] - at)
        if after[0][1] == "onset":
            return delay, "onset"
        return (0, "closed_without_onset") if delay <= MAX_UTTERANCE_MS else (delay, "closing")

    def user_floor_end(self, queued: datetime, started: datetime) -> tuple[datetime, list[str]] | None:
        """When the user held the floor at `queued` (an onset not closed yet), the closing fact that released it.

        Only a release at or before `started` counts: the scheduler waiting for the user is not queue latency.
        """
        segment = segment_of(self.segments, queued)
        timeline = [entry for entry in self.activity_timeline()
                    if segment is None or segment.start <= entry[0] <= segment.end]
        before = [entry for entry in timeline if entry[0] <= queued]
        last_onset = max((index for index, entry in enumerate(before) if entry[1] == "onset"), default=None)
        if last_onset is None or any(entry[1] == "closing" for entry in before[last_onset + 1:]):
            return None
        release = next((entry for entry in timeline if queued < entry[0] <= started and entry[1] == "closing"), None)
        return None if release is None else (release[0], [release[2]])

    def previous_output_end(self, queued: datetime, started: datetime, speech_id: str,
                            speech: Sequence[Mapping[str, Any]],
                            playback: Sequence[Mapping[str, Any]]) -> tuple[datetime, list[str]] | None:
        """End of the latest other output still live after `queued` and ended by `started`, in the same segment.

        The voice output is serial: a speech queued while another one plays waits
        for it, and that wait is not queueing latency.
        """
        segment = segment_of(self.segments, started)
        best: tuple[datetime, list[str]] | None = None
        candidates = [(item["started_at"], item["ended_at"], item["speech_id"], item["terminals"][:1] or None,
                       item["evidence"]) for item in speech]
        candidates += [(item["started_at"], item["ended_at"], item["speech_id"], None, item["evidence"])
                       for item in playback]
        for begin, end, other_id, terminal, evidence in candidates:
            if begin is None or end is None or other_id == speech_id:
                continue
            begin_at, end_at = _wire_time(begin), _wire_time(end)
            if not (begin_at < started and queued < end_at <= started) or segment_of(self.segments, end_at) != segment:
                continue
            if best is None or end_at > best[0]:
                refs = list(terminal[0]["evidence"]) if terminal else list(evidence)
                best = (end_at, refs[:MAX_EVIDENCE_REFS])
        return best

    def latency_items(self, speech: Sequence[Mapping[str, Any]], outputs: Mapping[str, Mapping[str, Any]],
                      playback: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        user_turns: dict[str, tuple[datetime, list[str]]] = {}
        accepted: dict[str, _Times] = {}
        for item_id, item in self.turns.items():
            correlation = item["correlation_id"]
            if correlation is None:
                continue
            if item["kind"] == TurnKind.USER_TURN.value:
                user_turns[correlation] = (self.turn_times[item_id], self.turn_evidence[item_id].emit())
            elif item["kind"] == TurnKind.TURN_ACCEPTED.value:
                accepted.setdefault(correlation, _Times()).note(self.turn_times[item_id],
                                                                self.turn_evidence[item_id].emit()[0])
        reported: dict[str, list[dict[str, Any]]] = {}
        for line in self.lines:
            if not line.kind.startswith(_REPORTED_LATENCY_PREFIX):
                continue
            data = line.data
            if line.kind == "voice.latency.brain_turn_accepted" and _id(data.get("correlation_id")):
                accepted.setdefault(data["correlation_id"], _Times()).note(line.ts, self.ref(line))
            elapsed, speech_id = _number(data.get("elapsed_ms")), _id(data.get("speech_id"))
            if elapsed is None or speech_id is None:
                continue
            measure = _code(data.get("measure")) or line.kind.removeprefix(_REPORTED_LATENCY_PREFIX)
            reported.setdefault(speech_id, []).append({"measure": measure, "ms": elapsed,
                                                       "evidence": [self.ref(line)]})
        by_id = {record.speech_id: record for record in self.speech.values()}
        items = []
        for entry in speech:
            if entry["outcome"] == SpeechOutcome.CHUNKED.value:
                continue
            record = by_id[entry["speech_id"]]
            stages: dict[str, tuple[datetime, list[str]]] = {}

            def put(stage: str, at: datetime | None, refs: Sequence[str]) -> None:
                if at is not None and refs:
                    stages[stage] = (at, list(refs))

            correlation = entry["correlation_id"]
            if correlation in user_turns:
                put("user_turn_end", *user_turns[correlation])
            if correlation in accepted:
                put("brain_turn_accepted", accepted[correlation].at, accepted[correlation].evidence.emit())
            requested = record.stages["requested"]
            if requested.at is None and record.parent_speech_id in by_id:
                requested = by_id[record.parent_speech_id].stages["requested"]  # type: ignore[index]
            put("speech_requested", requested.at, requested.evidence.emit())
            for stage, name in (("speech_queued", "queued"), ("speech_dispatched", "dispatched"),
                                ("speech_started", "started")):
                put(stage, record.stages[name].at, record.stages[name].evidence.emit())
            if "speech_queued" in stages and "speech_started" in stages:
                waits = [wait for wait in (
                    self.previous_output_end(stages["speech_queued"][0], stages["speech_started"][0],
                                             record.speech_id, speech, playback),
                    self.user_floor_end(stages["speech_queued"][0], stages["speech_started"][0])) if wait is not None]
                if waits:
                    put("speech_queue_free", *max(waits, key=lambda wait: (wait[0], wait[1])))
                else:
                    put("speech_queue_free", *stages["speech_queued"])
            chunk, write = _Times(), _Times()
            for output_id in sorted(record.output_ids):
                output = outputs.get(output_id)
                if output is None:
                    continue
                for source, target in ((output["chunk"], chunk), (output["write"], write)):
                    if source.at is not None:
                        for ref in source.evidence.emit():
                            target.note(source.at, ref)
            put("provider_first_pcm", chunk.at, chunk.evidence.emit())
            put("first_audio", write.at, write.evidence.emit())
            first = record.first_terminal()
            if first is not None:
                put("speech_ended", first[1].at, first[1].evidence.emit())
            measures = [{"name": name, "ms": _ms(stages[target][0] - stages[source][0]), "from_stage": source,
                         "to_stage": target}
                        for name, source, target in LATENCY_MEASURES if source in stages and target in stages]
            joined_reported = sorted(reported.get(record.speech_id, []),
                                     key=lambda item: (item["evidence"][0], item["measure"]))[:32]
            if len(stages) < 2 and not joined_reported:
                continue
            items.append({
                "join_id": f"speech:{record.speech_id}", "speech_id": record.speech_id,
                "correlation_id": correlation,
                "stages": [{"stage": stage, "at": format_time(stages[stage][0]),
                            "evidence": stages[stage][1][:MAX_EVIDENCE_REFS]}
                           for stage in LATENCY_STAGES if stage in stages],
                "measures": measures, "reported": joined_reported,
            })
        # A turn's first audio is measured once, on the join that produced it (earliest first audio).
        first_by_turn: dict[str, tuple[str, str]] = {}
        for item in items:
            audio = next((stage["at"] for stage in item["stages"] if stage["stage"] == "first_audio"), None)
            if item["correlation_id"] is not None and audio is not None:
                key = (audio, item["join_id"])
                if item["correlation_id"] not in first_by_turn or key < first_by_turn[item["correlation_id"]]:
                    first_by_turn[item["correlation_id"]] = key
        for item in items:
            first = first_by_turn.get(item["correlation_id"])
            if first is None or first[1] != item["join_id"]:
                item["measures"] = [measure for measure in item["measures"]
                                    if measure["name"] != "user_turn_end_to_first_audio_ms"]
        items.sort(key=lambda item: ((item["stages"][0]["at"] if item["stages"] else ""), item["join_id"]))
        return self._cap("latency", items)

    def turn_items(self, speech: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        outcomes = {item["speech_id"]: item["outcome"] for item in speech}
        items = []
        for item_id, item in self.turns.items():
            if item["kind"] == TurnKind.SPEECH.value and item["status"] is None:
                item["status"] = outcomes.get(item["speech_id"])
            items.append({**item, "at": format_time(self.turn_times[item_id]),
                          "evidence": self.turn_evidence[item_id].emit()})
        items.sort(key=lambda entry: (entry["at"], entry["item_id"]))
        return self._cap("turns", items)

    def identity(self) -> dict[str, Any]:
        configurations: set[str] = set()
        architectures: set[str] = set()
        evidence = _Evidence()
        for line in self.lines:
            if line.kind not in _IDENTITY_KINDS:
                continue
            configuration, architecture = line.data.get("configuration_id"), _code(line.data.get("arch"))
            found = False
            if isinstance(configuration, str) and _HEX64.fullmatch(configuration):
                configurations.add(configuration)
                found = True
            if architecture is not None:
                architectures.add(architecture)
                found = True
            if found:
                evidence.add(self.ref(line))
        for report in self.report_list:
            if report.configuration_id is not None:
                configurations.add(report.configuration_id)
            if report.architecture is not None:
                architectures.add(report.architecture)
            if report.configuration_id is not None or report.architecture is not None:
                evidence.add(report_ref(report.sha256))
        refs = evidence.emit()
        return {"status": "evidence" if refs else "unknown", "voice_configuration_ids": sorted(configurations)[:16],
                "architectures": sorted(architectures)[:16], "evidence": refs}

    def reports(self) -> list[dict[str, Any]]:
        items = []
        for report in self.report_list:
            items.append({
                "session_id": report.session_id, "architecture": report.architecture,
                "configuration_id": report.configuration_id, "session_fingerprint": report.session_fingerprint,
                "terminal_status": report.terminal_status, "trace_evidence_complete": report.trace_evidence_complete,
                "latency": [{"name": name, "count": count, "min_ms": low, "max_ms": high, "mean_ms": mean}
                            for name, count, low, high, mean in report.latency[:32]],
                "counts": [{"name": name, "value": value} for name, value in report.counts[:32]],
                "evidence": [report_ref(report.sha256)],
            })
        return items

    def summary_entries(self) -> list[dict[str, Any]] | None:
        if self.trace_summary is None:
            return None
        entries: list[dict[str, Any]] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, Mapping):
                for key in value:
                    segment = "".join(char if char.isascii() and (char.isalnum() or char in "_./-") else "_"
                                      for char in str(key).lower())
                    walk(value[key], f"{path}.{segment}" if path else segment)
            elif isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    walk(item, f"{path}.{index}")
            elif value is None or type(value) is bool or (type(value) in (int, float) and value == value
                                                           and abs(value) <= MAX_JSON_INT):
                entries.append({"path": path[:160], "value": value})
            elif isinstance(value, str) and 0 < len(value) <= 128 and value.isprintable():
                entries.append({"path": path[:160], "value": value})

        walk(self.trace_summary, "")
        entries = [entry for entry in entries if entry["path"]]
        entries.sort(key=lambda entry: entry["path"])
        unique: dict[str, dict[str, Any]] = {}
        for entry in entries:
            unique.setdefault(entry["path"], entry)
        return list(unique.values())[:_MAX_SUMMARY_ENTRIES]

    # ----------------------------------------------------------- segments

    def build_segments(self) -> None:
        """Split the evidence into voice session segments (docs/testlab.md, "Voice session segments").

        Items in time order; a new segment starts when the previous one was closed
        by a session end kind, when an item carries another `session_id` than the
        segment's, when a session start kind follows any other evidence, or after
        an idle gap longer than `SEGMENT_IDLE_GAP_MS` before an item that does not belong to the segment's
        known `session_id` (an item carrying it, an unidentified item whose next identified item carries it,
        or an unidentified session end kind all belong to it: a long silence inside one identified session
        stays one segment). Consecutive session end kinds (one shutdown
        sequence) close the same segment.
        """
        items = sorted([(stored.event.occurred_at, 0, stored.event.event_id, stored.event.session_id, None)
                        for stored in self.events]
                       + [(line.ts, 1, f"{line.offset:015d}", _id(line.data.get("session_id")), line.kind)
                          for line in self.lines], key=lambda item: item[:3])
        gap = timedelta(milliseconds=SEGMENT_IDLE_GAP_MS)
        rows: list[dict[str, Any]] = []
        #: For each item, the session id of the first identified item at or after it (look-ahead).
        next_session: list[str | None] = [None] * len(items)
        upcoming: str | None = None
        for index in range(len(items) - 1, -1, -1):
            upcoming = items[index][3] if items[index][3] is not None else upcoming
            next_session[index] = upcoming
        for position, (at, _, _, session_id, kind) in enumerate(items):
            current = rows[-1] if rows else None
            closing_sequence = (current is not None and current["end_kind"] is not None and kind in SEGMENT_END_KINDS
                                and at - current["end"] <= gap)
            if closing_sequence:
                # `audio.device_closed`, `voice.failure`, `voice.stop` of one shutdown close one segment.
                current["end"], current["end_kind"] = at, kind
                current["items"] += 1
                continue
            same_session = session_id is not None and session_id == current["session_id"] if current else False
            if (current is not None and kind in SEGMENT_END_KINDS and session_id is None
                    and current["end_kind"] is None and current["session_id"] is not None):
                # A data-less session end (`voice.stop` carries no ids) closes the identified session it
                # follows, however long that session stayed silent: a hung speech stays decidable.
                same_session = True
            if (current is not None and session_id is None and current["session_id"] is not None
                    and next_session[position] == current["session_id"]):
                # An unidentified line (`voice.speech_started` carries no session id) followed by lines of the
                # same identified session belongs to it: the silence before it is inside the session.
                same_session = True
            if (current is None or current["end_kind"] is not None or (at - current["end"] > gap and not same_session)
                    or (session_id is not None and current["session_id"] is not None
                        and session_id != current["session_id"])
                    or (kind in SEGMENT_START_KINDS and current["has_body"])):
                current = {"start": at, "end": at, "session_id": None, "end_kind": None, "items": 0,
                           "has_body": False}
                rows.append(current)
            current["end"] = at
            current["items"] += 1
            current["session_id"] = current["session_id"] or session_id
            if kind not in SEGMENT_START_KINDS:
                current["has_body"] = True
            if kind in SEGMENT_END_KINDS:
                current["end_kind"] = kind
        self.segments = [Segment(row["start"], row["end"], row["end_kind"]) for row in rows]
        self.segment_rows = [{"index": index, "session_id": row["session_id"], "started_at": format_time(row["start"]),
                              "ended_at": format_time(row["end"]), "end_kind": row["end_kind"], "items": row["items"]}
                             for index, row in enumerate(rows)]

    def failures(self, provider: Sequence[Mapping[str, Any]]) -> list[tuple[datetime, str, tuple[str, ...]]]:
        facts = [(_wire_time(item["at"]), item["event"], tuple(item["evidence"]))
                 for item in (*self.lifecycle, *provider) if item["event"] in FAILURE_CAUSES]
        return sorted(facts, key=lambda fact: (fact[0], fact[1], fact[2]))

    def warnings(self, started: datetime | None, ended: datetime | None) -> list[str]:
        warnings: set[str] = set()
        if self.selector.start is None and self.selector.end is None:
            if len(self.segments) > 1:
                warnings.add(CoverageWarning.MULTI_SESSION_SELECTION.value)
            if started is not None and ended - started > timedelta(hours=MAX_SELECTION_HOURS):
                warnings.add(CoverageWarning.LONG_SELECTION.value)
        if self.window_open():
            warnings.add(CoverageWarning.OPEN_WINDOW.value)
        if self.trace_evidence.torn_tail:
            warnings.add(CoverageWarning.TORN_TAIL.value)
        return sorted(warnings)

    def window_open(self) -> bool:
        return self.trace_evidence.window_open or (self.selector.end is not None
                                                  and self.selector.end > self.context.captured_at)

    # ----------------------------------------------------------- document

    def build(self) -> DiagnosticBundle:
        self.derive_events()
        self.derive_trace()
        self.build_segments()
        speech = self.speech_items()
        playback, outputs = self.playback_items()
        moments = [stored.event.occurred_at for stored in self.events] + [line.ts for line in self.lines]
        evidence_end = max(moments) if moments else None
        started = min(moments) if moments else None
        turns = self.turn_items(speech)
        barge_in = self.barge_in_items(speech, playback)
        provider = self.provider_items()
        latency = self.latency_items(speech, outputs, playback)
        identity = self.identity()
        reports = self.reports()
        read_sources = frozenset(name for name, status in ((SOURCE_CONVERSATION_EVENTS, self.events_evidence.status),
                                                           (SOURCE_RUNTIME_JOURNAL, self.trace_evidence.status))
                                 if status in READ_STATUSES)
        reconstruction = []
        by_conversation: dict[str, list[ConversationEvent]] = {}
        for stored in self.events:
            by_conversation.setdefault(stored.event.conversation_id, []).append(stored.event)
        for conversation_id in sorted(by_conversation):
            for item in reconstruct_conversation(by_conversation[conversation_id]):
                for anomaly in item.anomalies:
                    code, _, event_id = anomaly.partition(":")
                    reconstruction.append((item.item_id, item.started_at, code, event_id))
        payloads = {}
        for record in self.speech.values():
            text = record.payload or record.request_payload
            if text:
                payloads[record.speech_id] = normalize_payload(text)
        rule_rows, findings = evaluate_rules(self.options.rules, RuleContext(
            turns=turns, speech=speech, barge_in=barge_in, latency=latency, speech_payloads=payloads,
            reconstruction=reconstruction, segments=self.segments, failures=self.failures(provider),
            read_sources=read_sources))
        findings = self._cap("findings", findings)
        conversation_ids = {stored.event.conversation_id for stored in self.events}
        session_ids = {stored.event.session_id for stored in self.events if stored.event.session_id is not None}
        for line in self.lines:
            if line.matched:
                if _id(line.data.get("conversation_id")):
                    conversation_ids.add(line.data["conversation_id"])
                if _id(line.data.get("session_id")):
                    session_ids.add(line.data["session_id"])
        if len(conversation_ids) > MAX_IDS or len(session_ids) > MAX_IDS:
            self.limits.append({"section": "session_ids", "kept": MAX_IDS,
                                "dropped": max(len(conversation_ids), len(session_ids)) - MAX_IDS})
        events_cov, trace_cov = self.events_evidence, self.trace_evidence
        document: dict[str, Any] = {
            "schema": DIAGNOSTIC_BUNDLE_SCHEMA,
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_id": "",
            "content_fingerprint": "",
            "capture": {
                "captured_at": format_time(self.context.captured_at),
                "code": {"status": "capture_time" if self.context.code is not None else "unknown",
                         "git_revision": self.context.code.git_revision if self.context.code else None,
                         "dirty": self.context.code.dirty if self.context.code else None},
                "config": {"status": "capture_time" if self.context.config_fingerprint else "unknown",
                           "fingerprint": self.context.config_fingerprint},
            },
            "session": {
                "selector": self.selector.to_dict(), "conversation_ids": sorted(conversation_ids)[:MAX_IDS],
                "session_ids": sorted(session_ids)[:MAX_IDS], "started_at": format_time(started),
                "ended_at": format_time(evidence_end),
                "duration_ms": None if started is None else _ms(evidence_end - started),
            },
            "identity": identity,
            "coverage": {
                "conversation_events": {"status": events_cov.status.value, "origin": events_cov.origin,
                                        "events": len(self.events), "skipped_rows": events_cov.skipped_rows,
                                        "export_complete": events_cov.export_complete,
                                        "truncated": events_cov.truncated, "reason": events_cov.reason},
                "runtime_journal": {"status": trace_cov.status.value, "lines_in_window": trace_cov.lines_in_window,
                                    "lines_selected": len(self.lines), "corrupt_lines": trace_cov.corrupt_lines,
                                    "oversized_lines": trace_cov.oversized_lines,
                                    "untimed_lines": trace_cov.untimed_lines, "truncated": trace_cov.truncated,
                                    "start_truncated": trace_cov.start_truncated, "torn_tail": trace_cov.torn_tail,
                                    "window_open": self.window_open(), "stopped_by": trace_cov.stopped_by,
                                    "reason": trace_cov.reason},
                "voice_session_reports": {"status": self.report_evidence.status.value,
                                          "reports": len(self.report_list),
                                          "reason": self.report_evidence.reason},
                "content": {"included": self.options.include_public_content,
                            "max_chars": self.options.max_content_chars, "items": self.content_items,
                            "truncated_items": self.truncated_items, "redactions": self.redactions},
                "limits": self.limits,
                "segments": {"count": len(self.segment_rows), "idle_gap_ms": SEGMENT_IDLE_GAP_MS,
                             "dropped": max(0, len(self.segment_rows) - SECTION_LIMITS["segments"]),
                             "items": self.segment_rows[:SECTION_LIMITS["segments"]]},
                "warnings": self.warnings(started, evidence_end),
            },
            "turns": turns,
            "speech": speech,
            "playback": playback,
            "barge_in": barge_in,
            "provider": provider,
            "user_activity": self._cap("user_activity", _by_time(self.user_activity)),
            "lifecycle": self._cap("lifecycle", _by_time(self.lifecycle)),
            "brain": self._cap("brain", _by_time(self.brain)),
            "usage": self._cap("usage", _by_time(self.usage)),
            "latency": latency,
            "aggregates": {"trace_summary": self.summary_entries(), "voice_session_reports": reports},
            "anomalies": {"rules": rule_rows, "findings": findings},
            "references": {
                "conversation_events": [{"ref": stored.event.event_id, "sequence": stored.sequence,
                                         "event_type": stored.event.event_type.value,
                                         "occurred_at": format_time(stored.event.occurred_at),
                                         "visibility": stored.event.visibility.value}
                                        for stored in sorted(self.events, key=lambda item: (item.sequence,
                                                                                            item.event.event_id))],
                "trace_lines": [{"ref": trace_ref(offset), "offset": offset, "ts": format_time(line.ts),
                                 "kind": line.kind, "level": _code(line.level)}
                                for offset, line in sorted(self.used_lines.items())],
                "voice_session_reports": [{"ref": report_ref(report.sha256), "sha256": report.sha256}
                                          for report in self.report_list],
            },
        }
        fingerprint = bundle_content_fingerprint(document)
        document["content_fingerprint"] = fingerprint
        document["bundle_id"] = derive_bundle_id(document, fingerprint)
        return DiagnosticBundle.from_dict(document)


def build_diagnostic_bundle(selector: SessionSelector, *, context: CaptureContext,
                            events: EventEvidence = NOT_REQUESTED_EVENTS, trace: TraceEvidence = NOT_REQUESTED_TRACE,
                            reports: ReportEvidence = NOT_REQUESTED_REPORTS,
                            trace_summary: Mapping[str, Any] | None = None,
                            options: BundleOptions = BundleOptions()) -> DiagnosticBundle:
    """Derive the validated `DiagnosticBundle` of a selected session. Same inputs, byte-identical bundle."""
    if not isinstance(selector, SessionSelector) or not isinstance(context, CaptureContext):
        raise fail("build_diagnostic_bundle takes a SessionSelector and a CaptureContext")
    for value, kind in ((events, EventEvidence), (trace, TraceEvidence), (reports, ReportEvidence),
                        (options, BundleOptions)):
        if not isinstance(value, kind):
            raise fail(f"build_diagnostic_bundle expects {kind.__name__}")
    return _Builder(selector, context, events, trace, reports, trace_summary, options).build()
