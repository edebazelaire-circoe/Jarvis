"""Task07 actual wrapper/device-buffer ownership; no physical playback claim."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from jarvis.domain.voice_playback import VoiceAudioPart, VoiceAudioPartExtent, VoiceDevicePlaybackStatus, VoicePlaybackManifest
from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.output_admission import OutputAdmission, OutputAdmissionState
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture
from tests.fakes.audio_device import BufferedInputStream, BufferedOutputStream
from tests.unit.test_voice_duplex import build_bridge, ControllableSession, GuardedAudio, RecordingJournal
from tests.unit.test_v2_voice_toggle import FakeCore, FakeWakeWord, FakeRealtimeSession


PART = VoiceAudioPart("item", 0, 0)
PCM = b"\1\0" * 2400
MANIFEST = VoicePlaybackManifest("session", "output", "response", (VoiceAudioPartExtent(PART, len(PCM)),), len(PCM))


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


def audio_pair(tmp_path=None, wait=.25):
    journal = RuntimeJournal(tmp_path) if tmp_path else None
    audio = SoundDeviceRealtimeAudio(device_wait_s=wait, journal=journal)
    stream = BufferedOutputStream()
    audio._output = stream
    audio._input = BufferedInputStream()
    audio._output_latency_ms = 200
    return audio, stream, journal


async def write(audio, *, part=PART, output="output", response="response", pcm=PCM):
    audio.set_active_output(output_id=output, response_id=response, item_id=part.item_id,
                            content_index=part.content_index, output_index=part.output_index)
    await audio.play_b64(base64.b64encode(pcm).decode())


async def test_buffered_natural_drain_coalesces_and_cannot_reuse_complete_after_stop(tmp_path):
    audio, stream, journal = audio_pair(tmp_path)
    first = second = None
    try:
        await write(audio)
        assert audio.played_output_ms == 0 and stream.queued_bytes == len(PCM)
        first = asyncio.create_task(audio.complete_output(MANIFEST))
        await until(stream.draining.is_set)
        second = asyncio.create_task(audio.complete_output(MANIFEST))
        await asyncio.sleep(.01)
        assert not first.done() and not second.done()
        assert stream.calls.count("stop") == 1
        assert not audio._input.closed
        stream.consume()
        a, b = await asyncio.gather(first, second)
        assert a is b and a.status is VoiceDevicePlaybackStatus.COMPLETE
        assert a.confirmed_bytes == len(PCM) and a.parts == MANIFEST.parts
        assert stream.calls == ["write", "stop"]  # Lazy restart, not eager restart after drain.
        assert await audio.stop_output()
        assert (await audio.complete_output(MANIFEST)).status is VoiceDevicePlaybackStatus.STALE
        await write(audio, output="next", response="next-response")
        assert stream.calls[-2:] == ["start", "write"]
        traces = read_jsonl_tail(journal.trace_path)
        assert any(row["kind"] == "audio.drain_requested" for row in traces)
        assert any(row["data"].get("status") == "completed" for row in traces)
        assert "pcm" not in json.dumps(traces).lower()
    finally:
        stream.consume()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
        await audio.close()


@pytest.mark.parametrize("action", ["stop", "close", "cancel", "epoch"])
async def test_pending_native_drain_survives_control_without_false_completion(action, tmp_path):
    audio, stream, journal = audio_pair(tmp_path, wait=.03)
    input_stream = audio._input
    task = None
    try:
        await write(audio)
        task = asyncio.create_task(audio.complete_output(MANIFEST))
        await until(stream.draining.is_set)
        if action == "stop":
            assert await audio.stop_output() is False
        elif action == "close":
            assert await audio.close() is False
            assert input_stream.closed  # Full Stop can close capture while output is stuck.
        elif action == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert audio._native_tasks  # Cancellation is not native cancellation.
            assert await audio.close() is False
        else:
            audio.set_active_output(output_id="next", response_id="next-response", item_id="new", content_index=0, output_index=0)
        if action != "cancel":
            result = await task
            assert result.status is not VoiceDevicePlaybackStatus.COMPLETE
        assert stream.native == "stop" and not stream.closed
        assert not any(call in {"abort", "close", "start"} for call in stream.calls)
        stream.consume()
        await until(lambda: not audio._native_tasks and not audio.cleanup_pending)
        assert all(row["data"].get("status") != "completed" for row in read_jsonl_tail(journal.trace_path))
    finally:
        stream.consume()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await audio.close()


async def test_drain_timeout_has_real_error_evidence_and_never_late_complete(tmp_path):
    audio, stream, journal = audio_pair(tmp_path, wait=.02)
    try:
        await write(audio)
        result = await audio.complete_output(MANIFEST)
        assert result.status is VoiceDevicePlaybackStatus.UNKNOWN
        assert audio.cleanup_pending
        before = len(stream.writes)
        await asyncio.wait_for(write(audio, output="new", response="new-response"), .2)
        assert len(stream.writes) == before
        assert any(row["data"].get("code") == "audio_device_pending" for row in read_jsonl_tail(journal.trace_path))
        stream.consume()
        await until(lambda: not audio.cleanup_pending)
        assert result.confirmed_bytes == 0
    finally:
        stream.consume()
        await audio.close()


@pytest.mark.parametrize("failure", ["stop", "write", "start"])
async def test_native_failure_cannot_certify_audio(failure, tmp_path):
    audio, stream, journal = audio_pair(tmp_path)
    try:
        if failure == "stop":
            await write(audio)
            stream.fail.add("stop")
            result = await audio.complete_output(MANIFEST)
            assert result.status is VoiceDevicePlaybackStatus.FAILED
        else:
            stream.fail.add(failure)
            audio._output_stopped = failure == "start"
            with pytest.raises(OSError):
                await write(audio)
            assert (await audio.complete_output(MANIFEST)).status is not VoiceDevicePlaybackStatus.COMPLETE
        errors = read_jsonl_tail(journal.error_path)
        assert any(row["data"].get("code") == "audio_native_failed" for row in errors)
        assert "injected" not in json.dumps(errors)
    finally:
        stream.fail.clear()
        stream.consume()
        await audio.close()


async def test_gain_recovery_ramp_prevents_full_text_proof():
    audio, stream, _ = audio_pair()
    try:
        audio._applied_gain = .3
        audio.set_output_gain(1)
        await write(audio)
        result = await audio.complete_output(MANIFEST)
        assert result.status is VoiceDevicePlaybackStatus.STALE
        assert "stop" not in stream.calls
    finally:
        await audio.close()


async def test_multipart_cursor_and_exact_written_extents():
    audio, stream, _ = audio_pair()
    second = VoiceAudioPart("item", 1, 0)
    manifest = replace(MANIFEST, parts=(*MANIFEST.parts, VoiceAudioPartExtent(second, len(PCM))), received_bytes=len(PCM)*2)
    try:
        stream.latency = 0
        await write(audio)
        assert audio.playback_cursor().content_index == 0
        assert audio.playback_cursor().played_ms == 100
        await write(audio, part=second)
        assert audio.playback_cursor().content_index == 1
        assert audio.playback_cursor().played_ms == 100
        stream.consume()
        result = await audio.complete_output(manifest)
        assert result.status is VoiceDevicePlaybackStatus.COMPLETE and result.parts == manifest.parts
    finally:
        stream.consume()
        await audio.close()


async def test_close_attempts_release_after_abort_failure_and_retains_failed_close_for_retry():
    audio, stream, _ = audio_pair()
    stream.fail.update({"abort", "close"})
    with pytest.raises(RuntimeError):
        await audio.close()
    assert stream.calls[-2:] == ["abort", "close"]
    assert not audio.device_closed and audio._output is stream
    stream.fail.clear()
    assert await audio.close()
    assert stream.closed and audio.device_closed


async def test_failed_start_releases_created_output_too(monkeypatch):
    audio, stream, _ = audio_pair()
    input_stream = audio._input
    audio._input = audio._output = None
    stream.fail.add("start")
    class Device:
        RawInputStream = staticmethod(lambda **kwargs: input_stream)
        RawOutputStream = staticmethod(lambda **kwargs: stream)
    monkeypatch.setitem(sys.modules, "sounddevice", Device)
    with pytest.raises(RuntimeError, match="périphériques"):
        await audio.start()
    assert stream.closed and input_stream.closed
    assert stream.calls == ["start", "abort", "close"]
    await audio.close()


async def test_failed_open_cleanup_retains_pointer_until_retry(monkeypatch):
    audio, stream, _ = audio_pair()
    input_stream = audio._input
    audio._input = audio._output = None
    stream.fail.update({"start", "close"})
    class Device:
        RawInputStream = staticmethod(lambda **kwargs: input_stream)
        RawOutputStream = staticmethod(lambda **kwargs: stream)
    monkeypatch.setitem(sys.modules, "sounddevice", Device)
    with pytest.raises(RuntimeError):
        await audio.start()
    assert audio._output is stream and not stream.closed
    stream.fail.clear()
    assert await audio.close()
    assert stream.closed and stream.calls.count("close") == 2


async def test_failed_input_close_retains_pointer_for_full_close_retry():
    audio, output, _ = audio_pair()
    class Input(BufferedInputStream):
        attempts = 0
        def close(self, *, ignore_errors=True):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("injected input close")
            super().close(ignore_errors=ignore_errors)
    input_stream = Input()
    audio._input = input_stream
    with pytest.raises(OSError):
        await audio.stop_input()
    assert audio._input is input_stream and not input_stream.closed
    assert await audio.close()
    assert input_stream.attempts == 2 and input_stream.closed and output.closed


@pytest.mark.parametrize("cancel_open", [False, True])
async def test_output_start_owns_pointer_against_stop_write_and_cancel(monkeypatch, cancel_open):
    entered, release = threading.Event(), threading.Event()
    class Output(BufferedOutputStream):
        def start(self):
            with self.operation("start"):
                entered.set()
                assert release.wait(2)
                self.active = True
    stream, input_stream = Output(), BufferedInputStream()
    class Device:
        RawInputStream = staticmethod(lambda **kwargs: input_stream)
        RawOutputStream = staticmethod(lambda **kwargs: stream)
    monkeypatch.setitem(sys.modules, "sounddevice", Device)
    audio = SoundDeviceRealtimeAudio(device_wait_s=.02)
    starting = asyncio.create_task(audio.start())
    try:
        await until(entered.is_set)
        if cancel_open:
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(starting, .2)
        else:
            assert await audio.stop_output() is False
        await asyncio.wait_for(write(audio), .1)
        assert stream.calls == ["start"] and not stream.closed
        release.set()
        await asyncio.gather(starting, return_exceptions=True)
        await until(lambda: not audio.cleanup_pending)
    finally:
        release.set()
        await asyncio.gather(starting, return_exceptions=True)
        await audio.close()


@pytest.mark.parametrize("action", ["expire", "stop", "close"])
async def test_slow_lazy_start_rechecks_admission_and_epoch_before_first_write(action):
    entered, release = threading.Event(), threading.Event()
    class Output(BufferedOutputStream):
        def start(self):
            with self.operation("start"):
                entered.set()
                assert release.wait(2)
                self.active = True
    audio, _, _ = audio_pair(wait=.02)
    stream = Output()
    audio._output = stream
    audio._output_stopped = True
    audio.set_active_output(output_id="output", response_id="response", item_id="item", content_index=0, output_index=0)
    admission = OutputAdmission(expires_at=time.monotonic()+10)
    writing = asyncio.create_task(audio.play_b64_guarded(base64.b64encode(PCM).decode(), admission))
    try:
        await until(entered.is_set)
        assert admission.state is OutputAdmissionState.RESERVED
        if action == "expire":
            # Controlled expiry while the driver start remains blocked.
            admission._expires_at = time.monotonic()-1
        elif action == "stop":
            assert await audio.stop_output() is False
        else:
            assert await audio.close() is False
        release.set()
        assert await asyncio.wait_for(writing, .3) is False
        assert stream.writes == [] and audio.written_output_ms == 0
        if action == "expire":
            assert admission.state is OutputAdmissionState.INVALIDATED
    finally:
        release.set()
        await asyncio.gather(writing, return_exceptions=True)
        await audio.close()


async def test_urgent_provider_event_and_microphone_progress_with_zero_queued_audio_during_drain():
    audio, device, _ = audio_pair(wait=.1)
    proofs, received, ambient = [], [], []
    class Session(ControllableSession):
        def playback_manifest(self, payload):
            return MANIFEST
        def observe_device_completion(self, manifest, proof):
            proofs.append(proof)
        async def send_audio(self, pcm):
            received.append(pcm)
    session = Session()
    bridge = build_bridge(audio, session=session, on_ambient=lambda: ambient.append(True))
    queue = asyncio.Queue()
    async def events():
        while (event := await queue.get()) is not None:
            yield event
    task = asyncio.create_task(bridge._consume(events()))
    pump = asyncio.create_task(audio.pump_input(session))
    try:
        fields = dict(output_id="output", response_id="response", item_id="item", content_index=0, output_index=0)
        await queue.put(ProtocolEnvelope(message_type="realtime.output_started", payload=fields))
        await queue.put(ProtocolEnvelope(message_type="realtime.audio", payload={**fields, "pcm_b64":base64.b64encode(PCM).decode()}))
        await queue.put(ProtocolEnvelope(message_type="realtime.response_done", payload={**fields, "status":"completed"}))
        await until(device.draining.is_set)
        assert bridge._queued_audio == 0
        audio._enqueue(b"\1\0" * 50)
        await queue.put(ProtocolEnvelope(message_type="realtime.transcript_delta", payload={"text":"private provisional"}))
        await asyncio.wait_for(until(lambda: received and ambient), .05)
        assert not proofs and not audio._input.closed
        device.consume()
        await until(lambda: proofs)
        assert proofs[0].status is VoiceDevicePlaybackStatus.COMPLETE
        await queue.put(None)
        await asyncio.wait_for(task, 1)
    finally:
        device.consume()
        for item in (task, pump):
            item.cancel()
        await asyncio.gather(task, pump, return_exceptions=True)
        await audio.close()


async def test_runtime_repeated_mute_keeps_one_provider_close_and_no_early_idle():
    release, entered = asyncio.Event(), asyncio.Event()
    class Session(FakeRealtimeSession):
        calls = 0
        async def close(self):
            self.calls += 1
            entered.set()
            await release.wait()
            self.closed = True
    session, wake = Session([]), FakeWakeWord()
    async def factory(context):
        raise AssertionError("activation during pending close")
    runtime = PersistentVoiceRuntime(wakeword=wake, core=FakeCore(), realtime_factory=factory,
                                     voice_arch=VoiceArchitecture.LEGACY)
    runtime._session = session
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    first = asyncio.create_task(runtime.mute())
    await entered.wait()
    second = asyncio.create_task(runtime.mute())
    await asyncio.sleep(0)
    try:
        await runtime.activate()
        assert not first.done() and not second.done()
        assert not wake.resumed.is_set() and runtime.runtime.state is VoiceLifecycleState.ACTIVE
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert session.calls == 1 and runtime.runtime.state is VoiceLifecycleState.BACKGROUND
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_runtime_provider_can_close_while_device_pending_but_cannot_reopen(tmp_path):
    audio, stream, journal = audio_pair(tmp_path, wait=.02)
    session, wake = FakeRealtimeSession([]), FakeWakeWord()
    async def factory(context):
        raise AssertionError("new device/provider before cleanup")
    runtime = PersistentVoiceRuntime(wakeword=wake, core=FakeCore(), realtime_factory=factory,
                                     voice_arch=VoiceArchitecture.LEGACY, journal=journal)
    runtime._session = session
    runtime._bridge = SimpleNamespace(audio=audio)
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    task = None
    try:
        await write(audio)
        task = asyncio.create_task(audio.complete_output(MANIFEST))
        await until(stream.draining.is_set)
        await asyncio.wait_for(runtime.mute(), .3)
        assert session.closed and runtime._pending_audio is audio
        assert runtime.runtime.state is VoiceLifecycleState.ERROR and not wake.resumed.is_set()
        await asyncio.wait_for(runtime.activate(), .2)
        assert runtime._pending_audio is audio
        stream.consume()
        await until(lambda: audio.device_closed)
        await runtime.mute()
        assert runtime._pending_audio is None and runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        traces = read_jsonl_tail(journal.trace_path)
        pending = next(index for index,row in enumerate(traces) if row["kind"] == "voice.device_cleanup_pending")
        closed = next(index for index,row in enumerate(traces) if row["kind"] == "audio.device_closed")
        background = next(index for index,row in enumerate(traces) if row["kind"] == "voice.background")
        assert pending < closed < background
    finally:
        stream.consume()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await audio.close()


async def test_noise_replay_63_unconfirmed_candidates_has_zero_audible_modulations():
    audio, journal = GuardedAudio(guarded=True, gate_open=True), RecordingJournal()
    bridge = build_bridge(audio, journal=journal)
    bridge._playing = True
    # Synthetic equivalent: 7 bus-like candidates + 56 other rejected candidates.
    for _ in range(63):
        await bridge._on_near_end()
        await bridge._on_barge_timeout(bridge._barge_pending_token)
    assert len(journal.of("voice.barge_in_pending")) == 63
    assert len(journal.of("voice.barge_in_rejected")) == 63
    assert audio.gains == [] and audio.stop_output_calls == 0


async def test_terminal_tombstone_rejects_late_pcm_after_new_output():
    audio = GuardedAudio(guarded=True, gate_open=True)
    bridge = build_bridge(audio)
    old = {"output_id": "old", "speech_id": "old-speech"}
    bridge._interrupted_outputs.add("old-speech")
    bridge._release_playback_output(ProtocolEnvelope(message_type="realtime.response_done", payload=old))
    await bridge._play_audio(10, ProtocolEnvelope(message_type="realtime.audio", payload={**old, "pcm_b64": base64.b64encode(PCM).decode()}))
    assert audio.written_output_ms == 0
    for number in range(140):
        bridge._release_playback_output(ProtocolEnvelope(message_type="realtime.response_done", payload={"output_id": str(number)}))
    assert len(bridge._terminal_outputs) == len(bridge._interrupted_outputs) == 128
    bridge._inbox, bridge._playout = asyncio.Queue(), asyncio.Queue()
    bridge._dispatch(ProtocolEnvelope(message_type="realtime.audio", payload={**old, "pcm_b64":base64.b64encode(PCM).decode()}))
    assert bridge._playout.empty() and bridge._queued_audio == 0
