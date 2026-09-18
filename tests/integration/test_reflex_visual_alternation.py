"""La couleur de l'orbe quand le préambule parle et que le cerveau réfléchit encore.

Vraie normalisation du fournisseur (frontend OpenAI), vrai bridge, vrai
ordonnanceur de parole, vrai bus de signaux écrit sur disque : seul le fil du
websocket est joué à la main. Rien ici ne prétend mesurer une lecture matérielle.

Ce que le test fixe est la suite de couleurs vue par l'utilisateur, pas un
champ interne : violet pendant que le cerveau réfléchit, orange pendant qu'on
parle, **violet à nouveau** dès que le préambule se tait alors que le cerveau
n'a toujours pas répondu, orange quand la réponse arrive, puis la veille.
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from jarvis.adapters.openai_realtime import OUTPUT_ID_METADATA_KEY
from jarvis.domain.v2 import SpeechKind, SpeechPriority, SpeechRequest, VoiceLifecycleState
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from jarvis.v2_config import VoiceArchitecture
from tests.fakes.speech_context import source
from tests.unit.test_realtime_frontend_pipeline import pipeline, until  # noqa: F401
from tests.unit.test_voice_duplex import EmptyCore, RecordingJournal


#: Palette réelle de l'orbe, lue dans le rendu du Control Center : le test
#: parle de violet et d'orange, pas de noms d'états internes.
ORB = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_work.js"


def palette() -> dict[str, str]:
    text = ORB.read_text(encoding="utf-8")
    colors = dict(re.findall(r"(idle|listening|speaking|thinking):\[(\d+,\d+,\d+)\]", text))
    assert colors["thinking"] == "175,88,255" and colors["speaking"] == "255,151,61"
    return {"thinking": "violet", "speaking": "orange",
            "listening": "écoute", "idle": "veille"}


class Wake:
    async def suspend_for_active_session(self) -> None: ...
    async def resume(self) -> None: ...
    async def close(self) -> None: ...


class BrainCore:
    """Core qui accepte le tour et ne répond jamais tout seul : le cerveau travaille."""

    def __init__(self) -> None:
        self.turns: list[str] = []

    async def submit_brain_turn(self, conversation_id, *, content, correlation_id, source="realtime",  # noqa: ANN001
                                addressing="addressed", provider_item_id=None, interrupted_speech_id=None):
        self.turns.append(content)
        return {"turn_id": f"turn-{len(self.turns)}", "revision": len(self.turns), "duplicate": False}

    async def append_turn(self, *args, **kwargs):  # noqa: ANN002,ANN003
        return {"id": "turn"}


class Speaker:
    """Périphérique de test : il accepte les octets, il ne prétend rien drainer."""

    latency = 0

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, block) -> None:  # noqa: ANN001
        self.writes.append(block)


async def rig(pipeline, tmp_path):  # noqa: ANN001
    facade, wire, client, conversation, events, _history = pipeline
    bus = VisualSignalBus(tmp_path / "runtime")
    runtime = PersistentVoiceRuntime(
        wakeword=Wake(), core=SimpleNamespace(), realtime_factory=_never, signals=bus,
        auto_turn=True, voice_arch=VoiceArchitecture.CONTINUOUS_BRAIN, active_timeout_s=0,
    )
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    scheduler = SpeechScheduler(core=EmptyCore(), conversation_id=conversation, session=facade,
                                journal=RecordingJournal(), reflex_delay_s=.01)
    scheduler._running = True
    audio = SoundDeviceRealtimeAudio()
    audio._output = Speaker()
    bridge = RealtimeConversationBridge(
        core=BrainCore(), session=facade, conversation_id=conversation, audio=audio,
        continuous=True, auto_turn=True,
        on_addressed=runtime.addressed_activity, on_ambient=runtime.ambient_activity, on_mute=_never_called,
        on_listening=runtime.visual_listening, on_idle=runtime.visual_idle,
        on_thinking=runtime.visual_thinking, on_speaking=runtime.visual_speaking,
        on_response_done=runtime.turn_completed,
        on_brain_pending=runtime.brain_pending,
        on_output_event=scheduler.note_output_event,
        on_reflex=scheduler.request_reflex,
        output_admission=scheduler.output_admission,
    )
    return facade, wire, conversation, events, bus, runtime, scheduler, bridge


async def _never(_context):  # noqa: ANN001
    raise AssertionError("aucune session n'est ouverte par ce test")


def _never_called():
    raise AssertionError("le test ne coupe jamais la voix")


class Colors:
    """Toutes les couleurs publiées sur le bus, dans l'ordre, sans les répétitions.

    On observe le bus lui-même — ce que le Control Center lit — et non un
    champ interne : la preuve porte sur ce que l'utilisateur voit.
    """

    def __init__(self, bus: VisualSignalBus) -> None:
        self.path = bus.root / ".voice_state"
        self.names = palette()
        self.seen: list[str] = []
        published = bus.state

        def record(value: str) -> None:
            published(value)
            color = self.names[value]
            if not self.seen or self.seen[-1] != color:
                self.seen.append(color)

        bus.state = record

    @property
    def now(self) -> str:
        return self.names[self.path.read_text(encoding="utf-8").strip()]


async def pump(bridge, events, counter) -> None:
    """Passer au bridge tout ce que le frontend a normalisé, dans l'ordre reçu."""

    while True:
        try:
            envelope = await asyncio.wait_for(events.get(), .2)
        except asyncio.TimeoutError:
            return
        if envelope.message_type == "realtime.audio":
            counter[0] += 1
            await bridge._play_audio(counter[0], envelope)
        else:
            await bridge._handle_event(envelope)


def provider_response(wire, output_id: str, *, response_id: str, text: str) -> None:
    """Rejouer une réponse du fournisseur : ouverture, un bloc audio, transcription, fin."""

    wire.push(type="response.created", response={"id": response_id, "metadata": {OUTPUT_ID_METADATA_KEY: output_id}})
    wire.push(type="response.output_audio.delta", response_id=response_id, item_id=f"item-{response_id}",
              delta=base64.b64encode(bytes(960)).decode())
    wire.push(type="response.output_audio_transcript.done", response_id=response_id,
              item_id=f"item-{response_id}", transcript=text)
    wire.push(type="response.done", response={"id": response_id, "status": "completed"})


async def test_the_orb_returns_to_thinking_between_the_preamble_and_the_answer(pipeline, tmp_path):
    facade, wire, conversation, events, bus, runtime, scheduler, bridge = await rig(pipeline, tmp_path)
    colors, counter = Colors(bus), [0]
    try:
        for turn in range(2):
            # 1. L'utilisateur parle : le tour part au cerveau.
            wire.push(type="conversation.item.input_audio_transcription.completed",
                      transcript="Jarvis, compare les prix des deux architectures.", item_id=f"item-u{turn}")
            await pump(bridge, events, counter)
            assert colors.now == "violet"  # le cerveau réfléchit

            # 2. Le cerveau tarde : le cerveau réflexe dit une phrase d'attente.
            now = asyncio.get_running_loop().time()
            scheduler._reflex.due, scheduler._reflex.expires = now - .001, now + 5
            await scheduler._maybe_speak_reflex()
            preamble = scheduler._live_reflex.output_id
            provider_response(wire, preamble, response_id=f"preamble-{turn}", text="Je regarde ça.")
            await pump(bridge, events, counter)

            # 3. Le préambule s'est tu, le cerveau n'a toujours pas répondu.
            assert bridge._brain_pending is True
            assert colors.now == "violet"

            # 4. Le cerveau rend sa réponse et la dit au compte-gouttes.
            answer = SpeechRequest(conversation_id=conversation, text="Les deux tiennent dans le budget.",
                                   kind=SpeechKind.RESULT, priority=SpeechPriority.HIGH,
                                   correlation_id=f"c{turn}", source=source(f"c{turn}"))
            output_id = await facade.speak(answer)
            provider_response(wire, output_id, response_id=f"answer-{turn}", text=answer.text)
            await pump(bridge, events, counter)
            assert bridge._brain_pending is False
            assert colors.now == "écoute"

        # 5. Plus personne ne réfléchit : la veille reste la veille.
        await runtime.visual_idle()
        assert colors.now == "veille"

        assert colors.seen == [
            "violet", "orange", "violet", "orange", "écoute",  # premier tour
            "violet", "orange", "violet", "orange", "écoute",  # second tour
            "veille",
        ]
    finally:
        await scheduler.stop()
