"""12D real facade/runtime/device-bridge boundaries, controlled provider/device."""
import asyncio
import base64

import pytest

from jarvis.domain.v2 import ProtocolEnvelope, VoiceLifecycleState
from jarvis.domain.voice_events import AssistantAudioChunk, UserTranscriptDelta
from jarvis.domain.voice_events import VoiceUsageSource, VoiceUsageUpdated
from jarvis.domain.voice_frontend import FrontendState, VoiceAudioChunk, VoiceCorrelation, VoiceOperationStatus
from jarvis.adapters.openai_live_frontend import OpenAILiveFrontend
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from tests.fakes.voice_frontend import FakeVoiceFrontend
from tests.unit.test_live_delegation import ready
from tests.unit.test_v2_barge_in import FakeOutputStream, RecordingCore, build_bridge
from tests.unit.test_v2_voice_toggle import FakeCore, FakeWakeWord, RecordingJournal, RecordingSignals


async def test_cancelled_connect_owns_late_start_and_unconfirmed_stop(monkeypatch):
    import jarvis.runtime.live_frontend_session as facade_module

    connector_entered = asyncio.Event()
    release_connector = asyncio.Event()

    class Transport:
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.sent = []
            self.close_calls = 0

        async def send_json(self, value):
            self.sent.append(value)

        async def receive_json(self):
            return await self.incoming.get()

        async def close(self):
            self.close_calls += 1

    transport = Transport()
    frontends = []

    async def connector():
        connector_entered.set()
        await release_connector.wait()
        return transport

    def frontend_factory(*args, **kwargs):
        frontend = OpenAILiveFrontend(*args, **kwargs)
        frontends.append(frontend)
        return frontend

    monkeypatch.setattr(facade_module, "OpenAILiveFrontend", frontend_factory)
    call = asyncio.create_task(LiveFrontendSession.connect(
        api_key="provider-secret", voice="marin", context={}, connector=connector,
        start_timeout_s=.2, close_timeout_s=.02,
    ))
    await asyncio.wait_for(connector_entered.wait(), 1)
    call.cancel()
    release_connector.set()
    async with asyncio.timeout(1):
        while not any(item["type"] == "session.start" for item in transport.sent):
            await asyncio.sleep(0)
    transport.incoming.put_nowait({
        "type": "session.started", "event_id": "late-start",
        "session": {"id": "provider-session", "status": "active"},
    })
    with pytest.raises(asyncio.CancelledError):
        await call
    assert any(item["type"] == "session.close" for item in transport.sent)
    assert transport.close_calls == 1
    assert frontends[0].state is FrontendState.UNKNOWN_REAP_REQUIRED


def test_usage_diagnostic_is_cumulative_or_final_and_privacy_safe(tmp_path):
    frontend = FakeVoiceFrontend()
    session = LiveFrontendSession(frontend, "live-session")
    session.journal = RuntimeJournal(tmp_path)
    secret = "provider-secret-content"

    session._observe(frontend.event(UserTranscriptDelta(
        "input-transcript", secret, 1,
    ), correlation=VoiceCorrelation("live-session")))
    session._observe(frontend.event(VoiceUsageUpdated(
        VoiceUsageSource.PROVIDER_SNAPSHOT, duration_s=1.25,
    ), correlation=VoiceCorrelation("live-session")))
    session._observe(frontend.event(VoiceUsageUpdated(
        VoiceUsageSource.PROVIDER_FINAL, duration_s=4.5,
    ), correlation=VoiceCorrelation("live-session")))

    rows = [row for row in read_jsonl_tail(session.journal.trace_path)
            if row["kind"] == "voice.live.usage"]
    assert [row["data"] for row in rows] == [
        {"session_id": "live-session", "seconds": 1.25,
         "source": "provider_snapshot", "usage_type": "cumulative"},
        {"session_id": "live-session", "seconds": 4.5,
         "source": "provider_final", "usage_type": "final"},
    ]
    assert secret not in str(rows)


@pytest.mark.parametrize("confirmed", [False, True])
async def test_live_stop_result_controls_runtime_idle_offline_and_reactivation(confirmed):
    frontend = FakeVoiceFrontend(close_confirmed=confirmed)
    await ready(frontend)
    session = LiveFrontendSession(frontend, "live-session")
    wake, signals, journal = FakeWakeWord(), RecordingSignals(), RecordingJournal()
    opens = []
    async def factory(context):
        opens.append(context)
        raise AssertionError("uncertain old session must fence creation")
    runtime = PersistentVoiceRuntime(wakeword=wake, core=FakeCore(), realtime_factory=factory,
                                     signals=signals, journal=journal)
    runtime._session = session
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    signals.states.clear()  # Constructor's initial BACKGROUND predates this session.
    await runtime.mute()
    result = await session.close()
    assert result is session.stop_result
    if confirmed:
        assert result.status is VoiceOperationStatus.COMPLETED
        assert runtime._pending_canonical_close is None
        assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert signals.states[-1] == "idle"
        await runtime.close()
        assert signals.is_offline
    else:
        assert result.status is VoiceOperationStatus.UNKNOWN
        assert runtime._pending_canonical_close is session
        assert runtime.runtime.state is VoiceLifecycleState.ERROR
        await runtime.activate()
        await runtime.close()
        assert not opens and not signals.is_offline and "idle" not in signals.states
        assert not wake.resumed.is_set()
        assert runtime._pending_canonical_close is session
        assert any(event["data"].get("code") == "voice_close_unconfirmed" for event in journal.events)


def audio_event(output_id):
    return ProtocolEnvelope(message_type="realtime.audio", payload={
        "output_id": output_id, "speech_id": None, "response_id": None,
        "pcm_b64": base64.b64encode(b"\1\0" * 2400).decode(),
    })


async def test_barge_in_latches_before_device_stop_and_rejects_new_id_and_late_tail():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    session = LiveFrontendSession(frontend, "live-session")
    audio, device, core = SoundDeviceRealtimeAudio(), FakeOutputStream(), RecordingCore()
    audio._output = device
    bridge = build_bridge(audio=audio, session=session, core=core)
    first = audio_event("before-interruption")
    gate, entered = asyncio.Event(), asyncio.Event()
    original_stop = audio.stop_output
    async def held_stop():
        entered.set()
        await gate.wait()
        return await original_stop()
    try:
        bridge._note_output_received(first.payload, audio=True)
        await bridge._handle_event(ProtocolEnvelope(message_type="realtime.output_started", payload=first.payload))
        await bridge._play_audio(1, first)
        assert b"".join(device.writes) == b"\1\0" * 2400
        previous_writes = list(device.writes)
        audio.stop_output = held_stop
        interruption = asyncio.create_task(bridge._barge_in())
        await entered.wait()
        assert session.playback_suppressed
        # Already-dispatched PCM with an unseen identity must not bypass the latch.
        await bridge._play_audio(100, audio_event("queued-unseen-output"))
        gate.set()
        await interruption
        # A new input can cause the adapter to allocate another local output ID.
        session._observe(frontend.event(UserTranscriptDelta("input", "new question", 1),
            correlation=VoiceCorrelation("live-session")))
        for identity in ("after-input", "before-interruption", "another-local-output"):
            event = frontend.event(AssistantAudioChunk(VoiceAudioChunk(b"\1\0" * 2400)),
                correlation=VoiceCorrelation("live-session", output_id=identity))
            session._observe(event)
            assert list(session._legacy_events(event)) == []
            await bridge._handle_event(ProtocolEnvelope(message_type="realtime.output_started", payload=audio_event(identity).payload))
            await bridge._play_audio(101, audio_event(identity))
        assert device.writes == previous_writes and not bridge._playing
        assert session.playback_suppressed and not core.brain_turns and not core.tool_calls
    finally:
        gate.set()
        await audio.close()
        await session.close()


async def test_interruption_during_async_preplay_callback_cannot_write_after_latch():
    frontend = FakeVoiceFrontend()
    await ready(frontend)
    session = LiveFrontendSession(frontend, "live-session")
    audio, device = SoundDeviceRealtimeAudio(), FakeOutputStream()
    audio._output = device
    bridge = build_bridge(audio=audio, session=session, core=RecordingCore())
    entered, release = asyncio.Event(), asyncio.Event()
    async def callback():
        entered.set()
        await release.wait()
    bridge.on_speaking = callback
    pending = asyncio.create_task(bridge._play_audio(1, audio_event("selected")))
    try:
        await entered.wait()
        await bridge._barge_in()
        release.set()
        await pending
        assert session.playback_suppressed and device.writes == []
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await audio.close()
        await session.close()
