"""Task07 control-plane QA through runtime, canonical frontend and real Core HTTP.

Only native streams, provider websocket and wake input are controlled. Evidence
contract: blocked drain never produces heard text/idle; Stop reports retained
device ownership; explicit consumption permits cleanup. No injected COMPLETE.
"""
from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

from aiohttp.test_utils import TestServer
import pytest

from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.protocol.client import LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime.realtime_audio import SoundDeviceRealtimeAudio
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture
from tests.fakes.audio_device import BufferedInputStream, BufferedOutputStream
from tests.integration.test_voice_production_composition import ControlledWake
from tests.unit.test_realtime_frontend_adapter import started
from tests.unit.test_v2_speech_scheduler import RecordingJournal


async def until(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.001)


@pytest.fixture
async def control_plane(tmp_path, monkeypatch):
    core = JarvisCoreApplication(data_root=tmp_path / "core")
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token="t" * 32)
    server = TestServer(protocol._app())
    await server.start_server()
    client = LocalCoreClient(host="127.0.0.1", port=server.port, token="t" * 32)
    audios, wires, sessions = [], [], []
    journal = RecordingJournal()

    class Wake(ControlledWake):
        resumes = 0

        async def resume(self):
            self.resumes += 1

    wake = Wake()

    async def open_controlled_streams(audio):
        audio._loop = asyncio.get_running_loop()
        audio._input = BufferedInputStream()
        audio._output = BufferedOutputStream()
        audio.device = audio._output
        audio.input_device_stream = audio._input
        # Leave ample time to observe the blocked drain before asking Stop.
        audio.device_wait_s = 1
        audio._output_latency_ms = audio._stream_latency_ms()
        audios.append(audio)

    monkeypatch.setattr(SoundDeviceRealtimeAudio, "start", open_controlled_streams)

    async def factory(context):
        frontend, wire = await started()
        facade = RealtimeFrontendSession(frontend, "session")
        wires.append(wire)
        sessions.append(facade)
        return facade

    runtime = PersistentVoiceRuntime(
        wakeword=wake, core=client, realtime_factory=factory,
        voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN, auto_turn=True,
        journal=journal,
    )
    try:
        await asyncio.wait_for(runtime.activate(), 2)
        await until(lambda: audios and runtime._bridge._inbox is not None)
        yield SimpleNamespace(runtime=runtime, core=core, audio=audios[0],
                              wire=wires[0], facade=sessions[0], wake=wake,
                              journal=journal, wires=wires, audios=audios)
    finally:
        # Native drain cannot be cancelled; release every controlled buffer even
        # after an assertion failure, then let the production owner join it.
        for wire in wires:
            if wire.close_gate is not None:
                wire.close_gate.set()
        for audio in audios:
            audio.device.consume()
        try:
            await asyncio.wait_for(runtime.close(), 3)
            for audio in audios:
                await until(lambda audio=audio: not audio._native_tasks, timeout=2)
                assert await asyncio.wait_for(audio.close(), 2)
        finally:
            await client.close()
            await server.close()
            await core.stop()


def complete_provider_output(wire):
    fields = dict(response_id="response", item_id="audio-item", content_index=0, output_index=0)
    wire.push(type="response.created", response={"id": "response"})
    wire.push(type="response.output_audio_transcript.done", **fields, transcript="Generated answer.")
    wire.push(type="response.output_audio.delta", **fields,
              delta=base64.b64encode(b"\1\0" * 2400).decode())
    wire.push(type="response.output_audio.done", **fields)
    wire.push(type="response.done", response={
        "id": "response", "status": "completed", "usage": {"input_tokens": 1, "output_tokens": 2},
        "output": [{"id": "audio-item", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_audio", "transcript": "Generated answer."}]}],
    })


async def test_blocked_canonical_drain_keeps_capture_urgent_input_and_stop_responsive(control_plane):
    case = control_plane
    runtime, audio, wire = case.runtime, case.audio, case.wire
    bridge, speech = runtime._bridge, runtime._speech
    complete_provider_output(wire)
    await until(audio.device.draining.is_set)
    assert bridge._queued_audio == 0 and bridge._device_fence_pending == 1
    output_id = next(correlation.output_id for correlation in case.facade._outputs.values()
                     if correlation.provider_output_id == "response")
    assert bridge.output_pending(output_id)
    assert audio.device.queued_bytes == 4800 and audio.device.played_bytes == 0

    # Same callback handoff as real capture; the pump and both adapter layers
    # must still send these bytes while output's checked stop owns the device.
    microphone = b"\2\0" * 240
    audio._deliver_capture(len(microphone), microphone, ())
    wire.push(type="input_audio_buffer.speech_started", item_id="user-input", audio_start_ms=0)
    await until(lambda: audio.sent_bytes == len(microphone) and speech._user_speaking)
    uploaded = [message for message in wire.sent if message["type"] == "input_audio_buffer.append"]
    assert base64.b64decode(uploaded[-1]["audio"]) == microphone
    assert not audio.input_device_stream.closed
    assert audio.device.native == "stop" and audio.device.played_bytes == 0
    assert bridge._queued_audio == 0 and bridge._device_fence_pending == 1
    assert not bridge._idle.is_set()

    audio.device_wait_s = .025
    await asyncio.wait_for(runtime.mute(), .5)
    assert wire.closed and wire.close_count == 1
    assert runtime._pending_audio is audio
    assert runtime.runtime.state is VoiceLifecycleState.ERROR
    assert audio.cleanup_pending and audio.device.native == "stop"
    assert audio.input_device_stream.closed and not audio.device.closed
    assert case.wake.resumes == 0
    assert not case.journal.of("voice.background")
    assert case.journal.of("voice.device_cleanup_pending")

    await asyncio.wait_for(runtime.activate(), .2)
    assert len(case.wires) == len(case.audios) == 1
    assert runtime._pending_audio is audio and case.wake.resumes == 0
    assert not any(name in audio.device.calls for name in ("abort", "close", "start"))

    snapshot = (await case.core.voice_ledger.snapshot(runtime.runtime.conversation_id))["snapshot"]
    assert snapshot["speeches"]
    assert all(row["confirmed_text"] is None and row["playback_status"] != "complete"
               for row in snapshot["speeches"])
    assert not [turn for turn in await case.core.conversations.list_turns(runtime.runtime.conversation_id)
                if turn.kind.value == "assistant"]

    audio.device.consume()
    await until(lambda: audio.device_closed and not audio.cleanup_pending)
    await asyncio.wait_for(runtime.mute(), .5)
    assert runtime._pending_audio is None
    assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND and case.wake.resumes == 1
    kinds = [row["kind"] for row in case.journal.events]
    assert kinds.index("voice.device_cleanup_pending") < kinds.index("audio.device_closed") < kinds.index("voice.background")


async def test_concurrent_stop_waits_for_one_real_provider_close_without_early_idle(control_plane):
    case = control_plane
    case.wire.close_gate = asyncio.Event()
    first = asyncio.create_task(case.runtime.mute())
    second = None
    try:
        await until(lambda: case.wire.close_count == 1)
        second = asyncio.create_task(case.runtime.mute())
        await asyncio.sleep(0)
        await asyncio.wait_for(case.runtime.activate(), .2)
        assert not first.done() and not second.done()
        assert len(case.wires) == 1 and case.wire.close_count == 1
        assert not case.wire.closed and case.wake.resumes == 0
        assert case.runtime.runtime.state is not VoiceLifecycleState.BACKGROUND
        assert not case.journal.of("voice.background")
        case.wire.close_gate.set()
        await asyncio.wait_for(asyncio.gather(first, second), 2)
        assert case.wire.closed and case.wire.close_count == 1
        assert case.wake.resumes == 1
        assert case.runtime.runtime.state is VoiceLifecycleState.BACKGROUND
        assert case.audio.device_closed
        snapshot = (await case.core.voice_ledger.snapshot(case.runtime.runtime.conversation_id))["snapshot"]
        assert snapshot["lifecycle"] == "stopped"
    finally:
        case.wire.close_gate.set()
        await asyncio.wait_for(asyncio.gather(first, *([second] if second else []), return_exceptions=True), 2)
