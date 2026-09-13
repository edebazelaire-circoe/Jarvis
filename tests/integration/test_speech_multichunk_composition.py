"""Task08 positive composition: each semantic chunk waits for checked drain.

The actual app factory, Core HTTP/SQLite, canonical adapter and native wrapper
run. Only provider websocket, wake input and native streams are controlled.
"""
from __future__ import annotations

import asyncio
import base64

import aiohttp
from aiohttp.test_utils import TestServer

from jarvis import app
from jarvis.adapters.openai_realtime import OUTPUT_ID_METADATA_KEY, SPEECH_ID_METADATA_KEY
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import BrainEvent, BrainEventKind, BrainTurnResult, SpeechKind, SpeechRequest
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import credentials, realtime_audio
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedInputStream, BufferedOutputStream
from tests.integration.test_voice_production_composition import ControlledWake, ControlledWire


CHUNKS = ("Le Dr. Martin confirme le montant de 3.14 euros.\n\n", "Le rapport comprend deux recommandations.")
TEXT = "".join(CHUNKS)
PCM = b"\1\0" * 2400


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.001)


class ParagraphBackend:
    async def run_turn(self, turn, state, emit):
        await emit.emit(BrainEvent(
            kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
            correlation_id=turn.correlation_id, work_id="report-work",
            speech=SpeechRequest(conversation_id=turn.conversation_id, text=TEXT,
                                 kind=SpeechKind.RESULT, work_id="report-work"),
        ))
        return BrainTurnResult(correlation_id=turn.correlation_id)


async def test_app_multichunk_advances_only_after_real_device_drain(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard

    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=ParagraphBackend())
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token="m" * 32)
    server = TestServer(protocol._app())
    await server.start_server()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token_file = runtime_root / "core.token"
    token_file.write_text("m" * 32, encoding="utf-8")
    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", server.port,
                          "Europe/Paris", token_file, 12, 0, "unused", "ash", True,
                          VoiceArchitecture.CONTINUOUS_BRAIN)
    overrides = {"voice_arch": "continuous_brain", "voice_stack": "openai_realtime",
                 "voice_stack_settings": {"openai_realtime": {
                     "model": "gpt-realtime-2.1-mini", "voice": "cedar", "turn_mode": "auto",
                     "echo_cancellation": False, "ack_delay_ms": 0,
                 }}}
    monkeypatch.setattr(V2Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(app, "_control_settings", lambda root: overrides)
    monkeypatch.setattr(app, "_speaker_verifier", lambda *args: None)
    monkeypatch.setattr(credentials, "secret_for", lambda values, provider: "test-only-key" if provider == "openai" else None)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", ControlledWake)
    wire, audios, runtimes, connections = ControlledWire(), [], [], []
    original_connect = aiohttp.ClientSession.ws_connect

    def connect(client, url, **kwargs):
        if str(url).startswith("wss://api.openai.com/"):
            connections.append(str(url))
            assert kwargs["headers"]["Authorization"] == "Bearer test-only-key"

            async def opened():
                return wire
            return opened()
        return original_connect(client, url, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", connect)

    class ControlledAudio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._loop = asyncio.get_running_loop()
            self._input = BufferedInputStream()
            self._output = self.device = BufferedOutputStream()
            self.device_wait_s = 1
            self._output_latency_ms = self._stream_latency_ms()
            audios.append(self)

    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", ControlledAudio)

    def creates():
        return [item["response"] for item in wire.sent if item["type"] == "response.create"]

    async def drive(runtime):
        runtimes.append(runtime)
        try:
            await runtime.activate()
            assert isinstance(runtime._session, RealtimeFrontendSession)
            await until(lambda: audios and runtime._bridge._inbox is not None)
            conversation = runtime.runtime.conversation_id
            acceptance = await runtime.core.submit_brain_turn(
                conversation, content="Prépare le rapport.", correlation_id="report-origin",
            )
            await until(lambda: len(creates()) == 1)
            projection = runtime._speech.presentation_snapshot()
            candidates = sorted(projection["candidates"], key=lambda item: item["chunk"]["index"])
            assert len(candidates) == 2
            spans = [item["chunk"]["span"] for item in candidates]
            assert [TEXT[span["start"]:span["end"]] for span in spans] == list(CHUNKS)
            assert spans[0]["start"] == 0 and spans[0]["end"] == spans[1]["start"]
            assert spans[1]["end"] == len(TEXT)
            assert len({item["chunk"]["chain_id"] for item in candidates}) == 1
            assert len({item["outcome_id"] for item in candidates}) == 1
            assert all(item["source"]["turn_id"] == acceptance["turn_id"] and
                       item["source"]["correlation_id"] == "report-origin" and
                       item["source"]["dependencies"] == [{"work_id": "report-work", "source_correlation_id": "report-origin"}]
                       for item in candidates)

            device = audios[0].device
            for index, text in enumerate(CHUNKS):
                await until(lambda: len(creates()) == index + 1)
                command = creates()[index]
                assert text in command["instructions"]
                assert command["metadata"][SPEECH_ID_METADATA_KEY] == candidates[index]["speech_id"]
                device.draining.clear()
                response_id, item_id = f"response-{index}", f"audio-{index}"
                part = dict(response_id=response_id, item_id=item_id, content_index=0, output_index=0)
                wire.push("response.created", response={"id": response_id, "metadata": command["metadata"]})
                wire.push("response.output_audio_transcript.done", **part, transcript=text)
                wire.push("response.output_audio.delta", **part, delta=base64.b64encode(PCM).decode())
                wire.push("response.output_audio.done", **part)
                wire.push("response.done", response={
                    "id": response_id, "status": "completed", "metadata": command["metadata"],
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                    "output": [{"id": item_id, "type": "message", "role": "assistant", "status": "completed",
                                "content": [{"type": "audio", "transcript": text}]}],
                })
                await until(device.draining.is_set)
                assert device.queued_bytes == len(PCM)
                assert device.played_bytes == index * len(PCM)
                # Provider generation is closed, but the actual native stop is
                # blocked by an unconsumed buffer. No next response or heard text.
                await asyncio.sleep(.02)
                assert len(creates()) == index + 1
                snapshot = (await runtime.core.voice_snapshot(conversation))["snapshot"]
                assert len([item for item in snapshot["speeches"] if item["confirmed_text"] is not None]) == index
                device.consume()
                await until(lambda: device.native is None)
                if index == 0:
                    await until(lambda: len(creates()) == 2)

            async with asyncio.timeout(3):
                while True:
                    snapshot = (await runtime.core.voice_snapshot(conversation))["snapshot"]
                    heard = [item["confirmed_text"] for item in snapshot["speeches"] if item["confirmed_text"] is not None]
                    if len(heard) == 2:
                        break
                    await asyncio.sleep(.001)
            assert heard == list(CHUNKS)
            assert "".join(heard) == TEXT
            assert device.played_bytes == len(PCM) * 2
            assert device.calls.count("stop") == 2
            assert len({command["metadata"][OUTPUT_ID_METADATA_KEY] for command in creates()}) == 2
            assert all(item["playback_status"] == "complete" for item in snapshot["speeches"])
            outcomes = (await runtime.core.list_brain_outcomes(conversation))["outcomes"]
            assert len(outcomes) == 1 and outcomes[0]["text"] == TEXT
            assert outcomes[0]["id"] == candidates[0]["outcome_id"]
        finally:
            for audio in audios:
                audio.device.consume()
            await runtime.mute()

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 15) == 0
        assert connections == ["wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"]
        assert wire.readers == 1 and wire.closed
        conversation = runtimes[0].runtime.conversation_id
        turns = await core.conversations.list_turns(conversation)
        assert [turn.content for turn in turns if turn.kind.value == "assistant"] == list(CHUNKS)
    finally:
        for audio in audios:
            audio.device.consume()
        await server.close()
        await core.stop()
