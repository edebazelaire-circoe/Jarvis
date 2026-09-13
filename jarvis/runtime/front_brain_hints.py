"""Consume optional hints without dispatching, speaking or mutating Core state."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.domain.front_brain_hints import (
    FrontBrainHintRequest, FrontBrainHintResult, FrontBrainHintValue, HintAnalysisStatus, monotonic_ns,
)
from jarvis.domain.reflex_policy import ReflexAction
from jarvis.domain.speech_presentation import SpeechDependency, SpeechSource, speech_id
from jarvis.domain.voice_state import VoiceUserRecord
from jarvis.ports.v2 import DiagnosticSink


class HintConsumptionDisposition(StrEnum):
    ACCEPTED = "accepted"
    NO_SUGGESTION = "no_suggestion"
    IGNORED = "ignored"


class HintIgnoreReason(StrEnum):
    ACCEPTED = "accepted"
    NO_SUGGESTION = "no_suggestion"
    NO_REQUEST = "no_request"
    REQUEST_MISMATCH = "request_mismatch"
    DUPLICATE = "duplicate"
    EXPIRED = "expired"
    SESSION_CHANGED = "session_changed"
    INPUT_CHANGED = "input_changed"
    ORIGIN_CHANGED = "origin_changed"
    CONTEXT_CHANGED = "context_changed"
    CONFIGURATION_CHANGED = "configuration_changed"
    ADMISSION_REVOKED = "admission_revoked"
    DEPENDENCY_REVOKED = "dependency_revoked"
    SOURCE_INCOMPLETE = "source_incomplete"
    ANALYSIS_UNAVAILABLE = "analysis_unavailable"
    USEFUL_CONTENT_READY = "useful_content_ready"


@dataclass(frozen=True, slots=True)
class HintConsumption:
    disposition: HintConsumptionDisposition
    reason: HintIgnoreReason
    value: FrontBrainHintValue | None
    analysis_status: HintAnalysisStatus


class FrontBrainHintConsumer:
    """One expected request and one consumed flag; no queue, worker or authority.

    Task10's request factory owns globally fresh request IDs. Re-registering the
    same live ID cannot alter its binding/deadline or rearm its consumed result.
    A wrong-ID reply never changes the newer expectation. The caller supplies
    current evidence and a local monotonic clock at the point of consumption.
    """
    def __init__(self, diagnostics: DiagnosticSink | None = None) -> None:
        self._diagnostics = diagnostics
        self._expected: FrontBrainHintRequest | None = None
        self._consumed = False

    @property
    def expected_request_id(self) -> str | None:
        return self._expected.request_id if self._expected else None

    def expect(self, request: FrontBrainHintRequest) -> bool:
        if not isinstance(request, FrontBrainHintRequest):
            raise ValueError("expected hint request must be typed")
        if self._expected is not None and self._expected.request_id == request.request_id:
            if self._expected != request:
                raise ValueError("hint request identity cannot change binding or deadline")
            return False
        self._expected = request
        self._consumed = False
        self._trace("voice.hint.expected", request.request_id, "expected")
        return True

    def invalidate(self, reason: HintIgnoreReason = HintIgnoreReason.INPUT_CHANGED) -> None:
        if not isinstance(reason, HintIgnoreReason):
            raise ValueError("hint invalidation reason must be typed")
        if self._expected is not None:
            # Retain the single request identity so a duplicate registration
            # cannot resurrect it. A genuinely new request replaces this slot.
            self._consumed = True
            self._trace("voice.hint.invalidated", self._expected.request_id, reason.value)

    def consume(self, result: FrontBrainHintResult, *, current_input: VoiceUserRecord,
                current_origin_source: SpeechSource | None, current_context_source: SpeechSource | None,
                current_configuration_id: str, current_admission_id: str | None,
                source_complete: bool, invalidated_dependencies: tuple[SpeechDependency, ...],
                now_monotonic_ns: int, useful_ready: bool = False) -> HintConsumption:
        if not isinstance(result, FrontBrainHintResult) or not isinstance(current_input, VoiceUserRecord):
            raise ValueError("hint result and current input must be typed")
        monotonic_ns(now_monotonic_ns)
        speech_id(current_configuration_id, "configuration_id")
        speech_id(current_admission_id, "analysis_admission_id", optional=True)
        if type(source_complete) is not bool or type(useful_ready) is not bool:
            raise ValueError("hint current-state flags must be boolean")
        if not isinstance(invalidated_dependencies, tuple) or len(invalidated_dependencies) > 256 or any(not isinstance(item, SpeechDependency) for item in invalidated_dependencies):
            raise ValueError("hint invalidated dependencies must be a bounded typed tuple")
        for source in (current_origin_source, current_context_source):
            if source is not None and not isinstance(source, SpeechSource):
                raise ValueError("hint current sources must be typed or unknown")

        request = self._expected
        if request is None:
            return self._ignored(result, HintIgnoreReason.NO_REQUEST)
        if result.request_id != request.request_id:
            return self._ignored(result, HintIgnoreReason.REQUEST_MISMATCH)
        if self._consumed:
            return self._ignored(result, HintIgnoreReason.DUPLICATE)
        self._consumed = True

        # received_at is evidence only: a result received before expiry may
        # have waited too long before reaching this deterministic consumer.
        if now_monotonic_ns >= request.deadline_monotonic_ns or result.received_monotonic_ns >= request.deadline_monotonic_ns:
            return self._ignored(result, HintIgnoreReason.EXPIRED)
        if current_input.correlation.session_id != request.input.correlation.session_id:
            return self._ignored(result, HintIgnoreReason.SESSION_CHANGED)
        if current_input != request.input:
            return self._ignored(result, HintIgnoreReason.INPUT_CHANGED)
        if current_configuration_id != request.configuration_id:
            return self._ignored(result, HintIgnoreReason.CONFIGURATION_CHANGED)
        if current_admission_id != request.analysis_admission_id:
            return self._ignored(result, HintIgnoreReason.ADMISSION_REVOKED)
        if not source_complete:
            return self._ignored(result, HintIgnoreReason.SOURCE_INCOMPLETE)
        if current_origin_source != request.origin_source:
            return self._ignored(result, HintIgnoreReason.ORIGIN_CHANGED)
        if current_context_source != request.context_source:
            return self._ignored(result, HintIgnoreReason.CONTEXT_CHANGED)
        dependencies = tuple(dependency for source in (request.origin_source, request.context_source)
                             if source is not None for dependency in source.dependencies)
        if any(dependency in invalidated_dependencies for dependency in dependencies):
            return self._ignored(result, HintIgnoreReason.DEPENDENCY_REVOKED)
        if result.status is not HintAnalysisStatus.AVAILABLE:
            return self._ignored(result, HintIgnoreReason.ANALYSIS_UNAVAILABLE)
        value = result.value
        if useful_ready and value.suggested_action in (ReflexAction.WAIT, ReflexAction.BACKCHANNEL, ReflexAction.PREAMBLE):
            return self._ignored(result, HintIgnoreReason.USEFUL_CONTENT_READY)
        disposition = HintConsumptionDisposition.ACCEPTED if value.suggested_action is not None else HintConsumptionDisposition.NO_SUGGESTION
        reason = HintIgnoreReason.ACCEPTED if value.suggested_action is not None else HintIgnoreReason.NO_SUGGESTION
        self._trace("voice.hint.consumed", result.request_id, reason.value, result)
        return HintConsumption(disposition, reason, value, result.status)

    def _ignored(self, result: FrontBrainHintResult, reason: HintIgnoreReason) -> HintConsumption:
        self._trace("voice.hint.ignored", result.request_id, reason.value, result)
        return HintConsumption(HintConsumptionDisposition.IGNORED, reason, None, result.status)

    def _trace(self, kind: str, request_id: str, reason: str, result: FrontBrainHintResult | None = None) -> None:
        if self._diagnostics is None:
            return
        data = {"request_id": request_id, "reason": reason}
        request = self._expected
        if request is not None and request.request_id == request_id:
            data.update(session_id=request.input.correlation.session_id, transcript_id=request.input.transcript_id,
                        transcript_revision=request.input.revision, committed=request.input.committed)
        if result is not None:
            data["analysis_status"] = result.status.value
            data["suggested_action"] = result.value.suggested_action.value if result.value and result.value.suggested_action else None
        self._diagnostics.emit(kind, "Front Brain advisory hint", data=data)
