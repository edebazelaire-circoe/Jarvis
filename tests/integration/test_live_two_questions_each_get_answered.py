"""Deux questions de suite, deux réponses entendues — contre les vrais fournisseurs, **opt-in**.

Sauté tant que `JARVIS_LIVE_OPENAI=1` **et** `JARVIS_LIVE_CLAUDE=1` ne sont pas
posés. Même composition que `test_live_brain_full_stack.py` : Voice (pile OpenAI
Realtime réelle, micro TTS, faux haut-parleur) → Core → `ControlCenterBrainBackend`
→ vrai CLI `claude`.

Ce qu'aucun faux ne prouve, et que l'utilisateur a signalé deux fois le
19/09/2026 : il pose une question, reparle avant la réponse, et la réponse à la
première question **n'est jamais dite**. Dans la trace d'incident elle est
écartée 3 ms après sa naissance (`presentation_decided` / `deferred` /
`stale_source`, `age_ms: 3`), parce qu'une intention neuve périmait
mécaniquement la précédente. Sa décision : « une réponse sans retard faut
qu'elle soit dite si c'est cohérent avec le contexte ».

Le test tient la course pour de vrai : la deuxième phrase part **pendant** que
le cerveau réfléchit encore à la première (tour soumis, réponse pas encore en
file). Sur le code d'avant, la réponse à la première question n'arrive jamais à
`voice.speech.completed`.

Mesuré le 19/09/2026 : tel quel, ce test échoue encore, mais **pas** pour la
raison qu'il vise. Un barge-in est confirmé sur le silence qui suit la question,
pendant que le cerveau réfléchit (`voice.barge_in_confirming`, `local_evidence:
True`, ~0,7 s après la soumission du tour) ; le tour est alors abandonné et la
réponse retirée en `turn_abandoned` avant que sa fraîcheur ne soit jamais jugée.
C'est le chantier du barge-in acoustique, pas celui-ci. Pour mesurer la
péremption sans ce masque, on désarme la confirmation acoustique par ses propres
réglages de production (aucun double de test) :

    JARVIS_LIVE_OPENAI=1 JARVIS_LIVE_CLAUDE=1 \
    JARVIS_BARGE_IN_MIN_VOICED_MS=5000 JARVIS_BARGE_IN_MIN_MARGIN_DB=60 \
        .venv/Scripts/python.exe -m pytest \
        tests/integration/test_live_two_questions_each_get_answered.py -s -q

Lancer tel quel (la chaîne entière, barge-in compris) :
    JARVIS_LIVE_OPENAI=1 JARVIS_LIVE_CLAUDE=1 .venv/Scripts/python.exe -m pytest \
        tests/integration/test_live_two_questions_each_get_answered.py -s -q
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from aiohttp.test_utils import TestServer
import pytest

from jarvis import app
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import realtime_audio
from jarvis.runtime.journal import RuntimeJournal
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedOutputStream
from tests.integration.test_live_brain_full_stack import AGENT_SETTING_KEYS, brain_speech, brief, free_port, trace
from tests.integration.test_live_openai_multi_turn import synthesize_pcm24
from tests.integration.test_voice_production_composition import ControlledWake

ROOT = Path(__file__).resolve().parents[2]
live_only = pytest.mark.skipif(
    os.getenv("JARVIS_LIVE_OPENAI") != "1" or os.getenv("JARVIS_LIVE_CLAUDE") != "1",
    reason="requires JARVIS_LIVE_OPENAI=1 and JARVIS_LIVE_CLAUDE=1",
)

#: Première question : elle demande au cerveau d'aller lire, donc il réfléchit
#: assez longtemps pour que la seconde arrive avant sa réponse. C'est la course
#: que l'utilisateur subit, pas une course fabriquée.
FIRST = "Jarvis, combien y a-t-il de fichiers dans le dossier docs de ce projet ?"
SECOND = "Jarvis, et combien font deux plus deux ?"

STORY_KINDS = (
    "voice.brain_turn_submitted", "voice.reflex.started", "agent.input", "agent.ask",
    "voice.speech.presentation_decided", "voice.speech.queued", "voice.speech.dispatched",
    "voice.speech.started", "voice.speech.completed", "voice.speech.superseded",
    "voice.speech.expired", "voice.speech.abandoned", "voice.speech.error_withheld",
    "core.brain.replies_pending", "core.brain.replies_superseded",
)


@live_only
async def test_a_second_question_does_not_bury_the_answer_to_the_first(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard
    from jarvis.adapters.control_center_brain import ControlCenterBrainBackend
    from jarvis.runtime import credentials
    from jarvis.runtime.control_center import ControlCenter
    from jarvis.runtime.conversation_event_forwarder import (
        ConversationEventForwarder, CoreConversationEventTransport,
    )
    from jarvis.runtime.work_ingress import CoreWorkTransport, WorkIngressForwarder

    real_settings = app._control_settings(ROOT / "runtime")
    key = credentials.secret_for(real_settings, "openai")
    assert key, "aucune clé OpenAI dans les réglages ni l'environnement"

    overrides = {k: v for k, v in real_settings.items() if k != "voice_architecture"}
    stack = dict((overrides.get("voice_stack_settings") or {}).get("openai_realtime") or {})
    overrides.update({
        "voice_arch": "continuous_brain",
        "voice_stack": "openai_realtime",
        "active_timeout_s": 0,
        "voice_stack_settings": {**(overrides.get("voice_stack_settings") or {}),
                                 "openai_realtime": {**stack, "turn_mode": "auto", "echo_cancellation": False}},
    })

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    token = "c" * 32
    token_file = runtime_root / "core.token"
    token_file.write_text(token, encoding="utf-8")
    (runtime_root / "control-center-settings.json").write_text(
        json.dumps({k: real_settings[k] for k in AGENT_SETTING_KEYS if k in real_settings}), encoding="utf-8")
    ui_port = free_port()
    monkeypatch.setenv("JARVIS_UI_PORT", str(ui_port))
    journal = RuntimeJournal(runtime_root)

    brain_backend = ControlCenterBrainBackend(base_url=app._control_center_url(), timeout_s=600.0)
    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=brain_backend,
                                 diagnostics=journal, **app._brain_availability_from_env())
    await core.start()
    protocol = LocalProtocolServer(core, host="127.0.0.1", port=0, token=token)
    server = TestServer(protocol._app())
    await server.start_server()

    control = ControlCenter(
        runtime_root=runtime_root,
        project_root=ROOT,
        work_ingress=WorkIngressForwarder(
            source="claude", journal=journal,
            transport=CoreWorkTransport(host="127.0.0.1", port=server.port, token_file=token_file)),
        conversation_events=ConversationEventForwarder(
            journal=journal,
            transport=CoreConversationEventTransport(host="127.0.0.1", port=server.port, token_file=token_file)),
    )
    await control.start(port=ui_port)

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
    pending: asyncio.Queue[bytes] = asyncio.Queue()

    def count(predicate) -> int:
        return sum(1 for entry in trace(runtime_root) if predicate(entry))

    def kind_is(kind):
        return lambda entry: entry["kind"] == kind

    async def wait_until(predicate, minimum: int, timeout: float, what: str) -> None:
        try:
            async with asyncio.timeout(timeout):
                while count(predicate) < minimum:
                    await asyncio.sleep(.25)
        except TimeoutError:
            raise AssertionError(f"délai dépassé ({timeout:.0f} s) en attendant : {what}") from None

    async def microphone():
        """Un vrai micro ne se tait jamais : silence entre les phrases, en temps réel.

        Pousser une salve puis s'arrêter net fabrique un second segment de VAD
        chez le fournisseur, donc un faux barge-in : mesurer là-dessus mesurerait
        la sonde, pas JARVIS.
        """

        buffer = b""
        while True:
            if not buffer and not pending.empty():
                buffer = pending.get_nowait()
            block, buffer = (buffer[:chunk * 2], buffer[chunk * 2:]) if buffer else (b"\0\0" * chunk, b"")
            if audios:
                audios[0]._enqueue(block.ljust(chunk * 2, b"\0"))
            await asyncio.sleep(chunk / 24000)

    async def say(pcm: bytes) -> None:
        await pending.put(pcm)
        async with asyncio.timeout(60):
            while not pending.empty():
                await asyncio.sleep(.05)

    async def drain_speakers():
        while True:
            for audio in audios:
                audio.device.consume()
            await asyncio.sleep(.05)

    async def drive(runtime):
        drainer = asyncio.create_task(drain_speakers())
        mic = asyncio.create_task(microphone())
        try:
            await runtime.activate()
            async with asyncio.timeout(20):
                while not audios:
                    await asyncio.sleep(.05)
            assert runtime.voice_arch is VoiceArchitecture.CONTINUOUS_BRAIN

            # Question 1. On attend qu'elle atteigne le cerveau, pas sa réponse.
            await say(speech[FIRST])
            await wait_until(kind_is("voice.brain_turn_submitted"), 1, 60, "tour 1 soumis à Core")
            await wait_until(kind_is("agent.input"), 1, 90, "tour 1 reçu par l'agent Claude")

            # Question 2, pendant que le cerveau réfléchit encore à la première :
            # c'est exactement la course que l'utilisateur a subie.
            assert count(lambda e: brain_speech(e, "voice.speech.completed")) == 0, (
                "le cerveau a déjà fini de parler : la course n'a pas eu lieu, test non concluant")
            await say(speech[SECOND])
            await wait_until(kind_is("voice.brain_turn_submitted"), 2, 60, "tour 2 soumis à Core")

            # Les deux réponses doivent être entendues, pas une.
            await wait_until(lambda e: brain_speech(e, "voice.speech.completed"), 2, 300,
                             "les deux réponses du cerveau prononcées")
            await runtime.mute()
        finally:
            drainer.cancel()
            mic.cancel()
            await asyncio.gather(drainer, mic, return_exceptions=True)

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    started = time.monotonic()
    failure: BaseException | None = None
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 900) == 0
    except BaseException as exc:  # noqa: BLE001 - rapport complet, puis on relève
        failure = exc
    finally:
        entries = trace(runtime_root)
        print(f"\n=== durée totale : {time.monotonic() - started:.1f} s")
        for entry in entries:
            if entry["kind"] in STORY_KINDS:
                print("   ", brief(entry))
        for audio in audios:
            audio.device.consume()
        await control.stop()
        await server.close()
        await core.stop()
        await brain_backend.close()
    if failure is not None:
        raise failure

    spoken = [entry for entry in entries if brain_speech(entry, "voice.speech.completed")]
    correlations = {(entry.get("data") or {}).get("correlation_id") for entry in spoken}
    submitted = [(entry.get("data") or {}).get("correlation_id")
                 for entry in entries if entry["kind"] == "voice.brain_turn_submitted"]
    abandoned = [(entry.get("data") or {}).get("reason") for entry in entries
                 if entry["kind"] == "voice.speech.abandoned"]
    assert len(spoken) >= 2, (
        "une seule réponse a été prononcée pour deux questions ; "
        f"paroles soldées sans être dites : {abandoned or 'aucune'}")
    # La réponse à la PREMIÈRE question, celle qui mourait `deferred/stale_source`.
    assert submitted[0] in correlations, "la réponse à la première question n'a jamais été dite"
    # Et rien n'a été soldé en silence : ou c'est dit, ou la trace dit qui l'a retiré.
    for entry in entries:
        if entry["kind"] == "voice.speech.abandoned":
            assert entry["level"] == "warning" and (entry.get("data") or {}).get("reason")
