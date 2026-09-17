"""Une tâche de fond qui meurt doit être dite à voix haute.

Retour utilisateur du 16/09/2026 : « les tâches se terminent ou meurent en
échec SANS aucun feedback vocal ». La trace de ce matin-là montre pourquoi —
rien, dans toute la chaîne, ne menait d'un changement d'état de travail à une
parole prononcée :

1. `WorkAttentionPolicy` relevait bien l'échec, mais aucun réveil n'était
   câblé : le cerveau ne l'apprenait qu'au tour suivant de l'utilisateur, donc
   jamais s'il se taisait (`wake: false` dans `core.work.attention`) ;
2. et la seule voie de parole spontanée, `announce_notice`, publiait une
   `SpeechRequest` sans source, que l'ordonnanceur vocal différait pour
   toujours (`unknown_source`).

Ce test parcourt la chaîne réelle, de l'observation de travail jusqu'à la
commande envoyée au fournisseur : app factory, Core HTTP/SQLite, admission,
ordonnanceur de parole, adaptateur canonique. Seuls le websocket du
fournisseur, l'entrée du mot de réveil et les flux audio natifs sont pilotés.

Aucun tour utilisateur ne déclenche l'annonce : c'est tout l'objet du test.
"""
from __future__ import annotations

import asyncio
import base64

import aiohttp
from aiohttp.test_utils import TestServer

from jarvis import app
from jarvis.adapters.openai_realtime import SPEECH_ID_METADATA_KEY
from jarvis.core.brain_service import BRAIN_WOKEN_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.v2 import (
    BrainEvent, BrainEventKind, BrainTurnResult, BrainTurnSource, SpeechKind, SpeechRequest,
)
from jarvis.domain.work_attention_prompt import WORK_ATTENTION_WAKE_PROMPT
from jarvis.protocol.server import LocalProtocolServer
from jarvis.runtime import credentials, realtime_audio
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import V2Settings, VoiceArchitecture
from tests.fakes.audio_device import BufferedInputStream, BufferedOutputStream
from tests.integration.test_voice_production_composition import ControlledWake, ControlledWire

#: Ce que le cerveau décide de dire du sous-agent mort. Core n'en écrit pas un
#: mot : la phrase vient du backend (Décisions 13 et 14).
ANNOUNCEMENT = "L'agent qui comparait les branches Git est tombé. Je le relance ?"
PCM = b"\1\0" * 2400


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.001)


class WakeAnnouncingBackend:
    """Backend qui ne parle que sur le tour ouvert par un changement de travail.

    Il exige ce que le tour doit porter : la marque `system`, la consigne de
    réveil, et le changement lui-même dans le contexte de travail. Un tour
    d'utilisateur, ici, il n'y en a aucun.
    """

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []
        self.attention: list[tuple[str, str, str]] = []

    async def run_turn(self, turn, state, emit):  # pragma: no cover - Core préfère le contexte
        raise AssertionError("Core doit remettre le contexte de travail au backend")

    async def run_turn_with_context(self, turn, context, emit):
        self.turns.append((turn.source.value, turn.text))
        notes = context.work.attention if context.work else ()
        self.attention.extend((note.external_id, note.status.value, note.error_class) for note in notes)
        if turn.source is not BrainTurnSource.SYSTEM or not notes:
            return BrainTurnResult(correlation_id=turn.correlation_id)
        await emit.emit(BrainEvent(
            kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
            correlation_id=turn.correlation_id,
            speech=SpeechRequest(conversation_id=turn.conversation_id, text=ANNOUNCEMENT,
                                 kind=SpeechKind.RESULT),
        ))
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=ANNOUNCEMENT)


def observation(external_id: str, status: str, observed_at: str, **fields) -> dict:
    entry = {"source": "claude", "external_id": external_id, "status": status,
             "observed_at": observed_at, **fields}
    return {"source": "claude", "producer_id": "cc-1", "observations": [entry]}


async def test_an_interrupted_subagent_is_announced_without_any_user_turn(tmp_path, monkeypatch):
    from jarvis.adapters import wakeword_keyboard

    backend = WakeAnnouncingBackend()
    diagnostics: list[tuple[str, dict]] = []

    class RecordingSink:
        def emit(self, kind, message, *, level="info", data=None):
            diagnostics.append((kind, dict(data or {})))

    core = JarvisCoreApplication(data_root=tmp_path / "data", brain_backend=backend,
                                 diagnostics=RecordingSink(), work_attention_wake_interval_s=0.0)
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
    monkeypatch.setattr(credentials, "secret_for",
                        lambda values, provider: "test-only-key" if provider == "openai" else None)
    monkeypatch.setattr(wakeword_keyboard, "KeyboardWakeWordBackend", ControlledWake)
    wire, audios, runtimes = ControlledWire(), [], []
    original_connect = aiohttp.ClientSession.ws_connect

    def connect(client, url, **kwargs):
        if str(url).startswith("wss://api.openai.com/"):
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

            # Une intention doit exister pour que la surface ait une source
            # courante ; un seul tour adressé la crée, et il ne dit rien.
            await runtime.core.submit_brain_turn(
                conversation, content="Compare les branches Git.", correlation_id="git-origin",
            )
            await until(lambda: backend.turns and backend.turns[0][0] == "realtime")

            # Le sous-agent tourne, puis meurt avec son hôte — exactement le
            # `process_stopped` du 16/09/2026. Personne ne parle.
            await runtime.core.ingest_work_observations(
                observation("toolu_git", "running", "2026-09-16T07:37:31+00:00", label="Git branches vs main"))
            before = len(creates())
            await runtime.core.ingest_work_observations(
                observation("toolu_git", "interrupted", "2026-09-16T07:38:57+00:00",
                            error_class="process_stopped"))

            # Core ouvre un tour de lui-même, le cerveau y répond, et la parole
            # atteint réellement le fournisseur.
            await until(lambda: len(creates()) > before)
            assert ("system", WORK_ATTENTION_WAKE_PROMPT) in backend.turns
            assert backend.attention == [("toolu_git", "interrupted", "process_stopped")]
            assert [data["notes"] for kind, data in diagnostics if kind == BRAIN_WOKEN_KIND] == [1]

            command = creates()[-1]
            assert ANNOUNCEMENT in command["instructions"]

            # La parole est bien présentée, pas différée : c'est la régression
            # que ce test garde. Avant, elle restait `unknown_source` à jamais.
            candidates = runtime._speech.presentation_snapshot()["candidates"]
            announced = [item for item in candidates if item["speech_id"] == command["metadata"][SPEECH_ID_METADATA_KEY]]
            assert len(announced) == 1
            assert announced[0]["status"] in ("selected", "started")
            assert announced[0]["source"] is not None

            # Et elle est entendue de bout en bout.
            device = audios[0].device
            device.draining.clear()
            part = dict(response_id="response-wake", item_id="audio-wake",
                        content_index=0, output_index=0)
            wire.push("response.created", response={"id": "response-wake", "metadata": command["metadata"]})
            wire.push("response.output_audio_transcript.done", **part, transcript=ANNOUNCEMENT)
            wire.push("response.output_audio.delta", **part, delta=base64.b64encode(PCM).decode())
            wire.push("response.output_audio.done", **part)
            wire.push("response.done", response={
                "id": "response-wake", "status": "completed", "metadata": command["metadata"],
                "usage": {"input_tokens": 1, "output_tokens": 2},
                "output": [{"id": "audio-wake", "type": "message", "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "audio", "transcript": ANNOUNCEMENT}]}],
            })
            await until(device.draining.is_set)
            device.consume()

            async with asyncio.timeout(5):
                while True:
                    snapshot = (await runtime.core.voice_snapshot(conversation))["snapshot"]
                    heard = [item["confirmed_text"] for item in snapshot["speeches"]
                             if item["confirmed_text"] is not None]
                    if heard:
                        break
                    await asyncio.sleep(.001)
            assert heard == [ANNOUNCEMENT]
        finally:
            for audio in audios:
                audio.device.consume()
            await runtime.mute()

    monkeypatch.setattr(PersistentVoiceRuntime, "run", drive)
    try:
        assert await asyncio.wait_for(app._run_voice_v2(), 30) == 0
        conversation = runtimes[0].runtime.conversation_id
        # Le tour de réveil fait autorité mais personne ne l'a dit : il reste
        # hors du contexte de conversation relu par le modèle vocal.
        context = await core.conversations.rehydration_context(conversation)
        assert WORK_ATTENTION_WAKE_PROMPT not in [turn["content"] for turn in context["recent_turns"]]
    finally:
        for audio in audios:
            audio.device.consume()
        await server.close()
        await core.stop()
