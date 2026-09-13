"""Permanent contract fixture, not a production fallback or a provider simulator.

Only lifecycle is automatic. Tests inject every conversation event explicitly;
command acceptance never fabricates a transcript, playback, delegation or usage.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from jarvis.domain.voice_architecture import VoiceModelCapabilities
from jarvis.domain.voice_events import (
    AssistantPlaybackEvidence, FrontendLifecycleChanged, VoiceEvent,
    VoiceEventPayload, VoiceFrontendFailed,
)
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceCorrelation, VoiceErrorCode, VoiceEventId,
    VoiceFrontendConfig, VoiceFrontendError, VoiceObservation, VoiceOperation,
    VoiceOperationKind as Kind, VoiceOperationResult, VoiceOperationStatus as Status,
    VoiceSessionId, VoiceStopReason, VoiceTextUpdate,
)


class FakeVoiceFrontend:
    def __init__(
        self, *, supported: frozenset[Kind] = frozenset(Kind),
        close_confirmed: bool = True, start_gate: asyncio.Event | None = None,
        max_events: int = 256,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.state = FrontendState.NEW
        self.supported = supported
        self.capabilities = VoiceModelCapabilities(
            supports_audio_input=Kind.SEND_AUDIO in supported,
            supports_audio_output=Kind.SPOKEN_RESULT in supported,
            supports_quiet_context_injection=Kind.QUIET_CONTEXT in supported,
            supports_spoken_result_injection=Kind.SPOKEN_RESULT in supported,
            supports_prompt_update=Kind.RUNTIME_INSTRUCTION in supported,
            supports_native_interruptions=Kind.CANCEL_SPEECH in supported,
        )
        self.close_confirmed = close_confirmed
        self.start_gate = start_gate
        self.start_entered = asyncio.Event()
        self.calls: list[tuple[Kind, VoiceOperation, object]] = []
        self.config: VoiceFrontendConfig | None = None
        self._correlation = VoiceCorrelation(VoiceSessionId("unstarted-fixture"))
        self._queue: deque[VoiceEvent] = deque()
        self._changed = asyncio.Event()
        self._max_events = max_events
        self._sequence = 0
        self._closed = False
        self._reader_active = False
        self._stop_result: VoiceOperationResult | None = None

    def event(self, payload: VoiceEventPayload, *, correlation: VoiceCorrelation | None = None) -> VoiceEvent:
        """Create deterministic identity/time without a wall clock or provider."""
        self._sequence += 1
        return VoiceEvent(
            VoiceEventId(f"fixture-event-{self._sequence}"), self._sequence,
            correlation or self._correlation,
            VoiceObservation(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=self._sequence), self._sequence * 1_000_000),
            payload,
        )

    def inject(self, event: VoiceEvent) -> None:
        """Preserve even duplicate/stale IDs for downstream reducer tests."""
        if self._closed:
            raise RuntimeError("Cannot inject into a stopped event stream")
        if len(self._queue) >= self._max_events:
            raise asyncio.QueueFull
        self._queue.append(event)
        self._changed.set()

    def _lifecycle(self, state: FrontendState) -> None:
        self.state = state
        # At most five lifecycle/error events across this single-use instance.
        # Reserved control capacity lets stop wake readers even at injection cap.
        self._queue.append(self.event(FrontendLifecycleChanged(state)))
        self._changed.set()

    def _result(self, operation: VoiceOperation, kind: Kind, status: Status, code: VoiceErrorCode | None = None) -> VoiceOperationResult:
        error = VoiceFrontendError(code, kind, self.state) if code else None
        return VoiceOperationResult(operation, kind, status, self.state, error)

    async def start(self, config: VoiceFrontendConfig, *, operation: VoiceOperation) -> VoiceOperationResult:
        if self.state != FrontendState.NEW:
            return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        self.config = config
        self._correlation = operation.correlation
        self.calls.append((Kind.START, operation, config))
        self._lifecycle(FrontendState.STARTING)
        self.start_entered.set()
        try:
            if self.start_gate is not None:
                await self.start_gate.wait()
        except asyncio.CancelledError:
            # Cancellation is deliberately visible to the fixture caller; no
            # remote success is inferred while startup ownership is uncertain.
            if self.state == FrontendState.STARTING:
                self._lifecycle(FrontendState.UNKNOWN_REAP_REQUIRED)
                self._queue.append(self.event(VoiceFrontendFailed(VoiceFrontendError(
                    VoiceErrorCode.CANCELLED, Kind.START, self.state,
                ))))
                self._changed.set()
            raise
        if self.state != FrontendState.STARTING:
            return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        self._lifecycle(FrontendState.ACTIVE)
        return self._result(operation, Kind.START, Status.COMPLETED)

    async def stop(self, reason: VoiceStopReason, *, operation: VoiceOperation) -> VoiceOperationResult:
        if operation.correlation.session_id != self._correlation.session_id and self.state != FrontendState.NEW:
            return self._result(operation, Kind.STOP, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        if self._stop_result is not None:
            return replace(self._stop_result, operation=operation)
        never_started = self.state == FrontendState.NEW
        if never_started:
            self._correlation = operation.correlation
        self.calls.append((Kind.STOP, operation, reason))
        self._lifecycle(FrontendState.STOPPING)
        if self.close_confirmed or never_started:
            self._lifecycle(FrontendState.STOPPED)
            self._stop_result = self._result(operation, Kind.STOP, Status.COMPLETED)
        else:
            self._lifecycle(FrontendState.UNKNOWN_REAP_REQUIRED)
            self._stop_result = self._result(operation, Kind.STOP, Status.UNKNOWN, VoiceErrorCode.CLOSE_UNCONFIRMED)
        self._closed = True
        self._changed.set()
        if self.start_gate is not None:
            self.start_gate.set()
        return self._stop_result

    def _control(self, kind: Kind, operation: VoiceOperation, value: object = None) -> VoiceOperationResult:
        if self.state != FrontendState.ACTIVE or operation.correlation.session_id != self._correlation.session_id:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        if kind not in self.supported:
            return self._result(operation, kind, Status.UNSUPPORTED, VoiceErrorCode.UNSUPPORTED)
        if kind == Kind.SEND_AUDIO and value.format != self.config.input_format:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.INVALID_INPUT)
        self.calls.append((kind, operation, value))
        return self._result(operation, kind, Status.ACCEPTED)

    async def send_audio(self, chunk: VoiceAudioChunk, *, operation: VoiceOperation) -> VoiceOperationResult:
        return self._control(Kind.SEND_AUDIO, operation, chunk)

    async def finish_input(self, *, operation: VoiceOperation) -> VoiceOperationResult:
        return self._control(Kind.FINISH_INPUT, operation)

    async def append_quiet_context(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        return self._control(Kind.QUIET_CONTEXT, operation, update)

    async def append_spoken_result(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        return self._control(Kind.SPOKEN_RESULT, operation, update)

    async def feed_runtime_instruction(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        return self._control(Kind.RUNTIME_INSTRUCTION, operation, update)

    async def cancel_speech(self, *, operation: VoiceOperation, playback: AssistantPlaybackEvidence | None = None) -> VoiceOperationResult:
        return self._control(Kind.CANCEL_SPEECH, operation, playback)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        if self._reader_active:
            raise RuntimeError("VoiceFrontend.events allows only one active reader")
        self._reader_active = True
        try:
            while True:
                while self._queue:
                    yield self._queue.popleft()
                if self._closed:
                    return
                self._changed.clear()
                await self._changed.wait()
        finally:
            self._reader_active = False
