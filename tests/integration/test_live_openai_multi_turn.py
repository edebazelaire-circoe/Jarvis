"""Conversation directe à plusieurs tours contre le vrai OpenAI Realtime, **opt-in**.

Sauté tant que `JARVIS_LIVE_OPENAI=1` n'est pas posé. La clé est celle des
réglages réels du Control Center (`runtime/control-center-settings.json`).

Ce qu'aucun faux websocket ne prouve : le fournisseur réel donne à chaque
entrée comme `previous_item_id` le dernier élément de la conversation — la
réponse de l'assistant après le premier échange. Le 17/09, ce parent inconnu
de Core bloquait l'activation de tous les tours suivants : Voice restait en
« thinking » sans jamais répondre. Ici l'app réelle (Core, Voice, pile OpenAI)
reçoit trois phrases adressées de suite et doit répondre à chacune.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from aiohttp.test_utils import TestServer
import pytest

from jarvis import app
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import realtime_audio
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_voice_production_composition import ControlledWake

ROOT = Path(__file__).resolve().parents[2]
live_only = pytest.mark.skipif(os.getenv("JARVIS_LIVE_OPENAI") != "1", reason="requires JARVIS_LIVE_OPENAI=1")


PHRASES = ("Jarvis, combien font deux plus deux ?", "Jarvis, et si j'ajoute un ?", "Jarvis, merci, c'est tout.")


async def synthesize_pcm24(key: str, text: str) -> bytes:
    """Phrase nette et adressée : PCM 16 bits mono 24 kHz, le format du micro."""
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {key}"},
                                     json={"model": "gpt-4o-mini-tts", "voice": "alloy", "input": text, "response_format": "pcm"})
        response.raise_for_status()
        return response.content


def trace_kinds(runtime_root: Path) -> list[str]:
    path = runtime_root / "trace.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line)["kind"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@live_only
async def test_real_openai_direct_conversation_answers_every_turn(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard

    real_settings = app._control_settings(ROOT / "runtime")
    architecture = dict((real_settings.get("voice_architecture") or {}).get("config") or {})
    assert architecture.get("architecture") == "simple", "ce test couvre la conversation directe"
    overrides = {**real_settings, "voice_stack": "openai_realtime"}
    stack = dict((overrides.get("voice_stack_settings") or {}).get("openai_realtime") or {})
    overrides["voice_stack_settings"] = {**(overrides.get("voice_stack_settings") or {}),
                                         "openai_realtime": {**stack, "turn_mode": "auto", "echo_cancellation": False}}

    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token="t" * 32)
    server = TestServer(protocol._app())
    await server.start_server()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token_file = runtime_root / "core.token"
    token_file.write_text("t" * 32)
    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", server.port, "Europe/Paris",
                          token_file, 12, 0, "unused", "cedar", True, VoiceArchitecture.LEGACY)
    monkeypatch.setattr(V2Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(app, "_control_settings", lambda root: overrides)
    monkeypatch.setattr(app, "_speaker_verifier", lambda *args: None)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", ControlledWake)

    audios = []

    class Audio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._loop = asyncio.get_running_loop()
            self._output = self.device = BufferedOutputStream()
            self.device_wait_s = 1
            self._output_latency_ms = self._stream_latency_ms()
            audios.append(self)

    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", Audio)
    from jarvis.runtime import credentials

    key = credentials.secret_for(overrides, "openai")
    assert key, "aucune clé OpenAI dans les réglages ni l'environnement"
    phrases = [await synthesize_pcm24(key, text) for text in PHRASES]
    chunk = 2400  # 50 ms

    async def say(audio, pcm: bytes, trailing_silence_s: float) -> None:
        payload = pcm + b"\0\0" * int(24000 * trailing_silence_s)
        for start in range(0, len(payload), chunk * 2):
            audio._enqueue(payload[start:start + chunk * 2])
            await asyncio.sleep(chunk / 24000)

    async def drain_speakers():
        while True:
            for audio in audios:
                audio.device.consume()
            await asyncio.sleep(.05)

    async def wait_for(kind: str, count: int, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            while trace_kinds(runtime_root).count(kind) < count:
                await asyncio.sleep(.1)

    async def drive(runtime):
        drainer = asyncio.create_task(drain_speakers())
        try:
            await runtime.activate()
            async with asyncio.timeout(20):
                while not audios:
                    await asyncio.sleep(.05)
            await say(audios[0], b"\0\0" * 12000, 0)
            for turn, speech in enumerate(phrases, start=1):
                await say(audios[0], speech, 1.5)
                await wait_for("voice.conversation.requested", turn, 30)
                await wait_for("voice.turn_completed", turn, 45)
            await runtime.mute()
        finally:
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 180) == 0
        kinds = trace_kinds(runtime_root)
        assert kinds.count("voice.conversation.requested") >= 3
        assert kinds.count("voice.latency.output_first_write") >= 3
    finally:
        for audio in audios:
            audio.device.consume()
        await server.close()
        await core.stop()
