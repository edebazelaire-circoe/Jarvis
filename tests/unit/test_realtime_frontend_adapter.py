"""Real low-level normalization and canonical adapter; wire doubles only."""
from __future__ import annotations

import asyncio
import base64

import aiohttp
import pytest

from jarvis.adapters.openai_realtime import OpenAIRealtimeSession
from jarvis.adapters.openai_realtime_frontend import OpenAIRealtimeFrontend
from jarvis.domain.voice_architecture import SimpleVoiceConfig, VoiceModelRef
from jarvis.domain.voice_events import (
    AssistantTranscriptCompleted,
    FrontendLifecycleChanged, VoiceFrontendFailed, VoiceToolCallRequested, VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    FrontendState, VoiceAudioChunk, VoiceCorrelation, VoiceErrorCode, VoiceFrontendConfig,
    VoiceOperation, VoiceOperationStatus, VoiceStopReason, VoiceTextUpdate, bounded_json_object,
)


class Wire:
    def __init__(self):
        self.inbound = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.close_count = 0
        self.readers = 0
        self.fail_send = False
        self.close_gate = None

    def push(self, **event):
        self.inbound.put_nowait(event)

    async def send_json(self, event):
        if self.fail_send:
            raise ConnectionError("secret provider body must not escape")
        self.sent.append(event)

    async def ping(self):
        return None

    async def close(self):
        self.close_count += 1
        if self.close_gate is not None:
            await self.close_gate.wait()
        self.closed = True
        self.inbound.put_nowait(None)

    def __aiter__(self):
        async def stream():
            self.readers += 1
            while True:
                value = await self.inbound.get()
                if value is None:
                    return
                class Message:
                    type = aiohttp.WSMsgType.TEXT
                    def json(self):
                        return value
                yield Message()
        return stream()


def operation():
    return VoiceOperation("operation", VoiceCorrelation("session"))


def config():
    return VoiceFrontendConfig(SimpleVoiceConfig(VoiceModelRef("openai", "gpt-realtime-2.1-mini")), instructions="instructions")


async def started(*, queue_limit=256):
    wire = Wire()
    session = OpenAIRealtimeSession(wire, object(), owns_http=False)
    async def connect(_):
        return session
    frontend = OpenAIRealtimeFrontend(connect, ack_timeout_s=.05, queue_limit=queue_limit)
    wire.push(type="session.updated", session={"id": "provider-session", "instructions": "instructions"})
    result = await frontend.start(config(), operation=operation())
    assert result.status is VoiceOperationStatus.COMPLETED
    return frontend, wire


async def collect_stopped(frontend):
    await frontend.stop(VoiceStopReason.USER, operation=operation())
    return [event async for event in frontend.events()]


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_start_waits_for_matching_update_and_cancellation_closes():
    wire = Wire()
    session = OpenAIRealtimeSession(wire, object(), owns_http=False)
    async def connect(_):
        return session
    frontend = OpenAIRealtimeFrontend(connect)
    task = asyncio.create_task(frontend.start(config(), operation=operation()))
    wire.push(type="session.created", session={"id": "provider"})
    wire.push(type="session.updated", session={"instructions": "different"})
    await settle()
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert wire.closed and wire.close_count == 1
    assert frontend.state is FrontendState.STOPPED


@pytest.mark.parametrize("failure, expected", [(TimeoutError(), VoiceErrorCode.TIMEOUT), (ConnectionError(), VoiceErrorCode.TRANSPORT)])
async def test_failed_start_terminates_events(failure, expected):
    async def connect(_):
        raise failure
    frontend = OpenAIRealtimeFrontend(connect)
    result = await frontend.start(config(), operation=operation())
    events = await asyncio.wait_for(_events(frontend), .2)
    assert result.error.code is expected
    assert events[-1].payload.state is FrontendState.STOPPED


async def _events(frontend):
    return [event async for event in frontend.events()]


async def test_stop_is_shared_and_survives_caller_cancellation():
    frontend, wire = await started()
    wire.close_gate = asyncio.Event()
    first = asyncio.create_task(frontend.stop(VoiceStopReason.USER, operation=operation()))
    second = asyncio.create_task(frontend.stop(VoiceStopReason.USER, operation=operation()))
    await settle()
    first.cancel()
    wire.close_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await second).status is VoiceOperationStatus.COMPLETED
    assert wire.close_count == 1


async def test_quiet_context_has_no_response_create_and_command_error_is_typed():
    frontend, wire = await started()
    result = await frontend.append_quiet_context(VoiceTextUpdate("untrusted backend fact"), operation=operation())
    assert result.status is VoiceOperationStatus.ACCEPTED
    assert [item["type"] for item in wire.sent] == ["conversation.item.create"]
    assert wire.sent[0]["item"]["role"] == "user"
    wire.fail_send = True
    result = await frontend.send_audio(VoiceAudioChunk(bytes(480)), operation=operation())
    assert result.status is VoiceOperationStatus.FAILED
    assert result.error.code is VoiceErrorCode.TRANSPORT
    assert "secret" not in repr(result)
    assert wire.closed


async def test_one_wire_reader_multi_item_transcripts_and_tool_lineage():
    frontend, wire = await started()
    wire.push(type="response.created", response={"id": "response"})
    for item in ("audio-a", "audio-b"):
        wire.push(type="response.output_audio.delta", response_id="response", item_id=item,
                  delta=base64.b64encode(bytes(480)).decode())
        wire.push(type="response.output_audio_transcript.done", response_id="response", item_id=item, transcript=item)
    wire.push(type="response.function_call_arguments.done", response_id="response", item_id="tool-item",
              call_id="call", name="lookup", arguments='{"query":"value"}')
    wire.push(type="response.done", response={"id": "response", "status": "completed", "usage": {"input_tokens": 2, "output_tokens": 3}})
    await settle()
    events = await collect_stopped(frontend)
    assert wire.readers == 1
    texts = [event for event in events if isinstance(event.payload, AssistantTranscriptCompleted)]
    assert [event.payload.text for event in texts] == ["audio-a", "audio-b"]
    assert texts[0].payload.transcript_id != texts[1].payload.transcript_id
    call = next(event for event in events if isinstance(event.payload, VoiceToolCallRequested))
    assert call.correlation.provider_input_id is None and call.correlation.turn_id is None
    assert call.correlation.provider_output_id == "response"
    assert call.correlation.output_id != "response"
    assert call.correlation.provider_item_id is None


async def test_malformed_tool_arguments_never_become_empty_valid_call():
    frontend, wire = await started()
    wire.push(type="response.created", response={"id": "response"})
    wire.push(type="response.function_call_arguments.done", response_id="response", call_id="call", name="lookup", arguments='{bad')
    await settle()
    events = await collect_stopped(frontend)
    assert not any(isinstance(event.payload, VoiceToolCallRequested) for event in events)
    assert any(isinstance(event.payload, VoiceFrontendFailed) for event in events)


async def test_missing_usage_stays_unknown_and_duplicate_response_is_not_counted():
    frontend, wire = await started()
    for response, usage in (("a", None), ("b", {"input_tokens": 2, "output_tokens": 3}), ("b", {"input_tokens": 2, "output_tokens": 3})):
        wire.push(type="response.created", response={"id": response})
        wire.push(type="response.done", response={"id": response, "status": "completed", "usage": usage})
    await settle()
    values = [event.payload for event in await collect_stopped(frontend) if isinstance(event.payload, VoiceUsageUpdated)]
    assert len(values) == 2
    assert values[-1].input_tokens is None and values[-1].output_tokens is None


async def test_overflow_retains_failure_and_terminal():
    frontend, wire = await started(queue_limit=3)
    for number in range(6):
        wire.push(type="response.created", response={"id": str(number)})
    await settle()
    events = await collect_stopped(frontend)
    assert any(isinstance(event.payload, VoiceFrontendFailed) for event in events)
    assert isinstance(events[-1].payload, FrontendLifecycleChanged)
    assert events[-1].payload.state is FrontendState.STOPPED


@pytest.mark.parametrize("value", ['{"x":1e999}', '{"x":{"y":[1e999]}}', '{"x":NaN}', '{"x":1,"x":2}'])
def test_tool_json_is_finite_and_unambiguous(value):
    with pytest.raises(ValueError):
        bounded_json_object(value)


@pytest.mark.parametrize("phase", ["connect", "update", "ack"])
async def test_start_cancellation_cleans_wire_but_preserves_shared_http(phase):
    wire = Wire()
    entered = asyncio.Event()
    block = asyncio.Event()
    class Http:
        closed = False
        async def ws_connect(self, *args, **kwargs):
            if phase == "connect":
                entered.set()
                await block.wait()
            return wire
        async def close(self):
            self.closed = True
    http = Http()
    original_send = wire.send_json
    async def send(event):
        if phase == "update":
            entered.set()
            await block.wait()
        await original_send(event)
        entered.set()
    wire.send_json = send
    async def connector(_):
        return await OpenAIRealtimeSession.connect(api_key="test-only", model="gpt-realtime-2.1-mini",
                    voice="alloy", context={}, session=http)
    frontend = OpenAIRealtimeFrontend(connector)
    task = asyncio.create_task(frontend.start(config(), operation=operation()))
    await asyncio.wait_for(entered.wait(), .5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not http.closed
    assert wire.closed is (phase != "connect")
    assert frontend.state is FrontendState.STOPPED


async def test_close_timeout_reports_unknown_not_stopped():
    frontend, wire = await started()
    frontend._close_timeout = .01
    wire.close_gate = asyncio.Event()
    result = await frontend.stop(VoiceStopReason.USER, operation=operation())
    assert result.status is VoiceOperationStatus.UNKNOWN
    assert frontend.state is FrontendState.UNKNOWN_REAP_REQUIRED


async def test_missing_ack_timeout_closes_and_finishes_iterator():
    wire = Wire()
    async def connector(_):
        return OpenAIRealtimeSession(wire, object(), owns_http=False)
    frontend = OpenAIRealtimeFrontend(connector, ack_timeout_s=.01)
    result = await frontend.start(config(), operation=operation())
    assert result.error.code is VoiceErrorCode.TIMEOUT and wire.closed
    events = await asyncio.wait_for(_events(frontend), .2)
    assert events[-1].payload.state is FrontendState.STOPPED


@pytest.mark.parametrize("code, expected", [("invalid_api_key", VoiceErrorCode.AUTHENTICATION), ("rate_limit_exceeded", VoiceErrorCode.RATE_LIMIT)])
async def test_provider_error_before_start_ack_keeps_verified_error_class(code, expected):
    wire = Wire()
    wire.push(type="error", error={"code": code, "message": "must remain private"})
    async def connector(_):
        return OpenAIRealtimeSession(wire, object(), owns_http=False)
    frontend = OpenAIRealtimeFrontend(connector)
    result = await frontend.start(config(), operation=operation())
    assert result.error.code is expected and wire.closed
    assert "private" not in repr(result)
    await frontend.stop(VoiceStopReason.ERROR, operation=operation())
