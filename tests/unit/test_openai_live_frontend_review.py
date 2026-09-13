"""Independent Live adapter regressions; controlled transport, no provider calls."""
import asyncio
import base64
from contextlib import asynccontextmanager

import pytest

from jarvis.adapters.openai_live_frontend import OpenAILiveFrontend
from jarvis.domain.voice_events import AssistantAudioChunk, UserTranscriptDelta
from jarvis.domain.voice_frontend import FrontendState, VoiceOperationStatus, VoiceStopReason, VoiceTextUpdate
from tests.unit.test_openai_live_frontend import FakeLiveTransport, config, op, started


async def dispose(frontend):
    tasks = [task for task in (frontend._reader, frontend._start_task, frontend._stop_task) if task]
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def active():
    transport = FakeLiveTransport()
    frontend = OpenAILiveFrontend(lambda: asyncio.sleep(0, result=transport),
        start_timeout_s=.05, ack_timeout_s=.02, close_timeout_s=.01)
    await started(frontend, transport)
    try:
        yield frontend, transport
    finally:
        await dispose(frontend)


async def tick():
    for _ in range(10):
        await asyncio.sleep(0)


async def test_close_from_another_session_cannot_confirm_shutdown():
    async with active() as (frontend, transport):
        transport.push({"type": "session.closed", "reason": "close_requested",
            "session": {"id": "another-session", "status": "active"}, "usage": {"seconds": 1}})
        await tick()
        assert frontend.state is not FrontendState.STOPPED
        assert not frontend._closed.is_set()


async def test_duplicate_started_cannot_replace_provider_identity_or_model():
    async with active() as (frontend, transport):
        transport.push({"type": "session.started", "session": {"id": "replacement", "model": "wrong-model"}})
        await tick()
        assert frontend._correlation.provider_session_id == "provider-session"
        assert frontend.state is not FrontendState.ACTIVE


async def test_wrong_append_channel_ack_does_not_complete_thinking():
    async with active() as (frontend, transport):
        call = asyncio.create_task(frontend.append_quiet_context(VoiceTextUpdate("fact"), operation=op("append")))
        await tick()
        transport.push({"type": "session.commentary.appended", "client_event_id": "append", "start_ms": 1, "end_ms": 2})
        result = await call
        assert result.status is not VoiceOperationStatus.COMPLETED


async def test_duplicate_provider_fragment_does_not_duplicate_transcript():
    async with active() as (frontend, transport):
        fragment = {"type": "session.input_transcript.delta", "event_id": "same-event",
                    "delta": "go", "start_ms": 1, "end_ms": 2}
        transport.push(fragment)
        transport.push(fragment)
        await tick()
        deltas = [event.payload for event in frontend._events if isinstance(event.payload, UserTranscriptDelta)]
        assert [(value.delta, value.revision) for value in deltas] == [("go", 1)]


async def test_valid_hundred_millisecond_audio_frame_remains_exact():
    async with active() as (frontend, transport):
        pcm = b"\1\0" * 2400
        transport.push({"type": "session.output_audio.delta", "delta": base64.b64encode(pcm).decode()})
        await tick()
        assert frontend.state is FrontendState.ACTIVE
        chunks = [event.payload.audio.pcm for event in frontend._events if isinstance(event.payload, AssistantAudioChunk)]
        assert b"".join(chunks) == pcm


async def test_connector_finishing_after_stop_never_starts_or_reactivates_live():
    gate = asyncio.Event()
    transport = FakeLiveTransport()
    async def connector():
        await gate.wait()
        return transport
    frontend = OpenAILiveFrontend(connector, start_timeout_s=.1, close_timeout_s=.01)
    call = asyncio.create_task(frontend.start(config(), operation=op("start")))
    try:
        await tick()
        stopped = await frontend.stop(VoiceStopReason.USER, operation=op("stop"))
        assert stopped.state is not FrontendState.ACTIVE
        gate.set()
        await tick()
        transport.push({"type": "session.started", "session": {"id": "late-provider"}})
        await tick()
        assert not any(message["type"] == "session.start" for message in transport.sent)
        assert frontend.state is not FrontendState.ACTIVE
    finally:
        gate.set()
        await dispose(frontend)
        await asyncio.gather(call, return_exceptions=True)


async def test_close_deadline_includes_blocked_transport_send():
    async with active() as (frontend, transport):
        gate = asyncio.Event()
        original = transport.send_json
        async def send(message):
            await gate.wait()
            await original(message)
        transport.send_json = send
        call = asyncio.create_task(frontend.stop(VoiceStopReason.USER, operation=op("stop")))
        try:
            await asyncio.sleep(.06)
            returned_within_bound = call.done()
        finally:
            gate.set()
            await asyncio.wait_for(call, 1)
        assert returned_within_bound


async def test_unknown_append_retry_with_same_operation_does_not_resend_content():
    async with active() as (frontend, transport):
        update, operation = VoiceTextUpdate("fact"), op("same-operation")
        first = await frontend.append_quiet_context(update, operation=operation)
        assert first.status is VoiceOperationStatus.UNKNOWN
        await frontend.append_quiet_context(update, operation=operation)
        assert len([message for message in transport.sent if message["type"] == "session.thinking.append"]) == 1


@pytest.mark.parametrize("boundary", ["connector", "start_send"])
async def test_start_deadline_covers_connection_and_initial_send(boundary):
    gate = asyncio.Event()
    transport = FakeLiveTransport()
    async def connector():
        if boundary == "connector":
            await gate.wait()
        return transport
    original = transport.send_json
    async def send(message):
        if message["type"] == "session.start":
            await gate.wait()
        await original(message)
    if boundary == "start_send":
        transport.send_json = send
    frontend = OpenAILiveFrontend(connector, start_timeout_s=.01, close_timeout_s=.01)
    call = asyncio.create_task(frontend.start(config(), operation=op("start")))
    try:
        await asyncio.sleep(.06)
        bounded = call.done()
    finally:
        gate.set()
        await dispose(frontend)
        await asyncio.gather(call, return_exceptions=True)
    assert bounded


async def test_append_deadline_covers_blocked_send():
    async with active() as (frontend, transport):
        gate = asyncio.Event()
        original = transport.send_json
        async def send(message):
            await gate.wait()
            await original(message)
        transport.send_json = send
        call = asyncio.create_task(frontend.append_quiet_context(VoiceTextUpdate("fact"), operation=op("append")))
        try:
            await asyncio.sleep(.07)
            bounded = call.done()
        finally:
            gate.set()
            await asyncio.wait_for(call, 1)
        assert bounded


async def test_stop_deadline_covers_blocked_local_transport_cleanup():
    async with active() as (frontend, transport):
        gate = asyncio.Event()
        original = transport.close
        async def close():
            await gate.wait()
            await original()
        transport.close = close
        call = asyncio.create_task(frontend.stop(VoiceStopReason.USER, operation=op("stop")))
        try:
            await asyncio.sleep(.06)
            bounded = call.done()
        finally:
            gate.set()
            await asyncio.wait_for(call, 1)
        assert bounded


async def test_overflow_retains_failure_and_starts_owned_transport_cleanup():
    async with active() as (frontend, transport):
        frontend._queue_limit = 2  # Already occupied by STARTING and ACTIVE.
        transport.push({"type": "session.input_transcript.delta", "event_id": "overflow",
            "delta": "go", "start_ms": 1, "end_ms": 2})
        await tick()
        assert frontend.state is FrontendState.UNKNOWN_REAP_REQUIRED
        assert transport.close_calls == 1
        assert frontend._reader.done()


async def test_repeated_start_after_confirmed_stop_does_not_return_stale_active_result():
    async with active() as (frontend, transport):
        transport.push({"type": "session.closed", "reason": "close_requested",
            "session": {"id": "provider-session", "status": "active"}, "usage": {"seconds": 1}})
        await tick()
        result = await frontend.start(config(), operation=op("second-start"))
        assert result.state is not FrontendState.ACTIVE
        assert result.status is not VoiceOperationStatus.COMPLETED


@pytest.mark.parametrize("identity", ["bad\nidentity", "x" * 257])
async def test_provider_event_identity_must_fit_canonical_codec(identity):
    async with active() as (frontend, transport):
        transport.push({"type": "session.input_transcript.delta", "event_id": identity,
            "delta": "go", "start_ms": 1, "end_ms": 2})
        await tick()
        assert frontend.state is not FrontendState.ACTIVE
        assert not any(isinstance(event.payload, UserTranscriptDelta) for event in frontend._events)


async def test_invalid_unicode_append_returns_typed_rejection_without_send():
    async with active() as (frontend, transport):
        result = await frontend.append_quiet_context(VoiceTextUpdate("\ud800"), operation=op("invalid-unicode"))
        assert result.status is VoiceOperationStatus.REJECTED
        assert not any(message["type"] == "session.thinking.append" for message in transport.sent)
