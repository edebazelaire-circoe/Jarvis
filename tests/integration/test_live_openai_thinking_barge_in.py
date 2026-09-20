"""Reprendre la main pendant la réflexion, contre le vrai OpenAI Realtime, **opt-in**.

Sauté tant que `JARVIS_LIVE_OPENAI=1` n'est pas posé. La clé est celle des
réglages réels du Control Center (lecture seule) ; tout le reste vit dans
`tmp_path`.

Ce qu'aucun faux websocket ne prouve, et qui est exactement l'objet du retour
utilisateur du 19/09/2026 (« je n'arrive pas à t'interrompre quand tu es en
violet ou en bleu ») :

1. le VAD **réel** d'OpenAI émet bien `speech_started` pendant que le cerveau
   réfléchit, c'est-à-dire alors qu'aucun audio ne joue — c'est la porte qui
   était fermée, et rien d'autre ne le démontre ;
2. la surface en fait un abandon de tour, pas un simple silence : Core arrête
   la tâche du cerveau (`core.brain.turn_abandoned`) ;
3. la réponse du tour abandonné n'est **jamais** prononcée ;
4. et la conversation continue : le tour suivant obtient sa réponse, sur la
   même session Realtime — la preuve se fait sur plusieurs tours, pas un.

Le cerveau est ici un backend scripté dont le test tient la lenteur : c'est la
**surface** et le fournisseur qui sont réels, et c'est d'eux que venait le bug.
Le chemin complet jusqu'à l'agent Claude est couvert par
`test_live_brain_full_stack.py`.

Lancer :
    JARVIS_LIVE_OPENAI=1 .venv/Scripts/python.exe -m pytest \\
        tests/integration/test_live_openai_thinking_barge_in.py -s -q
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
from jarvis.domain.v2 import BrainEvent, BrainEventKind, BrainTurnResult, SpeechKind, SpeechRequest
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import realtime_audio
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_live_openai_multi_turn import synthesize_pcm24
from tests.integration.test_voice_production_composition import ControlledWake

ROOT = Path(__file__).resolve().parents[2]
live_only = pytest.mark.skipif(os.getenv("JARVIS_LIVE_OPENAI") != "1", reason="requires JARVIS_LIVE_OPENAI=1")

FIRST = "Jarvis, prépare-moi un résumé complet du dossier."
SECOND = "Jarvis, non, attends, laisse tomber, dis-moi plutôt la capitale de l'Italie."
HELD_ANSWER = "Voici le résumé complet du dossier."


class PacedBrain:
    """Cerveau dont le test tient la lenteur : le premier tour ne répond jamais seul."""

    def __init__(self) -> None:
        self.turns: list[str] = []
        self.cancelled: list[str] = []
        self.hold = asyncio.Event()
        self.first_started = asyncio.Event()

    async def run_turn(self, turn, state, emit) -> BrainTurnResult:
        self.turns.append(turn.correlation_id)
        index = len(self.turns)
        if index == 1:
            self.first_started.set()
            try:
                # Réflexion longue : c'est l'écran violet, et la fenêtre pendant
                # laquelle l'utilisateur ne pouvait pas reprendre la parole.
                await self.hold.wait()
            except asyncio.CancelledError:
                self.cancelled.append(turn.correlation_id)
                raise
        answer = HELD_ANSWER if index == 1 else "La capitale de l'Italie est Rome."
        await emit.emit(BrainEvent(
            kind=BrainEventKind.SPEECH,
            conversation_id=turn.conversation_id,
            correlation_id=turn.correlation_id,
            work_id=f"brain-turn:{turn.correlation_id}",
            speech=SpeechRequest(conversation_id=turn.conversation_id, text=answer,
                                 kind=SpeechKind.RESULT, work_id=f"brain-turn:{turn.correlation_id}"),
        ))
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=answer)


def trace(runtime_root: Path) -> list[dict]:
    path = runtime_root / "trace.jsonl"
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


@live_only
async def test_a_real_voice_takes_the_floor_back_while_the_brain_is_thinking(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard
    from jarvis.runtime import credentials

    real_settings = app._control_settings(ROOT / "runtime")
    key = credentials.secret_for(real_settings, "openai")
    assert key, "aucune clé OpenAI dans les réglages ni l'environnement"

    overrides = {k: v for k, v in real_settings.items() if k != "voice_architecture"}
    stack = dict((overrides.get("voice_stack_settings") or {}).get("openai_realtime") or {})
    overrides.update({
        "voice_arch": "continuous_brain",
        "voice_stack": "openai_realtime",
        # Un tour cerveau retenu dure plus longtemps que le délai d'activité.
        "active_timeout_s": 0,
        "voice_stack_settings": {**(overrides.get("voice_stack_settings") or {}),
                                 "openai_realtime": {**stack, "turn_mode": "auto", "echo_cancellation": False}},
    })

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token = "c" * 32
    token_file = runtime_root / "core.token"
    token_file.write_text(token, encoding="utf-8")
    journal = RuntimeJournal(runtime_root)

    brain = PacedBrain()
    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=brain, diagnostics=journal)
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)
    server = TestServer(protocol._app())
    await server.start_server()

    settings = V2Settings(tmp_path / "data", runtime_root, "127.0.0.1", server.port, "Europe/Paris",
                          token_file, 12, 0, "unused", "cedar", True, VoiceArchitecture.CONTINUOUS_BRAIN)
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

    speech = {text: await synthesize_pcm24(key, text) for text in (FIRST, SECOND)}
    chunk = 2400  # 50 ms à 24 kHz

    def count(kind: str) -> int:
        return sum(1 for entry in trace(runtime_root) if entry["kind"] == kind)

    async def wait_until(kind: str, minimum: int, timeout: float, what: str) -> None:
        try:
            async with asyncio.timeout(timeout):
                while count(kind) < minimum:
                    await asyncio.sleep(.2)
        except TimeoutError:
            raise AssertionError(f"délai dépassé ({timeout:.0f} s) en attendant : {what}") from None

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

    async def drive(runtime):
        drainer = asyncio.create_task(drain_speakers())
        try:
            await runtime.activate()
            async with asyncio.timeout(30):
                while not audios:
                    await asyncio.sleep(.05)

            # --- Tour 1 : le cerveau part, et ne rend pas la main.
            await say(audios[0], speech[FIRST], 1.8)
            await wait_until("voice.brain_turn_submitted", 1, 60, "tour 1 soumis à Core")
            await asyncio.wait_for(brain.first_started.wait(), timeout=60)
            # Rien ne joue : c'est exactement l'état où l'interruption n'existait pas.
            assert not audios[0].playing if hasattr(audios[0], "playing") else True

            # --- L'utilisateur reprend la parole pendant la réflexion.
            await say(audios[0], speech[SECOND], 1.8)
            await wait_until("voice.brain_turn_abandoned", 1, 60,
                             "la surface abandonne le tour en réflexion")
            await wait_until("core.brain.turn_abandoned", 1, 60,
                             "Core arrête la tâche du cerveau")

            # --- Le tour suivant obtient sa réponse : la conversation continue.
            await wait_until("voice.brain_turn_submitted", 2, 60, "tour 2 soumis à Core")
            await wait_until("voice.speech.completed", 1, 120, "réponse du tour 2 prononcée")
            await runtime.mute()
        finally:
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 600) == 0
        entries = trace(runtime_root)
        kinds = [entry["kind"] for entry in entries]

        # 1. Le tour en réflexion a bien été abandonné, jusque dans Core.
        assert kinds.count("voice.brain_turn_abandoned") >= 1
        assert kinds.count("core.brain.turn_abandoned") >= 1
        assert brain.cancelled == [brain.turns[0]], "la tâche du premier tour doit avoir été annulée"

        # 2. Sa réponse n'a jamais été prononcée.
        spoken = " ".join(str(entry.get("message") or "") for entry in entries
                          if entry["kind"] in ("voice.speech.dispatched", "voice.speech.started",
                                               "voice.speech.completed"))
        assert HELD_ANSWER not in spoken

        # 3. Et le tour suivant, lui, a parlé : plusieurs tours sur la même session.
        assert kinds.count("voice.brain_turn_submitted") >= 2
        assert kinds.count("voice.speech.completed") >= 1
    finally:
        brain.hold.set()
        for audio in audios:
            audio.device.consume()
        await server.close()
        await core.stop()
