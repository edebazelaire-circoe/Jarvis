"""Actual app/Core/facade/scheduler/device; only external transports are controlled."""
import asyncio
import base64
import json

import aiohttp
from aiohttp.test_utils import TestServer
import httpx
import pytest

from jarvis import app
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import credentials, realtime_audio
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_voice_production_composition import ControlledWire, ControlledWake


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.002)


@pytest.mark.parametrize("mode", ["simple", "front_brain"])
@pytest.mark.parametrize("model", ["gpt-realtime-2.1", "gpt-realtime-2.1-mini"])
async def test_explicit_conversation_is_direct_while_optional_luna_is_blocked(tmp_path, monkeypatch, mode, model):
    from jarvis.adapters import wakeword_keyboard
    from jarvis.adapters.openai_front_brain import LunaFrontBrainAnalyzer
    from jarvis.runtime import front_brain_factory

    wire, audios, runtimes, luna_calls = ControlledWire(), [], [], []
    gate = asyncio.Event()
    async def lunar(request):
        luna_calls.append(json.loads(request.content))
        await gate.wait()
        from jarvis.domain.front_brain_hints import FrontBrainHintValue
        from jarvis.domain.reflex_policy import ReflexAction
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(FrontBrainHintValue(suggested_action=ReflexAction.SPEAK).to_payload())}]}]})
    lunar_client = httpx.AsyncClient(transport=httpx.MockTransport(lunar))
    monkeypatch.setattr(front_brain_factory, "LunaFrontBrainAnalyzer", lambda **kwargs: LunaFrontBrainAnalyzer(client=lunar_client, **kwargs))
    backend_calls = []
    class Backend:
        async def run_turn(self, turn, sink):
            backend_calls.append(turn)
            raise AssertionError("direct conversation must not dispatch backend work")
    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=Backend())
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token="t" * 32)
    server = TestServer(protocol._app())
    await server.start_server()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token_file = runtime_root / "core.token"
    token_file.write_text("t" * 32)
    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", server.port, "Europe/Paris",
        token_file, 12, 0, "unused", "ash", True, VoiceArchitecture.LEGACY)
    config = {"architecture": mode, "conversation_model": {"provider_id": "openai", "model_id": model}}
    if mode == "front_brain":
        config = {"architecture": mode, "reflex_model": config["conversation_model"],
            "analysis_model": {"provider_id": "openai", "model_id": "gpt-5.6-luna"}, "reasoning_effort": "low", "speculative_deltas": True}
    overrides = {"voice_architecture": {"schema_version": 1, "config": config, "compatibility": None},
        "voice_stack": "gemini_live", "voice_stack_settings": {"openai_realtime": {
            "voice": "cedar", "turn_mode": "auto", "echo_cancellation": False, "ack_delay_ms": 0}}}
    monkeypatch.setattr(V2Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(app, "_control_settings", lambda root: overrides)
    monkeypatch.setattr(app, "_speaker_verifier", lambda *args: None)
    monkeypatch.setattr(credentials, "secret_for", lambda values, provider: "test-key" if provider == "openai" else None)
    monkeypatch.setattr(front_brain_factory, "secret_for", credentials.secret_for)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", ControlledWake)
    original = aiohttp.ClientSession.ws_connect
    def connect(session, url, **kwargs):
        if str(url).startswith("wss://api.openai.com/"):
            assert str(url).endswith(f"model={model}")
            async def opened():
                return wire
            return opened()
        return original(session, url, **kwargs)
    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", connect)
    class Audio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._output = self.device = BufferedOutputStream()
            self.device_wait_s = 1
            self._output_latency_ms = self._stream_latency_ms()
            audios.append(self)
    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", Audio)

    async def drive(runtime):
        runtimes.append(runtime)
        await runtime.activate()
        await until(lambda: bool(audios))
        assert runtime.continuous and runtime.conversation_architecture.value == mode
        wire.push("input_audio_buffer.speech_started", item_id="input-a", audio_start_ms=0)
        wire.push("input_audio_buffer.speech_stopped", item_id="input-a", audio_end_ms=500)
        wire.push("input_audio_buffer.committed", item_id="input-a", previous_item_id=None)
        wire.push("conversation.item.input_audio_transcription.completed", item_id="input-a", transcript="Jarvis, combien font deux plus deux ?")
        try:
            await until(lambda: any(item["type"] == "response.create" for item in wire.sent))
        except TimeoutError:
            raise AssertionError({"presentation": runtime._speech.presentation_snapshot(), "speaking": runtime._speech._user_speaking,
                "pending": len(runtime._speech._pending), "tasks": [(task.get_name(), task.done()) for task in runtime._speech._tasks]}) from None
        request = next(item["response"] for item in wire.sent if item["type"] == "response.create")
        assert request["input"] == [{"type": "item_reference", "id": "input-a"}]
        assert "instructions" not in request and "conversation" not in request
        assert not any(item["type"] == "conversation.item.create" for item in wire.sent)
        assert not backend_calls
        if mode == "front_brain":
            await until(lambda: bool(luna_calls))
            assert not gate.is_set()
        else:
            assert not luna_calls and runtime._session.analysis is None
        wire.push("response.created", response={"id": "response-a", "metadata": request["metadata"]})
        wire.push("response.output_item.added", response_id="response-a", output_index=0,
                  item={"type": "message", "id": "message-a", "role": "assistant"})
        wire.push("response.output_audio_transcript.done", response_id="response-a", item_id="message-a", content_index=0, output_index=0, transcript="Quatre.")
        wire.push("response.output_audio.delta", response_id="response-a", item_id="message-a", content_index=0, output_index=0, delta=base64.b64encode(b"\1\0" * 2400).decode())
        wire.push("response.output_audio.done", response_id="response-a", item_id="message-a", content_index=0, output_index=0)
        wire.push("response.done", response={"id": "response-a", "status": "completed", "output": [
            {"id": "message-a", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "audio", "transcript": "Quatre."}]}]})
        await until(lambda: audios[0].device.draining.is_set())
        assert audios[0].device.queued_bytes == 4800
        if mode == "front_brain":
            gate.set()
            await until(lambda: '"kind": "voice.hint.consumed"' in (runtime_root / "trace.jsonl").read_text(encoding="utf-8"))
        await runtime._session._dispatcher.flush()
        before = (await core.voice_ledger.snapshot(runtime.runtime.conversation_id))["snapshot"]
        try:
            assert before["speeches"][0]["intended_text"] is None
            assert before["speeches"][0]["confirmed_text"] is None
        finally:
            audios[0].device.consume()
        async with asyncio.timeout(5):
            while True:
                snapshot = (await core.voice_ledger.snapshot(runtime.runtime.conversation_id))["snapshot"]
                if snapshot["speeches"][0]["confirmed_text"] == "Quatre.":
                    break
                await asyncio.sleep(.002)
        # OpenAI rattache une entrée au dernier élément de la conversation : ici la
        # réponse de l'assistant, jamais connue comme entrée utilisateur.
        wire.push("input_audio_buffer.committed", item_id="rejected", previous_item_id="message-a")
        wire.push("conversation.item.input_audio_transcription.completed", item_id="rejected", transcript="Thank you for watching")
        wire.push("input_audio_buffer.speech_started", item_id="input-b", audio_start_ms=600)
        wire.push("input_audio_buffer.speech_stopped", item_id="input-b", audio_end_ms=1000)
        wire.push("input_audio_buffer.committed", item_id="input-b", previous_item_id="rejected")
        wire.push("conversation.item.input_audio_transcription.completed", item_id="input-b", transcript="Jarvis, ajoute un au résultat.")
        await until(lambda: sum(item["type"] == "response.create" for item in wire.sent) == 2)
        followup = [item["response"] for item in wire.sent if item["type"] == "response.create"][-1]
        assert followup["input"] == [{"type": "item_reference", "id": item} for item in ("input-a", "message-a", "input-b")]
        assert not any(item["type"] == "conversation.item.create" for item in wire.sent)
        # Troisième échange, sans rejet entre deux : le parent annoncé par
        # OpenAI est directement la réponse précédente de l'assistant.
        wire.push("response.created", response={"id": "response-b", "metadata": followup["metadata"]})
        wire.push("response.output_item.added", response_id="response-b", output_index=0,
                  item={"type": "message", "id": "message-b", "role": "assistant"})
        wire.push("response.output_audio_transcript.done", response_id="response-b", item_id="message-b", content_index=0, output_index=0, transcript="Cinq.")
        wire.push("response.done", response={"id": "response-b", "status": "completed", "output": [
            {"id": "message-b", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "audio", "transcript": "Cinq."}]}]})
        wire.push("input_audio_buffer.speech_started", item_id="input-c", audio_start_ms=1200)
        wire.push("input_audio_buffer.speech_stopped", item_id="input-c", audio_end_ms=1600)
        wire.push("input_audio_buffer.committed", item_id="input-c", previous_item_id="message-b")
        wire.push("conversation.item.input_audio_transcription.completed", item_id="input-c", transcript="Jarvis, et encore un ?")
        await until(lambda: sum(item["type"] == "response.create" for item in wire.sent) == 3)
        assert not backend_calls
        await runtime.mute()
    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 15) == 0
        update = next(item["session"] for item in wire.sent if item["type"] == "session.update")
        from jarvis.runtime.back_brain_delegation import conversation_tools
        assert update["tools"] == conversation_tools()
        assert update["audio"]["input"]["turn_detection"]["create_response"] is False
        assert update["audio"]["input"]["turn_detection"]["interrupt_response"] is False
        assert "Answer the admitted user's request directly" in update["instructions"]
        from jarvis.adapters.openai_realtime import CONTINUOUS_BRAIN_OPERATING_RULES
        assert CONTINUOUS_BRAIN_OPERATING_RULES not in update["instructions"]
        assert wire.readers == 1
        turns = await core.conversations.list_turns(runtimes[0].runtime.conversation_id)
        assert [(turn.kind.value, turn.content) for turn in turns] == [
            ("user", "Jarvis, combien font deux plus deux ?"), ("assistant", "Quatre."), ("user", "Jarvis, ajoute un au résultat."),
            ("user", "Jarvis, et encore un ?")]
        events = [json.loads(line) for line in (runtime_root / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        stack = next(item["data"] for item in events if item["kind"] == "voice.stack")
        assert stack["arch"] == mode and stack["arch_source"] == "voice_architecture" and stack["compatibility"] is False
        assert stack["conversation_model"] == model and len(stack["configuration_id"]) == 64
    finally:
        gate.set()
        for audio in audios:
            audio.device.consume()
        for runtime in runtimes:
            await runtime.mute()
        await lunar_client.aclose()
        await server.close()
        await core.stop()
