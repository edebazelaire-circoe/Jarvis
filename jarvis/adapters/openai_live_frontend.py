"""GPT-Live VoiceFrontend adapter with one wire reader and truthful evidence.

Provider messages stay in this module.  The adapter never invents transcript
finality, a committed user turn, output alignment, or playback completion.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol
import math
import time
import uuid

from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelCapabilities
from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantTranscriptDelta, FrontendLifecycleChanged,
    UserTranscriptDelta, VoiceDelegationRequested, VoiceEvent,
    VoiceFrontendFailed, VoiceUsageSource, VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    FrontendState, ProviderDelegationId, ProviderEventId, ProviderSessionId,
    VoiceAudioChunk, VoiceCorrelation, VoiceErrorCode, VoiceEventId,
    VoiceFrontendConfig, VoiceFrontendError, VoiceObservation, VoiceOperation,
    VoiceOperationKind as Kind, VoiceOperationResult, VoiceOperationStatus as Status,
    VoiceOutputId, VoicePcmFormat, VoiceSessionInterval, VoiceStopReason,
    VoiceTextUpdate, VoiceTranscriptId,
)
from jarvis.ports.live_sideband import LiveTerminalReceipt


LIVE_URL = "wss://api.openai.com/v1/live/sessions"
MAX_APPEND_UTF8 = 500  # Conservative preflight for the provider's 500-token cap.
MAX_STREAM_TEXT = 8192


class LiveTransport(Protocol):
    async def send_json(self, value: dict[str, object]) -> None: ...
    async def receive_json(self) -> dict[str, object] | None: ...
    async def close(self) -> None: ...


LiveConnector = Callable[[], Awaitable[LiveTransport]]


class AiohttpLiveTransport:
    """Small optional production transport; ownership includes its HTTP session."""

    def __init__(self, session, socket) -> None:
        self._session, self._socket = session, socket

    @classmethod
    async def connect(cls, api_key: str):
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("OpenAI API key is required")
        import aiohttp
        session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {api_key}"})
        try:
            socket = await session.ws_connect(LIVE_URL)
        except BaseException:
            await session.close()
            raise
        return cls(session, socket)

    async def send_json(self, value: dict[str, object]) -> None:
        await self._socket.send_json(value)

    async def receive_json(self) -> dict[str, object] | None:
        import aiohttp
        message = await self._socket.receive()
        if message.type is aiohttp.WSMsgType.TEXT:
            value = message.json()
            if not isinstance(value, dict):
                raise ValueError("Live message must be an object")
            return value
        if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
            return None
        if message.type is aiohttp.WSMsgType.ERROR:
            raise RuntimeError("Live socket failed")
        raise ValueError("Unsupported Live frame")

    async def close(self) -> None:
        try:
            await self._socket.close()
        finally:
            await self._session.close()


def aiohttp_live_connector(api_key: str) -> LiveConnector:
    async def connect() -> LiveTransport:
        return await AiohttpLiveTransport.connect(api_key)
    return connect


class OpenAILiveFrontend:
    """Single-use GPT-Live incarnation.

    Control calls may wait for ACKs, but only ``_read`` receives wire messages.
    Caller cancellation does not cancel owned start/stop cleanup.
    """

    def __init__(self, connector: LiveConnector, *, voice: str = "marin",
                 start_timeout_s: float = 15.0, ack_timeout_s: float = 15.0,
                 close_timeout_s: float = 5.0, queue_limit: int = 256,
                 lifecycle_hooks=None) -> None:
        if not callable(connector) or not isinstance(voice, str) or not voice.strip():
            raise ValueError("Live connector and voice are required")
        for value, name in ((start_timeout_s, "start"), (ack_timeout_s, "ack"), (close_timeout_s, "close")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} timeout must be finite and positive")
        if type(queue_limit) is not int or queue_limit < 1:
            raise ValueError("queue_limit must be positive")
        self._connector, self._voice = connector, voice
        self._start_timeout, self._ack_timeout, self._close_timeout = start_timeout_s, ack_timeout_s, close_timeout_s
        self._queue_limit = queue_limit
        self._events: deque[VoiceEvent] = deque()
        self._changed = asyncio.Event()
        self._stream_ended = False
        self._consumer = False
        self._state = FrontendState.NEW
        self._transport: LiveTransport | None = None
        self._config: VoiceFrontendConfig | None = None
        self._correlation: VoiceCorrelation | None = None
        self._sequence = 0
        self._input_revision = 0
        self._input_chars = self._output_chars = 0
        self._observed_direction: str | None = None
        self._input_transcript_id: VoiceTranscriptId | None = None
        self._output_transcript_id: VoiceTranscriptId | None = None
        self._output_id: VoiceOutputId | None = None
        self._started = asyncio.Event()
        self._closed = asyncio.Event()
        self._reader: asyncio.Task[None] | None = None
        self._start_task: asyncio.Task[VoiceOperationResult] | None = None
        self._stop_task: asyncio.Task[VoiceOperationResult] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._pending_acks: dict[str, tuple[str, asyncio.Future[None]]] = {}
        self._seen_provider_event_ids: set[str] = set()
        self._known_delegations: set[str] = set()
        self._used_append_ids: set[str] = set()
        self._stop_requested = asyncio.Event()
        self._provider_close_reason: str | None = None
        self._expires_at: int | None = None
        self._context_usage_ratio: float | None = None
        self._lifecycle_hooks = lifecycle_hooks

    @property
    def state(self) -> FrontendState:
        return self._state

    @property
    def capabilities(self) -> VoiceModelCapabilities:
        return VoiceModelCapabilities(
            supports_audio_input=True, supports_audio_output=True,
            supports_realtime_conversation=True, supports_full_duplex=True,
            supports_transcript_deltas=True, supports_native_interruptions=False,
            supports_backend_delegation=True, supports_quiet_context_injection=True,
            supports_spoken_result_injection=True, supports_usage_events=True,
            supports_prompt_update=True, billable_session_time=True,
        )

    @property
    def provider_close_reason(self) -> str | None:
        return self._provider_close_reason

    @property
    def expires_at(self) -> int | None:
        return self._expires_at

    @property
    def context_usage_ratio(self) -> float | None:
        return self._context_usage_ratio

    def _event(self, payload, *, correlation: VoiceCorrelation | None = None,
               provider_event_id: str | None = None,
               interval: VoiceSessionInterval | None = None) -> VoiceEvent:
        self._sequence += 1
        assert self._correlation is not None
        return VoiceEvent(VoiceEventId(str(uuid.uuid4())), self._sequence,
                          correlation or self._correlation,
                          VoiceObservation(datetime.now(timezone.utc), time.monotonic_ns()), payload,
                          provider_event_id=ProviderEventId(provider_event_id) if provider_event_id else None,
                          provider_interval=interval)

    def _enqueue(self, payload, **kwargs) -> bool:
        if len(self._events) >= self._queue_limit:
            self._fail(VoiceErrorCode.PROVIDER, None, "voice_event_overflow")
            return False
        self._events.append(self._event(payload, **kwargs))
        self._changed.set()
        return True

    def _enqueue_terminal(self, payload, **kwargs) -> None:
        # Terminal control capacity is intentionally outside the data limit.
        self._events.append(self._event(payload, **kwargs))
        self._changed.set()

    def _transition(self, state: FrontendState) -> None:
        if self._state is state:
            return
        self._state = state
        self._enqueue_terminal(FrontendLifecycleChanged(state))

    def _error(self, code: VoiceErrorCode, kind: Kind | None, message: str = "") -> VoiceFrontendError:
        return VoiceFrontendError(code, kind, self._state, retryable=code in {VoiceErrorCode.TRANSPORT, VoiceErrorCode.TIMEOUT}, safe_message=message[:512])

    def _fail(self, code: VoiceErrorCode, kind: Kind | None, message: str = "") -> None:
        if self._state not in {FrontendState.STOPPED, FrontendState.UNKNOWN_REAP_REQUIRED}:
            self._transition(FrontendState.UNKNOWN_REAP_REQUIRED)
            self._enqueue_terminal(VoiceFrontendFailed(self._error(code, kind, message)))
        self._reject_acks()
        self._stream_ended = True
        self._changed.set()
        self._ensure_cleanup()

    def _result(self, operation: VoiceOperation, kind: Kind, status: Status,
                code: VoiceErrorCode | None = None) -> VoiceOperationResult:
        return VoiceOperationResult(operation, kind, status, self._state,
                                    self._error(code, kind, code.value) if code else None,
                                    output_id=None)

    def _valid(self, operation: VoiceOperation, kind: Kind) -> VoiceOperationResult | None:
        if self._state is not FrontendState.ACTIVE or self._correlation is None or operation.correlation.session_id != self._correlation.session_id:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        return None

    async def start(self, config: VoiceFrontendConfig, *, operation: VoiceOperation) -> VoiceOperationResult:
        if self._state in {FrontendState.STOPPING, FrontendState.STOPPED, FrontendState.UNKNOWN_REAP_REQUIRED}:
            if self._correlation is None:
                self._correlation = operation.correlation
            return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        if self._start_task is not None:
            if config != self._config or self._correlation is None or operation.correlation.session_id != self._correlation.session_id:
                return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
            return replace(await asyncio.shield(self._start_task), operation=operation)
        if self._state is not FrontendState.NEW:
            return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        if not isinstance(config.mode, DuplexVoiceConfig) or config.mode.conversation_model.provider_id != "openai" or config.mode.conversation_model.model_id != "gpt-live-1" or config.input_format.sample_rate_hz not in {16000, 24000}:
            self._correlation = operation.correlation
            return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_INPUT)
        self._config, self._correlation = config, operation.correlation
        self._start_task = asyncio.create_task(self._start(config, operation), name="jarvis-live-start")
        return await asyncio.shield(self._start_task)

    def validate_start(self, config: VoiceFrontendConfig, operation: VoiceOperation) -> None:
        """Validate and bound the exact provider payload without opening a socket."""
        if not isinstance(config.mode, DuplexVoiceConfig) or config.mode.conversation_model.provider_id != "openai" or config.mode.conversation_model.model_id != "gpt-live-1" or config.input_format.sample_rate_hz not in {16000, 24000}:
            raise ValueError("invalid GPT-Live frontend config")
        self._start_payload(config, str(operation.operation_id))

    async def _start(self, config: VoiceFrontendConfig, operation: VoiceOperation) -> VoiceOperationResult:
        payload = self._start_payload(config, str(operation.operation_id))
        self._transition(FrontendState.STARTING)
        try:
            async with asyncio.timeout(self._start_timeout):
                self._transport = await self._connector()
                if self._stop_requested.is_set():
                    self._ensure_cleanup()
                    self._transition(FrontendState.STOPPED)
                    self._closed.set()
                    self._stream_ended = True
                    self._changed.set()
                    return self._result(operation, Kind.START, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
                self._reader = asyncio.create_task(self._read(), name="jarvis-live-reader")
                if self._lifecycle_hooks is not None:
                    await self._lifecycle_hooks.before_start_send()
                await self._transport.send_json(payload)
                await self._started.wait()
        except asyncio.CancelledError:
            self._fail(VoiceErrorCode.CANCELLED, Kind.START, "start caller cancelled")
            raise
        except TimeoutError:
            self._fail(VoiceErrorCode.TIMEOUT, Kind.START, "session.started timeout")
            return self._result(operation, Kind.START, Status.UNKNOWN, VoiceErrorCode.TIMEOUT)
        except Exception:
            self._fail(VoiceErrorCode.TRANSPORT, Kind.START, "Live startup failed")
            return self._result(operation, Kind.START, Status.FAILED, VoiceErrorCode.TRANSPORT)
        if self._state is not FrontendState.ACTIVE:
            return self._result(operation, Kind.START, Status.UNKNOWN, VoiceErrorCode.CLOSE_UNCONFIRMED)
        return self._result(operation, Kind.START, Status.COMPLETED)

    def _start_payload(self, config: VoiceFrontendConfig, event_id: str) -> dict[str, object]:
        instructions = config.instructions
        if len(instructions.encode("utf-8")) > 16384:
            raise ValueError("Live instructions exceed conservative token bound")
        messages = []
        total = 0
        for message in config.initial_context.messages:
            total += len(message.text.encode("utf-8"))
            part_type = "output_text" if message.role.value == "assistant" else "input_text"
            messages.append({"role": message.role.value, "content": [{"type": part_type, "text": message.text}]})
        if len(messages) > 128 or total > 8192:
            raise ValueError("Live initial context exceeds conservative token bound")
        return {"type": "session.start", "event_id": event_id, "session": {
            "model": "gpt-live-1", "instructions": instructions,
            "delegation": {"type": "client"}, "audio": {
                "format": {"type": "audio/pcm", "rate": config.input_format.sample_rate_hz},
                "output": {"voice": self._voice},
            }, "store": False, "input": messages,
        }}

    async def _read(self) -> None:
        try:
            assert self._transport is not None
            while True:
                value = await self._transport.receive_json()
                if value is None:
                    if not self._closed.is_set():
                        await self._notify_uncertain("provider_eof")
                        self._fail(VoiceErrorCode.CLOSE_UNCONFIRMED, None, "Live transport ended before session.closed")
                    return
                await self._handle(value)
                if self._closed.is_set():
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._notify_uncertain("provider_event_failure")
            self._fail(VoiceErrorCode.PROVIDER, None, "Invalid or failed Live event")

    async def _notify_uncertain(self, reason: str) -> None:
        if self._lifecycle_hooks is None:
            return
        try:
            await self._lifecycle_hooks.mark_unknown(reason)
        except Exception:
            pass

    @staticmethod
    def _string(value: object, name: str, *, optional: bool = False) -> str | None:
        if value is None and optional:
            return None
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ValueError(f"invalid {name}")
        return value

    @classmethod
    def _identity(cls, value: object, name: str, *, optional: bool = False) -> str | None:
        result = cls._string(value, name, optional=optional)
        if result is not None and (len(result) > 256 or not result.isprintable() or result.strip() != result):
            raise ValueError(f"invalid {name}")
        return result

    @staticmethod
    def _interval(value: dict[str, object]) -> VoiceSessionInterval:
        start, end = value.get("start_ms"), value.get("end_ms")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError("invalid Live interval")
        return VoiceSessionInterval(float(start), float(end))

    async def _handle(self, value: dict[str, object]) -> None:
        kind = self._string(value.get("type"), "event type")
        provider_event = self._identity(value.get("event_id"), "event id", optional=True)
        if provider_event is not None:
            if provider_event in self._seen_provider_event_ids:
                return
            if len(self._seen_provider_event_ids) >= 4096:
                self._fail(VoiceErrorCode.CONTEXT_LIMIT, None, "Live event identity bound")
                return
            self._seen_provider_event_ids.add(provider_event)
        if kind == "session.started":
            session = value.get("session")
            if not isinstance(session, dict):
                raise ValueError("missing Live session")
            provider_id = self._identity(session.get("id"), "session id")
            if session.get("model") not in (None, "gpt-live-1"):
                raise ValueError("unexpected Live model")
            expires = session.get("expires_at")
            if expires is not None and (type(expires) is not int or expires < 0):
                raise ValueError("invalid expiry")
            allow_active = True
            if self._lifecycle_hooks is not None:
                allow_active = await self._lifecycle_hooks.session_started(provider_id)
            self._expires_at = expires
            assert self._correlation is not None
            self._correlation = replace(self._correlation, provider_session_id=ProviderSessionId(provider_id))
            if self._state is FrontendState.STARTING and allow_active:
                self._transition(FrontendState.ACTIVE)
            elif self._state is FrontendState.STARTING:
                self._transition(FrontendState.STOPPING)
            elif self._state is not FrontendState.STOPPING:
                raise ValueError("unexpected session.started")
            self._started.set()
        elif kind in {"session.input_transcript.delta", "session.output_transcript.delta"}:
            delta = self._string(value.get("delta"), "transcript delta")
            interval = self._interval(value)
            if kind.startswith("session.input"):
                self._enter_direction("input")
                if self._input_chars + len(delta) > MAX_STREAM_TEXT:
                    self._fail(VoiceErrorCode.CONTEXT_LIMIT, None, "Live input transcript bound")
                    return
                self._input_chars += len(delta)
                self._input_revision += 1
                self._input_transcript_id = self._input_transcript_id or VoiceTranscriptId(f"live-input-{uuid.uuid4()}")
                self._enqueue(UserTranscriptDelta(self._input_transcript_id, delta, self._input_revision), provider_event_id=provider_event, interval=interval)
            else:
                self._enter_direction("output")
                if self._output_chars + len(delta) > MAX_STREAM_TEXT:
                    self._fail(VoiceErrorCode.CONTEXT_LIMIT, None, "Live output transcript bound")
                    return
                self._output_chars += len(delta)
                self._output_transcript_id = self._output_transcript_id or VoiceTranscriptId(f"live-output-text-{uuid.uuid4()}")
                self._output_id = self._output_id or VoiceOutputId(f"live-output-{uuid.uuid4()}")
                assert self._correlation is not None
                correlation = replace(self._correlation, output_id=self._output_id)
                self._enqueue(AssistantTranscriptDelta(self._output_transcript_id, delta), correlation=correlation, provider_event_id=provider_event, interval=interval)
        elif kind == "session.output_audio.delta":
            assert self._config is not None
            self._enter_direction("output")
            encoded = value.get("delta")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError("invalid audio delta")
            if len(encoded) > self._config.input_format.sample_rate_hz * 12:
                raise ValueError("Live audio delta exceeds bound")
            try:
                pcm = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("invalid audio") from exc
            if not pcm or len(pcm) % 2:
                raise ValueError("invalid PCM")
            assert self._correlation is not None
            limit = self._config.input_format.sample_rate_hz * 2
            self._output_id = self._output_id or VoiceOutputId(f"live-output-{uuid.uuid4()}")
            correlation = replace(self._correlation, output_id=self._output_id)
            for offset in range(0, len(pcm), limit):
                chunk = pcm[offset:offset + limit]
                if not self._enqueue(AssistantAudioChunk(VoiceAudioChunk(chunk, self._config.input_format)), correlation=correlation, provider_event_id=provider_event):
                    return
        elif kind == "session.delegation.created":
            delegation = value.get("delegation")
            if not isinstance(delegation, dict) or delegation.get("type") != "delegation" or delegation.get("target") != "client":
                raise ValueError("invalid client delegation")
            delegation_id = self._identity(delegation.get("id"), "delegation id")
            offset = value.get("offset_ms")
            if isinstance(offset, bool) or not isinstance(offset, (int, float)):
                raise ValueError("invalid delegation offset")
            if delegation_id not in self._known_delegations and len(self._known_delegations) >= 64:
                self._fail(VoiceErrorCode.CONTEXT_LIMIT, None, "Live delegation bound")
                return
            self._known_delegations.add(delegation_id)
            assert self._correlation is not None
            correlation = replace(self._correlation, provider_delegation_id=ProviderDelegationId(delegation_id))
            self._enqueue(VoiceDelegationRequested(self._input_revision), correlation=correlation,
                          provider_event_id=provider_event,
                          interval=VoiceSessionInterval(float(offset), float(offset)))
        elif kind == "session.usage.updated":
            usage = value.get("usage")
            if not isinstance(usage, dict):
                raise ValueError("invalid usage")
            context = value.get("context_window")
            if isinstance(context, dict) and context.get("usage_ratio") is not None:
                ratio = context["usage_ratio"]
                if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
                    raise ValueError("invalid context usage")
                self._context_usage_ratio = float(ratio)
            duration = self._duration(usage)
            if self._lifecycle_hooks is not None:
                await self._lifecycle_hooks.usage_updated(duration)
            self._enqueue(VoiceUsageUpdated(VoiceUsageSource.PROVIDER_SNAPSHOT, duration_s=duration), provider_event_id=provider_event)
        elif kind == "session.closed":
            usage = value.get("usage")
            session = value.get("session")
            if not isinstance(usage, dict) or not isinstance(session, dict):
                raise ValueError("invalid final usage")
            session_id = self._identity(session.get("id"), "closed session id")
            if self._correlation is None or str(self._correlation.provider_session_id or "") != session_id:
                raise ValueError("closed session identity mismatch")
            reason = self._string(value.get("reason"), "close reason")
            duration = self._duration(usage)
            # Reuse the sideband receipt validator so primary and recovery
            # accept exactly the same documented terminal evidence.
            receipt = LiveTerminalReceipt(session_id, reason, duration)
            if self._lifecycle_hooks is not None:
                await self._lifecycle_hooks.session_closed(
                    receipt.provider_session_id, receipt.reason, receipt.usage_seconds,
                )
            self._provider_close_reason = reason
            self._enqueue_terminal(VoiceUsageUpdated(VoiceUsageSource.PROVIDER_FINAL, duration_s=duration), provider_event_id=provider_event)
            self._transition(FrontendState.STOPPED)
            self._closed.set()
            self._reject_acks()
            self._stream_ended = True
            self._changed.set()
        elif kind in {"session.thinking.appended", "session.commentary.appended", "session.instructions.appended"}:
            client_id = self._identity(value.get("client_event_id"), "client event id")
            self._interval(value)
            pending = self._pending_acks.get(client_id)
            channel = kind.removeprefix("session.").removesuffix(".appended")
            if pending is not None and pending[0] == channel:
                self._pending_acks.pop(client_id, None)
                future = pending[1]
                if not future.done():
                    future.set_result(None)
        elif kind == "error":
            error = value.get("error")
            if not isinstance(error, dict):
                raise ValueError("invalid provider error")
            client_id = error.get("client_event_id")
            if isinstance(client_id, str):
                pending = self._pending_acks.pop(client_id, None)
                if pending is not None and not pending[1].done():
                    pending[1].set_exception(RuntimeError("provider rejected operation"))
            else:
                self._fail(VoiceErrorCode.PROVIDER, None, "Live provider error")
        # Forward-compatible unknown events carry no canonical authority.

    def _enter_direction(self, direction: str) -> None:
        """Rotate local provisional epochs on observed input/output alternation.

        This is bounded application grouping, not provider finality. Late frames
        may therefore start another epoch; no completed event is emitted.
        """
        if self._observed_direction == direction:
            return
        self._observed_direction = direction
        if direction == "input":
            self._input_transcript_id = None
            self._input_revision = 0
            self._input_chars = 0
        else:
            self._output_transcript_id = None
            self._output_id = None
            self._output_chars = 0

    @staticmethod
    def _duration(usage: dict[str, object]) -> float:
        seconds = usage.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("invalid usage seconds")
        return float(seconds)

    async def send_audio(self, chunk: VoiceAudioChunk, *, operation: VoiceOperation) -> VoiceOperationResult:
        if invalid := self._valid(operation, Kind.SEND_AUDIO):
            return invalid
        assert self._config is not None and self._transport is not None
        if chunk.format != self._config.input_format:
            return self._result(operation, Kind.SEND_AUDIO, Status.REJECTED, VoiceErrorCode.INVALID_INPUT)
        try:
            await self._transport.send_json({"type": "session.input_audio.append", "event_id": str(operation.operation_id),
                                             "audio": base64.b64encode(chunk.pcm).decode("ascii")})
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail(VoiceErrorCode.TRANSPORT, Kind.SEND_AUDIO, "audio send failed")
            return self._result(operation, Kind.SEND_AUDIO, Status.UNKNOWN, VoiceErrorCode.TRANSPORT)
        return self._result(operation, Kind.SEND_AUDIO, Status.ACCEPTED)

    async def finish_input(self, *, operation: VoiceOperation) -> VoiceOperationResult:
        if invalid := self._valid(operation, Kind.FINISH_INPUT):
            return invalid
        return self._result(operation, Kind.FINISH_INPUT, Status.UNSUPPORTED, VoiceErrorCode.UNSUPPORTED)

    async def append_quiet_context(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        return await self._append("thinking", Kind.QUIET_CONTEXT, update, operation)

    async def append_spoken_result(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        return await self._append("commentary", Kind.SPOKEN_RESULT, update, operation)

    async def feed_runtime_instruction(self, update: VoiceTextUpdate, *, operation: VoiceOperation) -> VoiceOperationResult:
        return await self._append("instructions", Kind.RUNTIME_INSTRUCTION, update, operation)

    async def _append(self, channel: str, kind: Kind, update: VoiceTextUpdate,
                      operation: VoiceOperation) -> VoiceOperationResult:
        if invalid := self._valid(operation, kind):
            return invalid
        try:
            update_size = len(update.text.encode("utf-8"))
        except UnicodeEncodeError:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.INVALID_INPUT)
        if not update.text or update_size > MAX_APPEND_UTF8:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.CONTEXT_LIMIT)
        delegation = operation.correlation.provider_delegation_id
        if delegation is not None and str(delegation) not in self._known_delegations:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.INVALID_INPUT)
        event_id = str(operation.operation_id)
        if event_id in self._pending_acks or event_id in self._used_append_ids:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.INVALID_INPUT)
        if len(self._used_append_ids) >= 512:
            return self._result(operation, kind, Status.REJECTED, VoiceErrorCode.CONTEXT_LIMIT)
        self._used_append_ids.add(event_id)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_acks[event_id] = (channel, future)
        try:
            assert self._transport is not None
            async with asyncio.timeout(self._ack_timeout):
                await self._transport.send_json({"type": f"session.{channel}.append", "event_id": event_id,
                                                 "content": update.text,
                                                 "delegation_id": str(delegation) if delegation is not None else None})
                await asyncio.shield(future)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._result(operation, kind, Status.UNKNOWN, VoiceErrorCode.TIMEOUT)
        except Exception:
            return self._result(operation, kind, Status.FAILED, VoiceErrorCode.PROVIDER)
        finally:
            self._pending_acks.pop(event_id, None)
        return self._result(operation, kind, Status.COMPLETED)

    async def cancel_speech(self, *, operation: VoiceOperation, playback=None) -> VoiceOperationResult:
        if invalid := self._valid(operation, Kind.CANCEL_SPEECH):
            return invalid
        return self._result(operation, Kind.CANCEL_SPEECH, Status.UNSUPPORTED, VoiceErrorCode.UNSUPPORTED)

    async def stop(self, reason: VoiceStopReason, *, operation: VoiceOperation) -> VoiceOperationResult:
        if self._stop_task is not None:
            return replace(await asyncio.shield(self._stop_task), operation=operation)
        if self._correlation is not None and operation.correlation.session_id != self._correlation.session_id:
            return self._result(operation, Kind.STOP, Status.REJECTED, VoiceErrorCode.INVALID_STATE)
        if self._state is FrontendState.STOPPED:
            return self._result(operation, Kind.STOP, Status.COMPLETED)
        if self._state is FrontendState.NEW:
            self._correlation = operation.correlation
            self._transition(FrontendState.STOPPING)
            self._transition(FrontendState.STOPPED)
            self._stream_ended = True
            self._changed.set()
            return self._result(operation, Kind.STOP, Status.COMPLETED)
        self._stop_task = asyncio.create_task(self._stop(reason, operation), name="jarvis-live-stop")
        return await asyncio.shield(self._stop_task)

    async def _stop(self, reason: VoiceStopReason, operation: VoiceOperation) -> VoiceOperationResult:
        self._stop_requested.set()
        self._transition(FrontendState.STOPPING)
        try:
            async with asyncio.timeout(self._close_timeout):
                if self._transport is not None:
                    await self._transport.send_json({"type": "session.close", "event_id": str(operation.operation_id)})
                await self._closed.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._state is not FrontendState.STOPPED:
                self._fail(VoiceErrorCode.CLOSE_UNCONFIRMED, Kind.STOP, "session.closed not observed")
            self._ensure_cleanup()
            return self._result(operation, Kind.STOP, Status.UNKNOWN, VoiceErrorCode.CLOSE_UNCONFIRMED)
        self._ensure_cleanup(cancel_reader=False)
        return self._result(operation, Kind.STOP, Status.COMPLETED)

    def _reject_acks(self) -> None:
        for _channel, future in tuple(self._pending_acks.values()):
            if not future.done():
                future.set_exception(RuntimeError("Live session ended"))
        self._pending_acks.clear()

    async def _cleanup_transport(self, *, cancel_reader: bool = True) -> None:
        if cancel_reader and self._reader is not None and self._reader is not asyncio.current_task() and not self._reader.done():
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        if self._transport is not None:
            try:
                async with asyncio.timeout(self._close_timeout):
                    await self._transport.close()
            except Exception:
                if self._state is not FrontendState.STOPPED:
                    self._fail(VoiceErrorCode.CLOSE_UNCONFIRMED, None, "transport cleanup failed")

    def _ensure_cleanup(self, *, cancel_reader: bool = True) -> asyncio.Task[None]:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self._cleanup_transport(cancel_reader=cancel_reader), name="jarvis-live-cleanup",
            )
            self._cleanup_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return self._cleanup_task

    async def wait_transport_closed(self) -> None:
        """Wait for the adapter-owned, time-bounded transport cleanup."""

        task = self._cleanup_task or self._ensure_cleanup()
        await asyncio.shield(task)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        if self._consumer:
            raise RuntimeError("VoiceFrontend events are single-consumer")
        self._consumer = True
        try:
            while True:
                while self._events:
                    yield self._events.popleft()
                if self._stream_ended:
                    return
                self._changed.clear()
                if self._events or self._stream_ended:
                    continue
                await self._changed.wait()
        finally:
            self._consumer = False
