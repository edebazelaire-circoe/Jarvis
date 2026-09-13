from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field

import pytest

from jarvis.adapters.openai_live_frontend import OpenAILiveFrontend
from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.domain.voice_events import (
    AssistantAudioChunk, AssistantTranscriptDelta, FrontendLifecycleChanged,
    UserTranscriptDelta, VoiceDelegationRequested, VoiceFrontendFailed,
    VoiceUsageSource, VoiceUsageUpdated,
)
from jarvis.domain.voice_frontend import (
    FrontendState, ProviderDelegationId, VoiceAudioChunk, VoiceCorrelation,
    VoiceFrontendConfig, VoiceOperation, VoiceOperationId, VoiceOperationKind,
    VoiceOperationStatus, VoiceSessionId, VoiceStopReason, VoiceTextUpdate,
)


@dataclass
class FakeLiveTransport:
    incoming: asyncio.Queue = field(default_factory=asyncio.Queue)
    sent: list[dict] = field(default_factory=list)
    close_calls: int = 0

    async def send_json(self, value):
        self.sent.append(value)

    async def receive_json(self):
        value = await self.incoming.get()
        if isinstance(value, BaseException):
            raise value
        return value

    async def close(self):
        self.close_calls += 1

    def push(self, value):
        self.incoming.put_nowait(value)


SESSION = VoiceSessionId("live-incarnation")


def op(value: str, *, delegation: str | None = None) -> VoiceOperation:
    return VoiceOperation(
        VoiceOperationId(value),
        VoiceCorrelation(SESSION, provider_delegation_id=ProviderDelegationId(delegation) if delegation else None),
    )


def config(*, instructions: str = "Talk naturally") -> VoiceFrontendConfig:
    return VoiceFrontendConfig(
        DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1")),
        instructions=instructions,
    )


async def started(frontend: OpenAILiveFrontend, transport: FakeLiveTransport):
    task = asyncio.create_task(frontend.start(config(), operation=op("start-1")))
    while not transport.sent:
        await asyncio.sleep(0)
    transport.push({"type": "session.started", "event_id": "server-start", "session": {
        "id": "provider-session", "expires_at": 12345, "status": "active",
    }})
    result = await task
    assert result.status is VoiceOperationStatus.COMPLETED
    assert frontend.state is FrontendState.ACTIVE
    return result


@pytest.mark.asyncio
async def test_start_uses_live_client_delegation_and_waits_for_started():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    task = asyncio.create_task(frontend.start(config(), operation=op("start-1")))
    while not transport.sent:
        await asyncio.sleep(0)
    assert not task.done()
    message = transport.sent[0]
    assert message == {
        "type": "session.start", "event_id": "start-1", "session": {
            "model": "gpt-live-1", "instructions": "Talk naturally",
            "delegation": {"type": "client"},
            "audio": {"format": {"type": "audio/pcm", "rate": 24000}, "output": {"voice": "marin"}},
            "store": False, "input": [],
        },
    }
    transport.push({"type": "session.started", "session": {"id": "opaque", "expires_at": 99}})
    assert (await task).status is VoiceOperationStatus.COMPLETED
    assert frontend.expires_at == 99


@pytest.mark.asyncio
async def test_reader_maps_deltas_audio_delegation_and_usage_without_finals():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    iterator = frontend.events()
    assert (await anext(iterator)).payload == FrontendLifecycleChanged(FrontendState.STARTING)
    assert (await anext(iterator)).payload == FrontendLifecycleChanged(FrontendState.ACTIVE)

    transport.push({"type": "session.input_transcript.delta", "event_id": "i1", "delta": "plan ", "start_ms": 10, "end_ms": 20})
    transport.push({"type": "session.input_transcript.delta", "event_id": "i2", "delta": "B", "start_ms": 20, "end_ms": 24})
    transport.push({"type": "session.output_transcript.delta", "event_id": "o1", "delta": "Je regarde", "start_ms": 30, "end_ms": 50})
    pcm = b"\x01\x00" * 20
    transport.push({"type": "session.output_audio.delta", "delta": base64.b64encode(pcm).decode()})
    transport.push({"type": "session.delegation.created", "event_id": "d1", "offset_ms": 25,
                    "delegation": {"id": "delegation-opaque", "type": "delegation", "target": "client"}})
    transport.push({"type": "session.usage.updated", "event_id": "u1", "usage": {"seconds": 1.25},
                    "context_window": {"usage_ratio": .2}})

    events = [await anext(iterator) for _ in range(6)]
    assert isinstance(events[0].payload, UserTranscriptDelta)
    assert events[0].payload.revision == 1 and events[0].provider_interval.start_ms == 10
    assert isinstance(events[1].payload, UserTranscriptDelta) and events[1].payload.revision == 2
    assert events[0].payload.transcript_id == events[1].payload.transcript_id
    assert isinstance(events[2].payload, AssistantTranscriptDelta)
    assert isinstance(events[3].payload, AssistantAudioChunk) and events[3].payload.audio.pcm == pcm
    assert events[3].provider_event_id is None
    assert isinstance(events[4].payload, VoiceDelegationRequested)
    assert events[4].payload.context_revision == 2
    assert events[4].correlation.provider_delegation_id == "delegation-opaque"
    assert events[4].provider_interval.start_ms == events[4].provider_interval.end_ms == 25
    assert events[5].payload == VoiceUsageUpdated(VoiceUsageSource.PROVIDER_SNAPSHOT, duration_s=1.25)
    assert frontend.context_usage_ratio == .2
    await iterator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,channel", [
    ("append_quiet_context", "thinking"),
    ("append_spoken_result", "commentary"),
    ("feed_runtime_instruction", "instructions"),
])
async def test_append_waits_for_correlated_ack_without_claiming_speech(method, channel):
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    transport.sent.clear()
    call = asyncio.create_task(getattr(frontend, method)(VoiceTextUpdate("fact"), operation=op("append-1")))
    while not transport.sent:
        await asyncio.sleep(0)
    assert transport.sent == [{"type": f"session.{channel}.append", "event_id": "append-1", "content": "fact", "delegation_id": None}]
    assert not call.done()
    transport.push({"type": f"session.{channel}.appended", "client_event_id": "append-1", "start_ms": 10, "end_ms": 11})
    assert (await call).status is VoiceOperationStatus.COMPLETED


@pytest.mark.asyncio
async def test_append_requires_delegation_from_same_session_and_conservative_bound():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    unknown = await frontend.append_quiet_context(VoiceTextUpdate("fact"), operation=op("a", delegation="old"))
    oversized = await frontend.append_quiet_context(VoiceTextUpdate("é" * 251), operation=op("b"))
    assert unknown.status is VoiceOperationStatus.REJECTED
    assert oversized.status is VoiceOperationStatus.REJECTED
    assert all(message["type"] == "session.start" for message in transport.sent)


@pytest.mark.asyncio
async def test_stop_is_confirmed_only_by_session_closed_and_emits_final_usage():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    iterator = frontend.events()
    await anext(iterator); await anext(iterator)
    task = asyncio.create_task(frontend.stop(VoiceStopReason.USER, operation=op("stop-1")))
    while not any(message["type"] == "session.close" for message in transport.sent):
        await asyncio.sleep(0)
    assert not task.done()
    transport.push({"type": "session.closed", "event_id": "closed", "reason": "close_requested",
                    "session": {"id": "provider-session", "status": "active"}, "usage": {"seconds": 4.5}})
    result = await task
    assert result.status is VoiceOperationStatus.COMPLETED and result.state is FrontendState.STOPPED
    assert frontend.provider_close_reason == "close_requested" and transport.close_calls == 1
    assert (await anext(iterator)).payload == FrontendLifecycleChanged(FrontendState.STOPPING)
    assert (await anext(iterator)).payload == VoiceUsageUpdated(VoiceUsageSource.PROVIDER_FINAL, duration_s=4.5)
    assert (await anext(iterator)).payload == FrontendLifecycleChanged(FrontendState.STOPPED)
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


@pytest.mark.asyncio
async def test_eof_before_session_closed_is_unknown_and_observable():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    iterator = frontend.events()
    await anext(iterator); await anext(iterator)
    transport.push(None)
    lifecycle = await anext(iterator)
    failure = await anext(iterator)
    assert lifecycle.payload == FrontendLifecycleChanged(FrontendState.UNKNOWN_REAP_REQUIRED)
    assert isinstance(failure.payload, VoiceFrontendFailed)
    assert frontend.state is FrontendState.UNKNOWN_REAP_REQUIRED
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


@pytest.mark.asyncio
async def test_finish_input_and_native_cancel_are_explicitly_unsupported():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    finish = await frontend.finish_input(operation=op("finish"))
    cancel = await frontend.cancel_speech(operation=op("cancel"))
    assert finish.status is cancel.status is VoiceOperationStatus.UNSUPPORTED


@pytest.mark.asyncio
async def test_caller_cancellation_does_not_cancel_owned_start():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    call = asyncio.create_task(frontend.start(config(), operation=op("start-1")))
    while not transport.sent:
        await asyncio.sleep(0)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    transport.push({"type": "session.started", "session": {"id": "provider-session"}})
    for _ in range(20):
        if frontend.state is FrontendState.ACTIVE:
            break
        await asyncio.sleep(0)
    assert frontend.state is FrontendState.ACTIVE


@pytest.mark.asyncio
async def test_audio_send_has_no_commit_or_response_trigger():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport))
    await started(frontend, transport)
    transport.sent.clear()
    chunk = VoiceAudioChunk(b"\0\0" * 10)
    result = await frontend.send_audio(chunk, operation=op("audio"))
    assert result.status is VoiceOperationStatus.ACCEPTED
    assert transport.sent == [{"type": "session.input_audio.append", "event_id": "audio",
                               "audio": base64.b64encode(chunk.pcm).decode("ascii")}]
