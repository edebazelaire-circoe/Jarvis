"""Optional analysis values. Identity and validity belong to the application.

Requests/results are process-local immutable envelopes, not durable authority.
Only the hint VALUE crosses a model JSON boundary. It contains no speech text,
tools, executable plan, owner proof or hidden reasoning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import math

from jarvis.domain.reflex_policy import ReflexAction
from jarvis.domain.speech_presentation import SpeechSource, speech_id
from jarvis.domain.v2 import SpeechPriority
from jarvis.domain.voice_frontend import VoiceContext, VoiceContextRole
from jarvis.domain.voice_state import VoiceUserRecord

HINT_SCHEMA_VERSION = 1
MAX_HINT_INPUT = 8192
MAX_HINT_HISTORY_MESSAGES = 8
MAX_HINT_REQUEST_TEXT = 16384
MAX_HINT_HYPOTHESIS = 512
MAX_HINT_JSON_BYTES = 8192


def monotonic_ns(value: object) -> None:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("hint monotonic time must be a bounded nonnegative integer")


def _version(value: object) -> None:
    if type(value) is not int or value != HINT_SCHEMA_VERSION:
        raise ValueError("unsupported hint schema version")


@dataclass(frozen=True, slots=True)
class FrontBrainHintRequest:
    request_id: str
    input: VoiceUserRecord
    origin_source: SpeechSource | None
    context_source: SpeechSource | None
    context: VoiceContext
    analysis_admission_id: str
    configuration_id: str
    deadline_monotonic_ns: int
    schema_version: int = HINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version)
        for name in ("request_id", "analysis_admission_id", "configuration_id"):
            speech_id(getattr(self, name), name)
        monotonic_ns(self.deadline_monotonic_ns)
        if not isinstance(self.input, VoiceUserRecord) or not isinstance(self.context, VoiceContext):
            raise ValueError("hint input and selected context must be typed")
        if not self.input.text.strip() or len(self.input.text) > MAX_HINT_INPUT:
            raise ValueError("hint input text exceeds bounds or is empty")
        if len(self.context.messages) > MAX_HINT_HISTORY_MESSAGES or len(self.input.text) + sum(len(message.text) for message in self.context.messages) > MAX_HINT_REQUEST_TEXT:
            raise ValueError("hint selected context exceeds aggregate bounds")
        if any(not isinstance(message.role, VoiceContextRole) for message in self.context.messages):
            raise ValueError("hint context roles must be typed USER, ASSISTANT or DEVELOPER")
        for source in (self.origin_source, self.context_source):
            if source is not None and not isinstance(source, SpeechSource):
                raise ValueError("hint sources must be typed or unknown")
        # These are the same correlation namespace when explicitly linked.
        # Never compare Core turn IDs with canonical voice turn IDs.
        linked = self.input.correlation.source_correlation_id
        if self.origin_source is not None and linked is not None and linked != self.origin_source.correlation_id:
            raise ValueError("hint origin disagrees with the explicit source correlation")


@dataclass(frozen=True, slots=True)
class FrontBrainHintValue:
    suggested_action: ReflexAction | None = None
    intent_hypothesis: str | None = field(default=None, repr=False)
    addressed_confidence: float | None = None
    confidence: float | None = None
    likely_backend_needed: bool | None = None
    urgency: SpeechPriority | None = None

    def __post_init__(self) -> None:
        if self.suggested_action is not None and not isinstance(self.suggested_action, ReflexAction):
            raise ValueError("hint action must be typed or unknown")
        if self.intent_hypothesis is not None and (not isinstance(self.intent_hypothesis, str) or len(self.intent_hypothesis) > MAX_HINT_HYPOTHESIS):
            raise ValueError("hint hypothesis exceeds text bounds")
        for value in (self.addressed_confidence, self.confidence):
            if value is not None and (type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value)):
                raise ValueError("hint confidence must be finite and between zero and one")
        if self.likely_backend_needed is not None and type(self.likely_backend_needed) is not bool:
            raise ValueError("hint backend need must be boolean or unknown")
        if self.urgency is not None and not isinstance(self.urgency, SpeechPriority):
            raise ValueError("hint urgency must be typed or unknown")

    def to_payload(self) -> dict:
        return {"schema_version": HINT_SCHEMA_VERSION,
                "suggested_action": self.suggested_action.value if self.suggested_action else None,
                "intent_hypothesis": self.intent_hypothesis,
                "addressed_confidence": self.addressed_confidence, "confidence": self.confidence,
                "likely_backend_needed": self.likely_backend_needed,
                "urgency": self.urgency.label if self.urgency is not None else None}

    @classmethod
    def from_payload(cls, payload: object) -> FrontBrainHintValue:
        keys = {"schema_version", "suggested_action", "intent_hypothesis", "addressed_confidence",
                "confidence", "likely_backend_needed", "urgency"}
        if not isinstance(payload, dict) or set(payload) != keys:
            raise ValueError("invalid hint value fields")
        _version(payload["schema_version"])
        action, urgency = payload["suggested_action"], payload["urgency"]
        if action is not None and (not isinstance(action, str) or action not in {item.value for item in ReflexAction}):
            raise ValueError("unknown hint action")
        if urgency is not None and (not isinstance(urgency, str) or urgency not in {item.label for item in SpeechPriority}):
            raise ValueError("unknown hint urgency")
        return cls(suggested_action=ReflexAction(action) if action is not None else None,
                   intent_hypothesis=payload["intent_hypothesis"], addressed_confidence=payload["addressed_confidence"],
                   confidence=payload["confidence"], likely_backend_needed=payload["likely_backend_needed"],
                   urgency=SpeechPriority.from_label(urgency) if urgency is not None else None)


def encode_front_brain_hint(value: FrontBrainHintValue) -> dict:
    if not isinstance(value, FrontBrainHintValue):
        raise ValueError("hint value must be typed")
    return value.to_payload()


def decode_front_brain_hint(raw_json: str) -> FrontBrainHintValue:
    """Reject duplicate keys and nonfinite JSON before value validation."""
    if not isinstance(raw_json, str) or len(raw_json) > MAX_HINT_JSON_BYTES:
        raise ValueError("hint JSON exceeds bounds")
    try:
        if len(raw_json.encode("utf-8")) > MAX_HINT_JSON_BYTES:
            raise ValueError("hint JSON exceeds byte bounds")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate hint JSON key")
                result[key] = value
            return result
        def finite_float(value):
            parsed = float(value)
            if not math.isfinite(parsed):
                raise ValueError("nonfinite hint JSON number")
            return parsed
        def invalid_constant(_value):
            raise ValueError("nonfinite hint JSON constant")
        parsed = json.loads(raw_json, object_pairs_hook=pairs, parse_float=finite_float, parse_constant=invalid_constant)
        return FrontBrainHintValue.from_payload(parsed)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid hint JSON encoding or nesting") from exc


class HintAnalysisStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REFUSED = "refused"
    TIMED_OUT = "timed_out"
    INVALID_OUTPUT = "invalid_output"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True, slots=True)
class FrontBrainHintResult:
    request_id: str
    status: HintAnalysisStatus
    value: FrontBrainHintValue | None
    received_monotonic_ns: int
    schema_version: int = HINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version)
        speech_id(self.request_id, "request_id")
        monotonic_ns(self.received_monotonic_ns)
        if not isinstance(self.status, HintAnalysisStatus):
            raise ValueError("hint outcome status must be typed")
        if self.status is HintAnalysisStatus.AVAILABLE:
            if not isinstance(self.value, FrontBrainHintValue):
                raise ValueError("available hint requires a typed value")
        elif self.value is not None:
            raise ValueError("unavailable hint cannot carry a suggested value")
