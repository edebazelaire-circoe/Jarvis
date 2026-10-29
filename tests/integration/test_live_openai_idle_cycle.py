"""ACTIVE -> IDLE -> reopen by speech -> SLEEP, contre le vrai GPT-Live, **opt-in**.

Sauté tant que `JARVIS_LIVE_GPT_LIVE=1` n'est pas posé (et `OPENAI_API_KEY`). Core (données dans `tmp_path`,
port 0), la pile Voice, la composition `_run_voice_v2` et la séance GPT-Live sont les vrais ; seul le micro est
simulé : une horloge de 80 ms pousse du silence ou une phrase de synthèse vocale, soit dans la file d'envoi de la
séance quand elle est ouverte, soit dans le détecteur de parole d'IDLE (le vrai `IdleSpeechDetector`) quand le
micro de repos est seul.

Ce que ça prouve que les faux websockets ne prouvent pas :
- `idle_timeout_s` (6 s ici) ferme réellement la séance fournisseur (confirmée, `voice.background`) ;
- la parole en IDLE rouvre une **vraie** séance GPT-Live, avec la parole tampon, et GPT-Live y répond par la voix ;
- passé `sleep_timeout_s`, la parole ne rouvre plus rien.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from aiohttp.test_utils import TestServer
import pytest

from jarvis import app
from jarvis.adapters.wakeword_own_stream import SPEECH_LABEL
from jarvis.audio.resampling import StreamingPcm16Resampler
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import realtime_audio
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_live_openai_multi_turn import synthesize_pcm24, trace_kinds

ROOT = Path(__file__).resolve().parents[2]
gpt_live_only = pytest.mark.skipif(
    os.getenv("JARVIS_LIVE_GPT_LIVE") != "1" or not os.getenv("OPENAI_API_KEY"),
    reason="requires JARVIS_LIVE_GPT_LIVE=1 and OPENAI_API_KEY",
)

IDLE_AFTER_S = 6.0
SLEEP_AFTER_S = 22.0
TICK_S = 0.08  # 80 ms : une trame du détecteur de mot d'éveil à 16 kHz
FIRST = "Jarvis, combien font deux plus deux ?"
SECOND = "Jarvis, quelle est la capitale de la France ?"
THIRD = "Jarvis, es-tu là ?"


class SilentKey:
    """La touche manuelle : jamais appuyée pendant ce scénario."""

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        pass

    async def detections(self):
        await asyncio.Event().wait()
        yield ""

    async def suspend(self) -> None: ...
    async def suspend_for_active_session(self) -> None: ...
    async def resume(self) -> None: ...
    async def close(self) -> None: ...


class OpenInput:
    """Un flux d'entrée ouvert : sans lui la séance ne sait pas que le micro bat, et le délai attend le point sûr."""

    def start(self) -> None: ...
    def stop(self, *, ignore_errors=True) -> None: ...
    def abort(self, *, ignore_errors=True) -> None: ...
    def close(self, *, ignore_errors=True) -> None: ...


class SimulatedRestMicrophone:
    """Le détecteur de repos : le vrai `IdleSpeechDetector` derrière l'interface `WakeWordBackend`."""

    def __init__(self, speech_detector) -> None:  # noqa: ANN001
        self.speech_detector = speech_detector
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.open = True

    async def detections(self):
        while True:
            yield await self.queue.get()

    async def suspend(self) -> None:
        self.open = False

    async def suspend_for_active_session(self) -> None:
        self.open = False

    async def resume(self) -> None:
        self.open = True

    async def close(self) -> None:
        self.open = False

    def set_speech_listening(self, enabled: bool) -> None:
        self.speech_detector.set_enabled(enabled)

    def take_speech_preroll(self):  # noqa: ANN201
        pcm, rate = self.speech_detector.take_preroll()
        return (pcm, rate) if pcm else None

    def hear(self, frame: bytes) -> None:
        if self.open and self.speech_detector.enabled and self.speech_detector.feed(frame):
            self.queue.put_nowait(SPEECH_LABEL)


@gpt_live_only
async def test_real_gpt_live_closes_at_idle_reopens_on_speech_and_sleeps(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard
    from jarvis.runtime import credentials, simple_wake_word

    real_settings = app._control_settings(ROOT / "runtime")
    overrides = {**real_settings, "voice_stack": "openai_realtime", "voice_architecture": {
        "schema_version": 1, "compatibility": None,
        "config": {"architecture": "duplex", "conversation_model": {"provider_id": "openai", "model_id": "gpt-live-1"},
                   "client_delegation": True, "idle_timeout_s": IDLE_AFTER_S, "sleep_timeout_s": SLEEP_AFTER_S,
                   "brain_orchestration": False, "barge_in_decider": "provider"}}}
    stack = dict((overrides.get("voice_stack_settings") or {}).get("openai_realtime") or {})
    overrides["voice_stack_settings"] = {**(overrides.get("voice_stack_settings") or {}),
                                         "openai_realtime": {**stack, "turn_mode": "auto", "echo_cancellation": False}}
    overrides.pop("wake_word", None)

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
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", SilentKey)

    rest_microphones: list[SimulatedRestMicrophone] = []

    def simulated_backends(**kwargs):  # noqa: ANN003
        rest_microphones.append(SimulatedRestMicrophone(kwargs["speech_detector"]))
        return rest_microphones

    monkeypatch.setattr(simple_wake_word, "simple_wake_backends", simulated_backends)

    audios = []

    class Audio(realtime_audio.SoundDeviceRealtimeAudio):
        async def start(self):
            self._loop = asyncio.get_running_loop()
            self._output = self.device = BufferedOutputStream()
            self._input = OpenInput()
            self.device_wait_s = 1
            self._output_latency_ms = self._stream_latency_ms()
            audios.append(self)

    monkeypatch.setattr(realtime_audio, "SoundDeviceRealtimeAudio", Audio)

    key = credentials.secret_for(overrides, "openai")
    assert key, "aucune clé OpenAI dans les réglages ni l'environnement"
    phrases = {text: await synthesize_pcm24(key, text) for text in (FIRST, SECOND, THIRD)}

    runtimes = []
    from jarvis.runtime.voice_v2 import PersistentVoiceRuntime

    original_init = PersistentVoiceRuntime.__init__

    def remember(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        original_init(self, *args, **kwargs)
        runtimes.append(self)

    monkeypatch.setattr(PersistentVoiceRuntime, "__init__", remember)

    pending: asyncio.Queue[bytes] = asyncio.Queue()
    resampler = StreamingPcm16Resampler(source_rate=24000, target_rate=16000)
    block_bytes = int(24000 * TICK_S) * 2

    async def microphone():
        """Un vrai micro ne se tait jamais : du silence entre les phrases, en temps réel."""
        buffer = b""
        while True:
            if not buffer and not pending.empty():
                buffer = pending.get_nowait()
            block, buffer = (buffer[:block_bytes], buffer[block_bytes:]) if buffer else (b"", b"")
            block = block.ljust(block_bytes, b"\0")
            runtime = runtimes[0] if runtimes else None
            if runtime is not None and runtime.runtime.state is VoiceLifecycleState.ACTIVE and audios:
                audios[-1]._enqueue(block)
            elif rest_microphones:
                frame = resampler.process(block)
                if len(frame) == 1280 * 2:
                    rest_microphones[0].hear(frame)
            await asyncio.sleep(TICK_S)

    async def say(text: str) -> None:
        await pending.put(phrases[text])
        async with asyncio.timeout(30):
            while not pending.empty():
                await asyncio.sleep(.05)

    async def drain_speakers():
        while True:
            for audio in audios:
                audio.device.consume()
            await asyncio.sleep(.05)

    async def wait_for(kind: str, count: int, timeout: float) -> None:
        try:
            async with asyncio.timeout(timeout):
                while trace_kinds(runtime_root).count(kind) < count:
                    await asyncio.sleep(.1)
        except TimeoutError:
            seen = [k for k in trace_kinds(runtime_root) if k.startswith("voice.") or k.startswith("wake")]
            raise AssertionError(f"jamais vu {kind} x{count} ; trace voix : {seen[-40:]}") from None

    async def wait_state(runtime, state: VoiceLifecycleState, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            while runtime.runtime.state is not state:
                await asyncio.sleep(.1)

    async def scenario():
        async with asyncio.timeout(20):
            while not runtimes or not rest_microphones:
                await asyncio.sleep(.05)
        runtime = runtimes[0]
        drainer, mic = asyncio.create_task(drain_speakers()), asyncio.create_task(microphone())
        try:
            # 1. « Hey Jarvis » : première séance GPT-Live réelle, une question, une réponse.
            await rest_microphones[0].queue.put("jarvis")
            await wait_for("voice.active", 1, 40)
            await say(FIRST)
            await wait_for("voice.output_started", 1, 45)
            # 2. Silence : la séance fournisseur est fermée au bout de IDLE_AFTER_S, le micro de repos prend le relais.
            await wait_state(runtime, VoiceLifecycleState.BACKGROUND, 60)
            assert runtime.rest_level.value == "idle"
            assert trace_kinds(runtime_root).count("voice.idle") == 1
            # 3. L'utilisateur reparle sans dire « Hey Jarvis » : une séance neuve s'ouvre avec sa parole tampon.
            await say(SECOND)
            await wait_for("voice.idle.speech", 1, 30)
            await wait_for("voice.active", 2, 40)
            assert trace_kinds(runtime_root).count("voice.idle.preroll") == 1
            await wait_for("voice.output_started", 2, 60)
            # 4. Silence jusqu'au sommeil : plus de séance, plus de réouverture par la parole.
            await wait_state(runtime, VoiceLifecycleState.BACKGROUND, 60)
            async with asyncio.timeout(60):
                while runtime.rest_level.value != "sleep":
                    await asyncio.sleep(.2)
            assert runtime._last_displayed == "sleep"  # noqa: SLF001
            await say(THIRD)
            await asyncio.sleep(4)
            assert runtime.runtime.state is VoiceLifecycleState.BACKGROUND
            assert trace_kinds(runtime_root).count("voice.active") == 2
        finally:
            drainer.cancel()
            mic.cancel()
            await asyncio.gather(drainer, mic, return_exceptions=True)
            for runtime in runtimes:
                runtime._stop.set()  # noqa: SLF001

    task = asyncio.create_task(scenario())
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 420) == 0
        await task
        kinds = trace_kinds(runtime_root)
        assert kinds.count("voice.timeout") >= 2
        assert "voice.timeout_forced" not in kinds  # le point sûr était là : fermeture à IDLE_AFTER_S, pas au plafond
        assert "voice.provider_error" not in kinds and "voice.failure" not in kinds
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for audio in audios:
            audio.device.consume()
        await server.close()
        await core.stop()
