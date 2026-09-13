"""Canonical Realtime adapter: one transport owner and one normalized reader."""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
import json
import time
import uuid
from functools import wraps

from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.domain.v2 import PlaybackCursor, SpeechRequest
from jarvis.domain.voice_events import (
    AssistantAudioPartCompleted,
    AssistantAudioChunk, AssistantGenerationFinished, AssistantGenerationStarted,
    AssistantPlaybackEvidence, AssistantTranscriptCompleted, AssistantTranscriptDelta,
    FrontendLifecycleChanged, UserCommitSource, UserSpeechActivity, UserTranscriptCommitted,
    UserTranscriptDelta, UserTurnOpened, VoiceActivitySource, VoiceEvent, VoiceFrontendFailed,
    VoiceGenerationStatus, VoiceSpeechPhase, VoiceToolCallRequested, VoiceUsageSource, VoiceUsageUpdated,
)
from jarvis.domain.voice_playback import VoiceAudioPart
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceContextMessage, VoiceContextRole, VoiceCorrelation,
    VoiceErrorCode, VoiceFrontendConfig, VoiceFrontendError, VoiceObservation, VoiceOperation,
    VoiceOperationKind, VoiceOperationResult, VoiceOperationStatus,
    VoiceReflexRequest, VoiceStopReason, VoiceTextUpdate, VoiceToolResult, bounded_text,
)
from jarvis.runtime.voice_capabilities import default_voice_registry


class _ProviderFailure(Exception):
    def __init__(self, code: VoiceErrorCode):
        self.code = code


def _command(kind: VoiceOperationKind):
    """Keep provider exceptions below the typed operation boundary."""
    def decorate(method):
        @wraps(method)
        async def guarded(self, *args, operation, **kwargs):
            try:
                return await method(self, *args, operation=operation, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = self._error_code(exc)
                self._failure = self._failure or self._event(VoiceFrontendFailed(
                    VoiceFrontendError(code, kind, FrontendState.UNKNOWN_REAP_REQUIRED)))
                await self.stop(VoiceStopReason.ERROR, operation=operation)
                return self._result(operation, kind, VoiceOperationStatus.FAILED, code=code)
        return guarded
    return decorate


class OpenAIRealtimeFrontend:
    """Owns its low-level session; compatibility runtime never reads it directly.

    Connector is injected at composition for credentials/legacy settings. The
    canonical config remains credential-free. Queue overflow fails the frontend;
    no terminal/transcript event is silently sacrificed to keep it running.
    """

    def __init__(self, connector: Callable[[VoiceFrontendConfig], Awaitable[OpenAIRealtimeSession]], *,
                 ack_timeout_s: float = 15.0, close_timeout_s: float = 5.0, queue_limit: int = 256) -> None:
        self._connector = connector
        self._ack_timeout = ack_timeout_s
        self._close_timeout = close_timeout_s
        self._state = FrontendState.NEW
        self._session: OpenAIRealtimeSession | None = None
        self._start_task: asyncio.Task | None = None
        self._stop_task: asyncio.Task | None = None
        self._reader: asyncio.Task | None = None
        self._queue: asyncio.Queue[VoiceEvent] = asyncio.Queue(maxsize=queue_limit)
        self._finished = asyncio.Event()
        self._ack = asyncio.Event()
        self._instructions_lock = asyncio.Lock()
        self._expected_instructions = ""
        self._correlation: VoiceCorrelation | None = None
        self._config: VoiceFrontendConfig | None = None
        self._sequence = 0
        self._consumer = False
        self._failure: VoiceEvent | None = None
        self._terminal: VoiceEvent | None = None
        self._operations: OrderedDict[str, VoiceCorrelation] = OrderedDict()
        self._speech_operations: OrderedDict[str, VoiceCorrelation] = OrderedDict()
        self._transcript_revisions: dict[str, int] = {}
        self._response_usage: OrderedDict[str, tuple[int | None, int | None]] = OrderedDict()
        self._usage_input: int | None = None
        self._usage_output: int | None = None
        self._usage_input_complete = True
        self._usage_output_complete = True
        self._asr_usage: OrderedDict[str, dict] = OrderedDict()
        self._cancelled_outputs: set[str] = set()
        self._invalidated_outputs: set[str] = set()
        self._pending_output_cancels: dict[tuple[str, str], asyncio.Task] = {}
        self._close_task: asyncio.Task | None = None
        self._connector_cleanup_unconfirmed = False
        self._terminal_cleanup_pending = False

    @property
    def state(self) -> FrontendState:
        return self._state

    @property
    def capabilities(self):
        from dataclasses import replace
        from jarvis.domain.voice_architecture import VoiceModelRef
        model = self._config.mode.conversation_model if self._config is not None else VoiceModelRef("openai", "gpt-realtime-2.1-mini")
        descriptor = default_voice_registry().find(model)
        base = descriptor.capabilities if descriptor else default_voice_registry().require(VoiceModelRef("openai", "gpt-realtime-2.1-mini")).capabilities
        return replace(base, supports_quiet_context_injection=True, supports_prompt_update=True, supports_usage_events=True)

    @property
    def active_output_id(self) -> str | None:
        return self._session.active_output_id if self._session is not None else None

    @property
    def prompt_applications(self) -> tuple[dict[str, object], ...]:
        if self._session is None:
            return ()
        return tuple(dict(item) for item in getattr(self._session, "prompt_applications", ()))

    def _event(self, payload, *, correlation: VoiceCorrelation | None = None, provider_event_id: str | None = None) -> VoiceEvent:
        self._sequence += 1
        assert self._correlation is not None
        return VoiceEvent(str(uuid.uuid4()), self._sequence, correlation or self._correlation,
                          VoiceObservation(datetime.now(timezone.utc), time.monotonic_ns()), payload,
                          provider_event_id=provider_event_id)

    def _emit(self, payload, **kwargs) -> None:
        self._queue.put_nowait(self._event(payload, **kwargs))

    def _result(self, operation: VoiceOperation, kind: VoiceOperationKind, status: VoiceOperationStatus = VoiceOperationStatus.ACCEPTED,
                *, output_id: str | None = None, code: VoiceErrorCode | None = None) -> VoiceOperationResult:
        error = VoiceFrontendError(code, kind, self.state, safe_message=code.value) if code else None
        return VoiceOperationResult(operation, kind, status, self.state, error=error, output_id=output_id)

    def _valid(self, operation: VoiceOperation, kind: VoiceOperationKind) -> VoiceOperationResult | None:
        if self.state is not FrontendState.ACTIVE or self._correlation is None or operation.correlation.session_id != self._correlation.session_id:
            return self._result(operation, kind, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_STATE)
        return None

    async def start(self, config: VoiceFrontendConfig, *, operation: VoiceOperation) -> VoiceOperationResult:
        if config.input_format.sample_rate_hz != 24000:
            return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
        if self.state in (FrontendState.STOPPING, FrontendState.STOPPED, FrontendState.UNKNOWN_REAP_REQUIRED):
            return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_STATE)
        if self._start_task is not None:
            if self._correlation is None or operation.correlation.session_id != self._correlation.session_id or config != self._config:
                return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_STATE)
            return replace(await asyncio.shield(self._start_task), operation=operation)
        if self.state is not FrontendState.NEW:
            return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_STATE)
        self._correlation, self._config = operation.correlation, config
        self._start_task = asyncio.create_task(self._start(config, operation))
        try:
            return await asyncio.shield(self._start_task)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(self.stop(VoiceStopReason.CANCELLED, operation=operation))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
            raise

    async def _start(self, config: VoiceFrontendConfig, operation: VoiceOperation) -> VoiceOperationResult:
        self._state = FrontendState.STARTING
        self._emit(FrontendLifecycleChanged(self.state))
        self._expected_instructions = config.instructions
        try:
            self._session = await self._connector(config)
            if self.state is not FrontendState.STARTING:
                await self._session.close()
                raise asyncio.CancelledError
            self._reader = asyncio.create_task(self._read(), name="jarvis-realtime-canonical-reader")
            await asyncio.wait_for(self._ack.wait(), self._ack_timeout)
            if self.state is not FrontendState.STARTING:
                code = self._failure.payload.error.code if self._failure is not None else VoiceErrorCode.TRANSPORT
                return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.FAILED, code=code)
            self.initial_context_item_ids = []
            for message in config.initial_context.messages:
                role = "system" if message.role is VoiceContextRole.DEVELOPER else message.role.value
                item_id = "ctx_" + uuid.uuid4().hex[:24]
                await self._session.append_message(message.text, role=role, request_response=False, item_id=item_id)
                self.initial_context_item_ids.append(item_id)
            self._state = FrontendState.ACTIVE
            self._emit(FrontendLifecycleChanged(self.state))
            return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.COMPLETED)
        except asyncio.CancelledError as exc:
            self._connector_cleanup_unconfirmed = bool(getattr(exc, "voice_cleanup_unconfirmed", False))
            raise
        except Exception as exc:
            code = self._error_code(exc)
            self._terminal_cleanup_pending = True
            self._state = FrontendState.STOPPING
            try:
                self._emit(FrontendLifecycleChanged(self.state))
            except asyncio.QueueFull:
                pass
            closed = await self._close_owned() and not getattr(exc, "voice_cleanup_unconfirmed", False)
            self._state = FrontendState.STOPPED if closed else FrontendState.UNKNOWN_REAP_REQUIRED
            self._failure = self._event(VoiceFrontendFailed(VoiceFrontendError(code, VoiceOperationKind.START, self.state)))
            self._terminal = self._event(FrontendLifecycleChanged(self.state))
            self._finished.set()
            return self._result(operation, VoiceOperationKind.START, VoiceOperationStatus.FAILED, code=code)

    @staticmethod
    def _error_code(exc: Exception) -> VoiceErrorCode:
        if isinstance(exc, _ProviderFailure):
            return exc.code
        status = getattr(exc, "status", None)
        if status in (401, 403):
            return VoiceErrorCode.AUTHENTICATION
        if status == 429:
            return VoiceErrorCode.RATE_LIMIT
        return VoiceErrorCode.TIMEOUT if isinstance(exc, TimeoutError) else VoiceErrorCode.TRANSPORT

    async def _close_owned(self) -> bool:
        controls = [task for task in self._pending_output_cancels.values() if task is not asyncio.current_task()]
        for task in controls:
            if not task.done():
                task.cancel()
        if controls:
            await asyncio.gather(*controls, return_exceptions=True)
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_transport())
        closed = await asyncio.shield(self._close_task)
        if self._reader is not None and self._reader is not asyncio.current_task():
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        return closed

    async def _close_transport(self) -> bool:
        try:
            if self._session is not None:
                await asyncio.wait_for(self._session.close(), self._close_timeout)
            return not self._connector_cleanup_unconfirmed
        except Exception:
            return False

    async def stop(self, reason: VoiceStopReason, *, operation: VoiceOperation) -> VoiceOperationResult:
        if self._correlation is not None and operation.correlation.session_id != self._correlation.session_id:
            return self._result(operation, VoiceOperationKind.STOP, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_STATE)
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop(reason, operation=operation), name="jarvis-realtime-stop")
        try:
            return replace(await asyncio.shield(self._stop_task), operation=operation)
        except asyncio.CancelledError:
            await asyncio.shield(self._stop_task)
            raise

    async def _stop(self, reason: VoiceStopReason, *, operation: VoiceOperation) -> VoiceOperationResult:
        if self.state is FrontendState.STOPPED:
            return self._result(operation, VoiceOperationKind.STOP, VoiceOperationStatus.COMPLETED)
        if self._correlation is None:
            self._correlation = operation.correlation
        elif operation.correlation.session_id != self._correlation.session_id:
            return self._result(operation, VoiceOperationKind.STOP, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_STATE)
        self._terminal_cleanup_pending = True
        self._state = FrontendState.STOPPING
        try:
            self._emit(FrontendLifecycleChanged(self.state))
        except asyncio.QueueFull:
            pass  # Overflow failure is retained separately by the reader.
        if self._start_task is not None and not self._start_task.done() and self._start_task is not asyncio.current_task():
            self._start_task.cancel()
            await asyncio.gather(self._start_task, return_exceptions=True)
        closed = await self._close_owned()
        self._state = FrontendState.STOPPED if closed else FrontendState.UNKNOWN_REAP_REQUIRED
        self._terminal = self._event(FrontendLifecycleChanged(self.state))
        self._finished.set()
        return self._result(operation, VoiceOperationKind.STOP,
                            VoiceOperationStatus.COMPLETED if closed else VoiceOperationStatus.UNKNOWN,
                            code=None if closed else VoiceErrorCode.CLOSE_UNCONFIRMED)

    async def _read(self) -> None:
        assert self._session is not None
        try:
            async for envelope in self._session.events():
                self._translate(envelope.message_type, envelope.payload)
                if envelope.message_type == "realtime.output_started" and envelope.payload.get("output_id") in self._invalidated_outputs:
                    self._schedule_output_cancel(envelope.payload["output_id"], envelope.payload.get("response_id"))
            if not self._terminal_cleanup_pending and self.state not in (FrontendState.STOPPING, FrontendState.STOPPED):
                raise ConnectionError("Realtime stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._terminal_cleanup_pending:
                return  # The close owner publishes terminal only after its close acknowledgement.
            self._state = FrontendState.UNKNOWN_REAP_REQUIRED
            error = VoiceFrontendError(self._error_code(exc), None, self.state, retryable=True)
            self._failure = self._event(VoiceFrontendFailed(error))
            await self._close_owned()
            self._terminal = self._event(FrontendLifecycleChanged(self.state))
            self._finished.set()
        finally:
            self._ack.set()  # Wake startup/update failure without claiming success.

    def _input(self, item: str | None) -> VoiceCorrelation:
        assert self._correlation is not None
        if not item:
            return self._correlation
        turn = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self._correlation.session_id}/input/{item}"))
        return replace(self._correlation, turn_id=turn, provider_input_id=item)

    def _output(self, values: dict) -> VoiceCorrelation:
        assert self._correlation is not None
        local_id = values.get("output_id")
        base = self._operations.get(local_id) or self._speech_operations.get(values.get("speech_id")) or self._correlation
        return replace(base, output_id=local_id, speech_id=values.get("speech_id") or base.speech_id,
                       provider_output_id=values.get("response_id"), provider_item_id=values.get("item_id"))

    def _translate(self, kind: str, values: dict) -> None:
        provider_event_id = values.get("provider_event_id")
        output_kind = kind in {"realtime.output_started", "realtime.audio", "realtime.audio_done", "realtime.response_done",
                               "realtime.assistant_transcript", "realtime.assistant_transcript_delta", "realtime.tool_call"}
        correlation = self._output(values) if output_kind else self._input(values.get("item_id"))
        part = VoiceAudioPart(values["item_id"], values["content_index"], values.get("output_index")) if output_kind and values.get("item_id") and type(values.get("content_index")) is int else None
        payload = None
        if kind in {"realtime.session_created", "realtime.session_updated"}:
            if values.get("session_id"):
                self._correlation = replace(self._correlation, provider_session_id=values["session_id"])
            if kind == "realtime.session_updated" and values.get("instructions") == self._expected_instructions:
                self._ack.set()
            return
        if kind == "realtime.output_started":
            payload = AssistantGenerationStarted()
        elif kind == "realtime.audio":
            pcm = base64.b64decode(values.get("pcm_b64", ""), validate=True)
            for start in range(0, len(pcm), 48000):
                self._emit(AssistantAudioChunk(VoiceAudioChunk(pcm[start:start + 48000]), part), correlation=correlation, provider_event_id=provider_event_id)
            return
        elif kind == "realtime.audio_done":
            if part is None:
                return  # Missing identity cannot establish a closed part.
            payload = AssistantAudioPartCompleted(part)
        elif kind == "realtime.response_done":
            try:
                status = VoiceGenerationStatus(values.get("status") or "unknown")
            except ValueError:
                status = VoiceGenerationStatus.UNKNOWN
            parts = values.get("audio_parts")
            payload = AssistantGenerationFinished(status,
                tuple(VoiceAudioPart(part["item_id"], part["content_index"], part["output_index"]) for part in parts) if isinstance(parts, list) else None,
                tuple(part["transcript"] for part in parts) if isinstance(parts, list) else None)
            self._usage(values, correlation, provider_event_id)
        elif kind in {"realtime.assistant_transcript", "realtime.assistant_transcript_delta"}:
            bounded_text(values.get("text", ""), 8192, "assistant transcript fragment")
            transcript_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{correlation.session_id}/output/{correlation.output_id}/{correlation.provider_item_id}/{part.content_index if part else 'unknown'}"))
            payload = (AssistantTranscriptCompleted(transcript_id, str(values.get("text") or ""), part) if kind.endswith("transcript")
                       else AssistantTranscriptDelta(transcript_id, str(values.get("text") or ""), part))
        elif kind in {"realtime.transcript", "realtime.transcript_delta"}:
            bounded_text(values.get("text", ""), 8192, "user transcript fragment")
            if correlation.turn_id is None:
                raise ValueError("ASR event has no input identity")
            key = str(correlation.provider_input_id)
            revision = self._transcript_revisions.get(key, 0) + 1
            self._transcript_revisions[key] = revision
            if len(self._transcript_revisions) > 512:
                self._transcript_revisions.pop(next(iter(self._transcript_revisions)))
            payload = (UserTranscriptCommitted(key, str(values.get("text") or ""), revision, UserCommitSource.PROVIDER)
                       if kind == "realtime.transcript" else UserTranscriptDelta(key, str(values.get("text") or ""), revision))
            if isinstance(values.get("usage"), dict):
                self._asr_usage[key] = dict(values["usage"])
                while len(self._asr_usage) > 128:
                    self._asr_usage.popitem(last=False)
        elif kind == "realtime.input_committed":
            if correlation.turn_id is None:
                return
            previous = values.get("previous_item_id")
            correlation = replace(correlation, previous_provider_input_id=previous)
            payload = UserTurnOpened(self._input(previous).turn_id if previous else None, VoiceActivitySource.PROVIDER)
        elif kind in {"realtime.speech_started", "realtime.speech_stopped"}:
            payload = UserSpeechActivity(VoiceSpeechPhase.STARTED if kind.endswith("started") else VoiceSpeechPhase.STOPPED, VoiceActivitySource.PROVIDER)
        elif kind == "realtime.tool_call":
            # A function item is not an audio truncation cursor or user input.
            correlation = replace(correlation, provider_item_id=None)
            raw = values.get("arguments_json", json.dumps(values.get("arguments"), ensure_ascii=False))
            payload = VoiceToolCallRequested(str(values.get("call_id") or ""), str(values.get("name") or ""), raw)
        elif kind in {"realtime.error", "realtime.transcript_failed"}:
            error = values.get("error") if isinstance(values.get("error"), dict) else {}
            code = str(error.get("code") or "")
            safe_code = code if len(code) <= 128 and code.replace("_", "").isalnum() else None
            mapped = (VoiceErrorCode.AUTHENTICATION if code == "invalid_api_key" else
                      VoiceErrorCode.RATE_LIMIT if code == "rate_limit_exceeded" else VoiceErrorCode.PROVIDER)
            if self.state is FrontendState.STARTING:
                raise _ProviderFailure(mapped)
            payload = VoiceFrontendFailed(VoiceFrontendError(mapped, None, self.state, retryable=True, provider_code=safe_code))
        if payload is not None:
            self._emit(payload, correlation=correlation, provider_event_id=provider_event_id)

    def _usage(self, values: dict, correlation: VoiceCorrelation, provider_event_id: str | None) -> None:
        response = values.get("response_id")
        usage = values.get("usage")
        if not response or response in self._response_usage:
            return
        usage = usage if isinstance(usage, dict) else {}
        counts = tuple(value if type(value) is int and value >= 0 else None for value in (usage.get("input_tokens"), usage.get("output_tokens")))
        self._response_usage[response] = counts
        # Retain all response IDs within the bounded session; reaching this cap
        # fails instead of forgetting IDs and counting an old replay twice.
        if len(self._response_usage) > 4096:
            raise ValueError("Realtime usage retention exhausted")
        self._usage_input_complete = self._usage_input_complete and counts[0] is not None
        self._usage_output_complete = self._usage_output_complete and counts[1] is not None
        if counts[0] is not None and self._usage_input_complete:
            self._usage_input = (self._usage_input or 0) + counts[0]
        else:
            self._usage_input = None
        if counts[1] is not None and self._usage_output_complete:
            self._usage_output = (self._usage_output or 0) + counts[1]
        else:
            self._usage_output = None
        self._emit(VoiceUsageUpdated(VoiceUsageSource.PROVIDER_SNAPSHOT, input_tokens=self._usage_input, output_tokens=self._usage_output), correlation=correlation, provider_event_id=provider_event_id)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        if self._consumer:
            raise RuntimeError("VoiceFrontend.events has one consumer")
        self._consumer = True
        try:
            while True:
                if not self._queue.empty():
                    yield self._queue.get_nowait()
                    continue
                if self._finished.is_set():
                    if self._failure is not None:
                        event, self._failure = self._failure, None
                        yield event
                    if self._terminal is not None:
                        event, self._terminal = self._terminal, None
                        yield event
                    return
                get = asyncio.create_task(self._queue.get())
                finished = asyncio.create_task(self._finished.wait())
                try:
                    done, _ = await asyncio.wait((get, finished), return_when=asyncio.FIRST_COMPLETED)
                    if get in done:
                        yield get.result()
                finally:
                    for task in (get, finished):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(get, finished, return_exceptions=True)
        finally:
            self._consumer = False

    @_command(VoiceOperationKind.SEND_AUDIO)
    async def send_audio(self, chunk: VoiceAudioChunk, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.SEND_AUDIO):
            return failure
        if chunk.format.sample_rate_hz != 24000:
            return self._result(operation, VoiceOperationKind.SEND_AUDIO, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
        await self._session.send_audio(chunk.pcm)
        return self._result(operation, VoiceOperationKind.SEND_AUDIO)

    @_command(VoiceOperationKind.FINISH_INPUT)
    async def finish_input(self, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.FINISH_INPUT):
            return failure
        sent = await self._session.finish_input()
        return self._result(operation, VoiceOperationKind.FINISH_INPUT, VoiceOperationStatus.ACCEPTED if sent else VoiceOperationStatus.REJECTED,
                            code=None if sent else VoiceErrorCode.INVALID_INPUT)

    @_command(VoiceOperationKind.QUIET_CONTEXT)
    async def append_quiet_context(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.QUIET_CONTEXT):
            return failure
        # Data message, not a system instruction. No response.create.
        await self._session.append_message(update.text, role="user", request_response=False)
        return self._result(operation, VoiceOperationKind.QUIET_CONTEXT)

    @_command(VoiceOperationKind.SPOKEN_RESULT)
    async def append_spoken_result(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.SPOKEN_RESULT):
            return failure
        reserved = operation.correlation.output_id
        if reserved is not None:
            if not isinstance(reserved, str) or not reserved or len(reserved) > 256 or not reserved.isprintable() or reserved.strip() != reserved or reserved in self._operations:
                return self._result(operation, VoiceOperationKind.SPOKEN_RESULT, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
            self._remember(reserved, operation.correlation)
        if reserved in self._invalidated_outputs:
            return self._result(operation, VoiceOperationKind.SPOKEN_RESULT, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.CANCELLED)
        request = SpeechRequest(conversation_id=str(operation.correlation.session_id), text=update.text,
                                id=operation.correlation.speech_id or str(uuid.uuid4()))
        self._speech_operations[request.id] = operation.correlation
        while len(self._speech_operations) > 128:
            self._speech_operations.popitem(last=False)
        output = await self._session.speak(request, output_id=reserved)
        self._remember(output, operation.correlation)
        return self._result(operation, VoiceOperationKind.SPOKEN_RESULT, output_id=output)

    @_command(VoiceOperationKind.CONVERSATION)
    async def request_conversation(self, request, *, operation: VoiceOperation) -> VoiceOperationResult:
        from jarvis.domain.voice_frontend import VoiceConversationRequest
        if failure := self._valid(operation, VoiceOperationKind.CONVERSATION):
            return failure
        output = operation.correlation.output_id
        if not isinstance(request, VoiceConversationRequest) or not isinstance(output, str) or not output or len(output) > 256 or not output.isprintable() or output in self._operations:
            return self._result(operation, VoiceOperationKind.CONVERSATION, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
        if output in self._invalidated_outputs:
            return self._result(operation, VoiceOperationKind.CONVERSATION, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.CANCELLED)
        self._remember(output, operation.correlation)  # Bind early events before awaiting wire.
        returned = await self._session.request_conversation(request.input_item_ids, output_id=output)
        return self._result(operation, VoiceOperationKind.CONVERSATION, output_id=returned)

    def _remember(self, output: str, correlation: VoiceCorrelation) -> None:
        self._operations[output] = correlation
        while len(self._operations) > 128:
            self._operations.popitem(last=False)

    @_command(VoiceOperationKind.REFLEX)
    async def request_reflex(self, request: VoiceReflexRequest, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.REFLEX):
            return failure
        reserved = operation.correlation.output_id
        if reserved is not None:
            if not isinstance(reserved, str) or not reserved or len(reserved) > 256 or not reserved.isprintable() or reserved.strip() != reserved or reserved in self._operations:
                return self._result(operation, VoiceOperationKind.REFLEX, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
            self._remember(reserved, operation.correlation)
        if reserved in self._invalidated_outputs:
            return self._result(operation, VoiceOperationKind.REFLEX, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.CANCELLED)
        output = await self._session.speak_reflex(transcript=request.transcript, avoid=request.avoid, output_id=reserved)
        self._remember(output, operation.correlation)
        return self._result(operation, VoiceOperationKind.REFLEX, output_id=output)

    @_command(VoiceOperationKind.CANCEL_SPEECH)
    async def invalidate_unstarted_output(self, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.CANCEL_SPEECH):
            return failure
        output = operation.correlation.output_id
        if not isinstance(output, str) or not output or len(output) > 256 or not output.isprintable() or output.strip() != output:
            return self._result(operation, VoiceOperationKind.CANCEL_SPEECH, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
        if len(self._invalidated_outputs) >= 4096 and output not in self._invalidated_outputs:
            raise ValueError("Output invalidation retention exhausted")
        self._invalidated_outputs.add(output)
        self._schedule_output_cancel(output, self._session.response_for_output(output))
        return self._result(operation, VoiceOperationKind.CANCEL_SPEECH)

    def _schedule_output_cancel(self, output_id: str, response_id: str | None) -> None:
        if response_id is None or self.state is not FrontendState.ACTIVE:
            return
        key = (output_id, response_id)
        if key in self._pending_output_cancels:
            return
        if len(self._pending_output_cancels) >= 4096:
            raise ValueError("Output cancellation retention exhausted")
        self._pending_output_cancels[key] = asyncio.create_task(self._cancel_reserved_response(*key), name="jarvis-reflex-cancel")

    async def _cancel_reserved_response(self, output_id: str, response_id: str) -> None:
        try:
            await asyncio.wait_for(self._session.cancel_pending_output(output_id, response_id=response_id), self._ack_timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._terminal_cleanup_pending = True
            self._state = FrontendState.UNKNOWN_REAP_REQUIRED
            self._failure = self._event(VoiceFrontendFailed(VoiceFrontendError(self._error_code(exc), VoiceOperationKind.CANCEL_SPEECH, self.state)))
            await self._close_owned()
            self._terminal = self._event(FrontendLifecycleChanged(self.state))
            self._finished.set()

    @_command(VoiceOperationKind.TOOL_RESULT)
    async def send_tool_result(self, result: VoiceToolResult, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.TOOL_RESULT):
            return failure
        await self._session.send_tool_result(result.call_id, json.loads(result.result_json), request_response=result.request_response)
        return self._result(operation, VoiceOperationKind.TOOL_RESULT)

    @_command(VoiceOperationKind.CONTEXT_MESSAGE)
    async def append_context_message(self, message: VoiceContextMessage, *, request_response: bool, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.CONTEXT_MESSAGE):
            return failure
        if type(request_response) is not bool:
            return self._result(operation, VoiceOperationKind.CONTEXT_MESSAGE, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
        role = "system" if message.role is VoiceContextRole.DEVELOPER else message.role.value
        await self._session.append_message(message.text, role=role, request_response=request_response)
        return self._result(operation, VoiceOperationKind.CONTEXT_MESSAGE)

    @_command(VoiceOperationKind.RUNTIME_INSTRUCTION)
    async def feed_runtime_instruction(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.RUNTIME_INSTRUCTION):
            return failure
        async with self._instructions_lock:
            self._expected_instructions = update.text
            self._ack.clear()
            await self._session.update_instructions(update.text)
            try:
                await asyncio.wait_for(self._ack.wait(), self._ack_timeout)
            except asyncio.TimeoutError:
                return self._result(operation, VoiceOperationKind.RUNTIME_INSTRUCTION, VoiceOperationStatus.UNKNOWN, code=VoiceErrorCode.TIMEOUT)
            if self.state is not FrontendState.ACTIVE:
                return self._result(operation, VoiceOperationKind.RUNTIME_INSTRUCTION, VoiceOperationStatus.FAILED, code=VoiceErrorCode.TRANSPORT)
            return self._result(operation, VoiceOperationKind.RUNTIME_INSTRUCTION, VoiceOperationStatus.COMPLETED)

    @_command(VoiceOperationKind.CANCEL_SPEECH)
    async def cancel_speech(self, *, operation: VoiceOperation, playback: AssistantPlaybackEvidence | None = None) -> VoiceOperationResult:
        if failure := self._valid(operation, VoiceOperationKind.CANCEL_SPEECH):
            return failure
        correlation = operation.correlation
        if playback is not None and playback.part is not None and playback.part.item_id != correlation.provider_item_id:
            return self._result(operation, VoiceOperationKind.CANCEL_SPEECH, VoiceOperationStatus.REJECTED, code=VoiceErrorCode.INVALID_INPUT)
        cursor = PlaybackCursor(speech_id=correlation.speech_id or correlation.output_id or "unknown",
                                played_ms=int(playback.played_ms or 0) if playback else 0,
                                provider_response_id=correlation.provider_output_id,
                                provider_item_id=correlation.provider_item_id,
                                content_index=playback.part.content_index if playback is not None and playback.part is not None else None)
        key = str(correlation.provider_output_id or correlation.output_id or self.active_output_id or "")
        if not key or key not in self._cancelled_outputs:
            await self._session.cancel_output(cursor if correlation.provider_output_id or correlation.output_id else None)
            if key:
                if len(self._cancelled_outputs) >= 4096:
                    raise ValueError("Cancellation retention exhausted")
                self._cancelled_outputs.add(key)
        if playback is not None and correlation.provider_item_id:
            await self._session.truncate(cursor)
        # Sent only; truncate ACK is observed separately, never synchronization proof.
        return self._result(operation, VoiceOperationKind.CANCEL_SPEECH)

    async def keepalive(self) -> None:
        if self._session is not None and self.state is FrontendState.ACTIVE:
            await self._session.keepalive()
