"""Task05 parent QA: real app factory, runtime, transport adapter and Core HTTP.

Only external websocket, wake input and audio device are controlled doubles.
Runtime.run is a test driver; activate/mute/bridge/ledger remain production code.
Device writes deliberately do not establish complete playback.
"""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import aiohttp
from aiohttp.test_utils import TestServer
import pytest

from jarvis import app
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.voice_frontend import FrontendState
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import credentials, realtime_audio
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from tests.fakes.audio_device import BufferedOutputStream
from jarvis.v2_config import V2Settings, VoiceArchitecture


class ControlledWire:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.close_code = None
        self.readers = 0

    def push(self, kind, **values):
        self.incoming.put_nowait({"type": kind, **values})

    def __aiter__(self):
        self.readers += 1
        return self

    async def __anext__(self):
        value = await self.incoming.get()
        if value is None:
            raise StopAsyncIteration
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda: value)

    async def send_json(self, value):
        self.sent.append(value)
        if value["type"] == "session.update":
            self.push("session.created", session={"id": "provider-session"})
            self.push("session.updated", session={"id": "provider-session", **value["session"]})

    async def ping(self):
        pass

    def exception(self):
        return None

    async def close(self, **kwargs):
        if not self.closed:
            self.closed, self.close_code = True, 1000
            self.incoming.put_nowait(None)
        return True


class ControlledDevice:
    latency = 0.02

    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, pcm):
        self.written.extend(pcm)

    def abort(self, *, ignore_errors=True):
        pass

    def start(self):
        pass

    def close(self, *, ignore_errors=True):
        self.closed = True


class ControlledWake:
    def __init__(self, **kwargs):
        pass

    async def suspend_for_active_session(self):
        pass

    async def resume(self):
        pass

    async def close(self):
        pass


@pytest.mark.parametrize("architecture,model", [
    (VoiceArchitecture.LEGACY, "gpt-realtime-2.1"),
    (VoiceArchitecture.CONTINUOUS_BRAIN, "gpt-realtime-2.1-mini"),
])
@pytest.mark.parametrize("natural", [False, True])
async def test_app_factory_reaches_canonical_core_with_only_proven_device_delivery(tmp_path, monkeypatch, architecture, model, natural):
    from jarvis.adapters import wakeword_keyboard

    wire, connections, audios, runtimes = ControlledWire(), [], [], []
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token="t" * 32)
    server = TestServer(protocol._app())
    await server.start_server()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token_file = runtime_root / "core.token"
    token_file.write_text("t" * 32, encoding="utf-8")
    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", server.port,
                          "Europe/Paris", token_file, 12, 0, "unused-env-model", "ash", True,
                          VoiceArchitecture.LEGACY)
    overrides = {"voice_arch": architecture.value, "voice_stack": "openai_realtime",
                 "voice_stack_settings": {"openai_realtime": {
                     "model": model, "voice": "cedar", "turn_mode": "auto",
                     "echo_cancellation": False, "ack_delay_ms": 0,
                 }}}
    monkeypatch.setattr(V2Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(app, "_control_settings", lambda root: overrides)
    monkeypatch.setattr(app, "_speaker_verifier", lambda *args: None)
    monkeypatch.setattr(credentials, "secret_for", lambda values, provider: "test-only-key" if provider == "openai" else None)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", ControlledWake)
    monkeypatch.setenv("OPENAI_REALTIME_MODEL", "unused-env-model")

    original_ws_connect = aiohttp.ClientSession.ws_connect

    def connect(session, url, **kwargs):
        if str(url).startswith("wss://api.openai.com/"):
            connections.append(str(url))
            assert kwargs["headers"]["Authorization"] == "Bearer test-only-key"
            async def opened():
                return wire
            return opened()
        return original_ws_connect(session, url, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", connect)

    class ControlledAudio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._output = BufferedOutputStream() if natural else ControlledDevice()
            self.device = self._output
            self.device_wait_s = 1
            self._output_latency_ms = self._stream_latency_ms()
            audios.append(self)

    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", ControlledAudio)

    async def drive(runtime):
        runtimes.append(runtime)
        await runtime.activate()
        assert isinstance(runtime._session, RealtimeFrontendSession)
        assert runtime._session.frontend.state == FrontendState.ACTIVE
        assert runtime.voice_arch == architecture
        async with asyncio.timeout(5):
            while not audios:
                await asyncio.sleep(0.005)
        if architecture == VoiceArchitecture.LEGACY:
            wire.push("input_audio_buffer.committed", item_id="input-a", previous_item_id=None)
            wire.push("conversation.item.input_audio_transcription.completed", item_id="input-a", transcript="Jarvis, quel est le résultat ?")
        wire.push("response.created", response={"id": "response-a"})
        wire.push("response.output_item.added", response_id="response-a", item={"type": "message", "id": "message-a"})
        wire.push("response.output_audio_transcript.done", response_id="response-a", item_id="message-a", content_index=0, output_index=0, transcript="Voici la réponse générée.")
        wire.push("response.output_audio.delta", response_id="response-a", item_id="message-a", content_index=0, output_index=0, delta=base64.b64encode(b"\1\0" * 2400).decode())
        response = {"id": "response-a", "status": "completed", "usage": {"input_tokens": 3, "output_tokens": 5}}
        if natural:
            wire.push("response.output_audio.done", response_id="response-a", item_id="message-a", content_index=0, output_index=0)
            response["output"] = [{"id": "message-a", "type": "message", "role": "assistant", "status": "completed",
                                   "content": [{"type": "audio", "transcript": "Voici la réponse générée."}]}]
        wire.push("response.done", response=response)
        if natural:
            async with asyncio.timeout(5):
                while not audios[0].device.draining.is_set():
                    await asyncio.sleep(.001)
            before = (await core.voice_ledger.snapshot(runtime.runtime.conversation_id))["snapshot"]
            assert not before or not any(speech["confirmed_text"] for speech in before["speeches"])
            assert audios[0].device.queued_bytes == 4800
            audios[0].device.consume()
        async with asyncio.timeout(5):
            while True:
                snapshot = (await core.voice_ledger.snapshot(runtime.runtime.conversation_id))["snapshot"]
                if (snapshot and snapshot["speeches"] and snapshot["speeches"][0]["played_ms"] > 0
                        and snapshot["speeches"][0]["playback_status"] == ("complete" if natural else "unknown")):
                    break
                await asyncio.sleep(0.01)
        speech = snapshot["speeches"][0]
        assert speech["generated"][0]["text"] == "Voici la réponse générée."
        assert speech["confirmed_text"] == ("Voici la réponse générée." if natural else None)
        assert speech["playback_status"] == ("complete" if natural else "unknown")
        if architecture == VoiceArchitecture.LEGACY:
            assert [user["text"] for user in snapshot["users"]] == ["Jarvis, quel est le résultat ?"]
        await runtime.mute()

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 15) == 0
        assert connections == [f"wss://api.openai.com/v1/realtime?model={model}"]
        assert wire.readers == 1 and wire.closed
        update = next(value["session"] for value in wire.sent if value["type"] == "session.update")
        assert update["audio"]["output"]["voice"] == "cedar"
        assert bool(update["tools"]) == (architecture == VoiceArchitecture.LEGACY)
        conversation_id = runtimes[0].runtime.conversation_id
        snapshot = (await core.voice_ledger.snapshot(conversation_id))["snapshot"]
        assert snapshot["lifecycle"] == "stopped"
        heard = [turn.content for turn in await core.conversations.list_turns(conversation_id) if turn.kind.value == "assistant"]
        assert heard == (["Voici la réponse générée."] if natural else [])
    finally:
        for audio in audios:
            if natural:
                audio.device.consume()
        await server.close()
        await core.stop()
