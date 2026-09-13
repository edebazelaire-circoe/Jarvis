"""Independent Task13C composition checks; no provider or device access."""
import asyncio
import base64
import sys
from types import SimpleNamespace

import pytest

from jarvis import app
from jarvis.domain.voice_architecture import DuplexVoiceConfig, VoiceModelRef
from jarvis.runtime.voice_architecture_config import VoiceArchitectureSettings
from tests.unit.test_app import _StopVoice, _voice_startup


async def eventually(predicate, timeout=1):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.005)


@pytest.fixture
async def live_idle_bridge(monkeypatch):
    from jarvis.runtime.live_frontend_session import LiveFrontendSession
    from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
    from tests.fakes.audio_device import BufferedInputStream, BufferedOutputStream
    from tests.integration.test_live_duplex_session import LiveWire
    from tests.unit.test_v2_barge_in import RecordingCore

    device = BufferedOutputStream()
    microphone = BufferedInputStream()
    callbacks = {}

    def input_stream(**kwargs):
        callbacks["input"] = kwargs["callback"]
        return microphone

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        RawInputStream=input_stream, RawOutputStream=lambda **kwargs: device,
    ))
    wire = LiveWire()
    session = await LiveFrontendSession.connect(
        api_key="controlled", voice="marin", context={},
        connector=lambda: asyncio.sleep(0, result=wire), close_timeout_s=.1,
    )
    audio = SoundDeviceRealtimeAudio(device_wait_s=.2)
    bridge = RealtimeConversationBridge(
        core=RecordingCore(), session=session, conversation_id="conversation-1", audio=audio,
        on_addressed=lambda: None, on_mute=lambda: None,
        continuous=True, auto_turn=True, direct_conversation=True,
    )
    task = asyncio.create_task(bridge.run())
    try:
        wire.push({"type": "session.input_transcript.delta", "event_id": "input-ready",
                   "delta": "provisional", "start_ms": 0, "end_ms": 1})
        await eventually(lambda: session.input_observation_revision == 1)
        yield SimpleNamespace(bridge=bridge, audio=audio, device=device, microphone=microphone,
                              callback=callbacks["input"], wire=wire, session=session)
    finally:
        device.consume()
        task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
        await asyncio.wait_for(session.close(), 1)


def idle_runtime(monkeypatch, evidence, *, continuation=False):
    from jarvis.domain.v2 import VoiceLifecycleState
    from jarvis.domain.voice_architecture import VoiceArchitectureId
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from tests.unit.test_v2_voice_activity import FakeClock
    from tests.unit.test_v2_voice_toggle import FakeCore, FakeWakeWord

    async def no_open(context):
        raise AssertionError("Policy test cannot open provider")

    clock = FakeClock()
    runtime = PersistentVoiceRuntime(
        wakeword=FakeWakeWord(), core=FakeCore(), realtime_factory=no_open,
        clock=clock, active_timeout_s=5, auto_turn=True,
        conversation_architecture=VoiceArchitectureId.DUPLEX,
    )
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    runtime._bridge = SimpleNamespace(live_idle_evidence=lambda: evidence)
    runtime._speech = SimpleNamespace(immediate_continuation_pending=continuation)
    stops = []

    async def stop(reason):
        stops.append(reason)

    monkeypatch.setattr(runtime, "mute", stop)
    return runtime, clock, stops


@pytest.mark.parametrize("idle_seconds", [5.0, 37.0, 3600.0])
async def test_duplex_effective_idle_never_inherits_legacy_disabled_timeout(
    tmp_path, monkeypatch, idle_seconds,
):
    mode = DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"), idle_timeout_s=idle_seconds)
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={
        "voice_architecture": VoiceArchitectureSettings(mode).to_dict(),
        "active_timeout_s": 0,
    })
    with pytest.raises(_StopVoice):
        await app._run_voice_v2()
    assert captured["active_timeout_s"] == idle_seconds


async def test_legacy_disabled_timeout_remains_disabled(tmp_path, monkeypatch):
    captured = _voice_startup(tmp_path, monkeypatch, env_arch=None, overrides={
        "voice_arch": "legacy", "active_timeout_s": 0,
    })
    with pytest.raises(_StopVoice):
        await app._run_voice_v2()
    assert captured["active_timeout_s"] == 0


async def test_visual_bus_failure_cannot_skip_live_idle_supervision():
    checked = asyncio.Event()

    class BrokenSignals:
        def heartbeat(self):
            raise PermissionError("controlled visual bus unavailable")

    class Voice:
        async def check_timeout(self):
            checked.set()
            return False

    task = asyncio.create_task(app._voice_timeout_loop(Voice(), BrokenSignals()))
    try:
        await asyncio.wait_for(checked.wait(), 2.5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_core_production_injects_sideband_closer_without_network_or_secret_logs(
    tmp_path, monkeypatch,
):
    from jarvis.adapters.openai_live_sideband import (
        AiohttpLiveSidebandTransport, OpenAILiveSidebandCloser,
    )
    from jarvis.core import v2_app
    from jarvis.protocol import server
    from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail

    secret = "controlled-secret-never-log-this"
    root = tmp_path / "runtime"
    monkeypatch.setenv("JARVIS_RUNTIME_DIR", str(root))
    monkeypatch.setenv("JARVIS_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setattr(app, "_announce_calendar_backend", lambda *args: None)
    monkeypatch.setattr(app, "_calendar_backend_from_env", lambda: None)
    monkeypatch.setattr(app, "_drive_backend_from_env", lambda: None)
    captured = {}

    async def forbidden_network(*args, **kwargs):
        raise AssertionError("Composition cannot open provider transport")

    monkeypatch.setattr(AiohttpLiveSidebandTransport, "connect", forbidden_network)

    async def backend_close():
        captured["backend_closed"] = True

    monkeypatch.setattr(app, "_brain_backend_from_env", lambda: SimpleNamespace(
        base_url="http://127.0.0.1:9999", close=backend_close,
    ))

    class Core:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def start(self):
            pass

        async def wait(self):
            pass

        async def stop(self):
            captured["core_stopped"] = True

    class Server:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    monkeypatch.setattr(v2_app, "JarvisCoreApplication", Core)
    monkeypatch.setattr(server, "LocalProtocolServer", Server)
    assert await app._run_core_v2() == 0
    assert isinstance(captured.get("live_sideband_closer"), OpenAILiveSidebandCloser)
    assert captured["core_stopped"] and captured["backend_closed"]
    rows = read_jsonl_tail(RuntimeJournal(root).trace_path)
    assert secret not in str(rows)


async def test_unconfirmed_closed_bridge_does_not_poll_stop_in_a_hot_loop(monkeypatch):
    from jarvis.domain.v2 import VoiceLifecycleState
    from jarvis.runtime.live_frontend_session import LiveFrontendSession
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
    from tests.fakes.voice_frontend import FakeVoiceFrontend
    from tests.unit.test_live_delegation import ready
    from tests.unit.test_v2_voice_toggle import FakeCore, FakeWakeWord

    frontend = FakeVoiceFrontend(close_confirmed=False)
    await ready(frontend)
    session = LiveFrontendSession(frontend, "live-session")

    async def no_open(context):
        raise AssertionError("Pending session cannot be replaced")

    runtime = PersistentVoiceRuntime(
        wakeword=FakeWakeWord(), core=FakeCore(), realtime_factory=no_open,
    )
    runtime._session = session
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    await runtime.mute()
    assert runtime._pending_canonical_close is session
    calls = []
    original_mute = runtime.mute

    async def counted_mute(*args, **kwargs):
        calls.append(None)
        # Instrument a scheduling yield so an actual hot loop cannot hang the
        # test runner; this does not add the required production retry cadence.
        await asyncio.sleep(0)
        return await original_mute(*args, **kwargs)

    monkeypatch.setattr(runtime, "mute", counted_mute)
    task = asyncio.create_task(runtime.run())
    try:
        await asyncio.sleep(.05)
        assert len(calls) <= 3, "Unchanged UNKNOWN state is polling Stop without backoff"
    finally:
        task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)


@pytest.mark.parametrize("sensor,device,speaking,output,continuation", [
    (False, True, False, False, False),
    (True, False, False, False, False),
    (True, True, True, False, False),
    (True, True, False, True, False),
    (True, True, False, False, True),
])
async def test_public_idle_evidence_inhibits_premature_close(
    monkeypatch, sensor, device, speaking, output, continuation,
):
    from jarvis.domain.live_idle import LiveIdleEvidence

    runtime, clock, stops = idle_runtime(
        monkeypatch, LiveIdleEvidence(sensor, device, speaking, output), continuation=continuation,
    )
    clock.advance(60)
    assert await runtime.check_timeout() is False
    assert stops == []


async def test_background_job_activity_cannot_renew_duplex_idle(monkeypatch):
    from jarvis.domain.live_idle import LiveIdleEvidence
    from jarvis.domain.voice_frontend import VoiceStopReason

    runtime, clock, stops = idle_runtime(monkeypatch, LiveIdleEvidence(True, True, False, False))
    for _ in range(6):
        clock.advance(1)
        await runtime.brain_activity()
    assert await runtime.check_timeout() is True
    assert stops == [VoiceStopReason.IDLE]


async def test_corrupt_idle_evidence_is_unknown_not_permission_to_close(monkeypatch):
    runtime, clock, stops = idle_runtime(monkeypatch, {
        "sensor_known": True, "device_known": True, "user_speaking": False, "output_pending": False,
    })
    clock.advance(60)
    assert await runtime.check_timeout() is False
    assert stops == []


async def test_live_provider_reader_does_not_certify_missing_microphone_sensor(live_idle_bridge):
    case = live_idle_bridge
    assert not case.microphone.closed  # Native stream exists, but delivered no callback.
    assert case.session.input_observation_revision == 1  # Provider reader is running.
    assert case.bridge.live_idle_evidence().sensor_known is False


async def test_unclassified_live_microphone_energy_is_not_certified_silence(live_idle_bridge):
    case = live_idle_bridge
    case.callback(b"\xff\x7f" * 1200, 1200, None, None)
    await eventually(lambda: case.audio.captured_bytes > 0)
    evidence = case.bridge.live_idle_evidence()
    assert not evidence.sensor_known or evidence.user_speaking


async def test_live_device_buffer_drains_without_a_provider_response_done(live_idle_bridge):
    case = live_idle_bridge
    pcm = b"\x01\x00" * 2400
    case.wire.push({"type": "session.output_audio.delta", "event_id": "output-only",
                    "delta": base64.b64encode(pcm).decode()})
    await eventually(lambda: case.device.queued_bytes == len(pcm))
    assert case.bridge.live_idle_evidence().output_pending
    # No provider output-final or response.done exists. The local device owner
    # must establish quiescence separately; queue-empty/write-return isn't proof.
    await eventually(case.device.draining.is_set)
    assert case.device.played_bytes == 0
    assert case.bridge.live_idle_evidence().output_pending
    case.device.consume()
    await eventually(lambda: not case.bridge.live_idle_evidence().output_pending)
    assert case.device.played_bytes == len(pcm)
    assert not case.microphone.closed
    assert not any(message["type"].startswith("response.") for message in case.wire.sent)


async def test_live_late_native_drain_is_reconciled_after_bounded_wait(live_idle_bridge):
    case = live_idle_bridge
    case.audio.device_wait_s = .02
    pcm = b"\x01\x00" * 2400
    case.wire.push({"type": "session.output_audio.delta", "event_id": "slow-output",
                   "delta": base64.b64encode(pcm).decode()})
    await eventually(case.device.draining.is_set)
    await asyncio.sleep(.06)  # The public device wait has timed out; native owner survives.
    assert case.device.queued_bytes == len(pcm)
    assert case.bridge.live_idle_evidence().output_pending
    case.device.consume()
    await eventually(lambda: case.device.native is None)
    await eventually(lambda: not case.bridge.live_idle_evidence().output_pending)
    assert case.device.calls.count("stop") == 1
    assert not case.microphone.closed


async def test_expired_unstarted_speech_is_not_an_unbounded_immediate_continuation():
    from tests.unit.test_v2_speech_scheduler import (
        FakeClock, FakeCore, FakeVoiceSession, build_scheduler, speech_envelope,
    )

    class UnconfirmedCancelSession(FakeVoiceSession):
        async def invalidate_unstarted_output(self, output_id):
            # Provider cleanup can remain unknown; that is separate from a
            # bounded expectation that an utterance should happen immediately.
            raise RuntimeError("controlled provider cancel unconfirmed")

    session = UnconfirmedCancelSession()
    scheduler = build_scheduler(FakeCore(), session, clock=FakeClock(), output_timeout_s=.3)
    await scheduler.start()
    try:
        await scheduler.handle_core_event(speech_envelope("Short pending utterance", ttl_s=2))
        await eventually(lambda: len(session.spoken) == 1)
        assert scheduler.immediate_continuation_pending
        deadline = scheduler.immediate_continuation_until
        assert isinstance(deadline, float)
        assert asyncio.get_running_loop().time() < deadline <= asyncio.get_running_loop().time() + .31
        await asyncio.sleep(.35)
        assert not scheduler.immediate_continuation_pending
        assert scheduler.immediate_continuation_until is None
        # Expiration of the expectation must not claim a provider completion.
        assert session.active_output_id is not None
    finally:
        await asyncio.wait_for(scheduler.stop(), 1)


async def test_real_capture_local_speech_while_jarvis_silent_inhibits_idle(
    live_idle_bridge, monkeypatch,
):
    from jarvis.audio.duplex import CaptureProcessor
    from tests.unit.test_voice_duplex import tone

    case = live_idle_bridge
    processor = CaptureProcessor(capture_rate=24000, render_rate=24000)
    case.audio.capture = processor
    pcm = tone(.1, amplitude=.3)
    case.callback(pcm, len(pcm) // 2, None, None)
    await eventually(lambda: case.audio.captured_bytes >= len(pcm))
    # Actual detector semantics: near_end_active is a far-end interruption
    # latch; last_near also recognizes local energy when JARVIS is silent.
    assert processor.detector.last_near
    assert not processor.near_end_active
    evidence = case.bridge.live_idle_evidence()
    assert evidence.sensor_known
    assert evidence.user_speaking
    runtime, clock, stops = idle_runtime(monkeypatch, evidence)
    runtime._bridge = case.bridge
    clock.advance(60)
    assert await runtime.check_timeout() is False
    assert stops == []
