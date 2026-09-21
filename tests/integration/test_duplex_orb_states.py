"""La couleur de l'orbe en mode GPT-Live (duplex), au bus que le Control Center lit.

Vraie façade duplex (`LiveFrontendSession`), vrai bridge de périphérique, vrai
runtime vocal, vrai `VisualSignalBus` écrit sur disque. Seul le fil du
fournisseur est joué à la main, avec les évènements canoniques que GPT-Live
émet réellement (transcription d'entrée mot à mot, délégation, blocs audio) —
et surtout SANS les évènements qu'il n'émet jamais : pas de `response.done`,
pas d'`audio_done`, pas de transcription finale, pas d'`input_committed`.

Ce que le test fixe est ce que l'utilisateur voit : l'orbe part de la veille,
passe au violet quand le cerveau se met au travail, à l'orange quand JARVIS
parle, et redescend quand le périphérique s'est tu. En duplex, la fin de
parole ne peut venir que de la quiescence locale : le fil Live n'annonce
jamais la fin d'une sortie.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import re
from types import SimpleNamespace

from jarvis.domain.v2 import VoiceLifecycleState
from jarvis.domain.voice_architecture import (
    DuplexVoiceConfig, VoiceArchitectureId, VoiceModelRef,
)
from jarvis.domain.voice_events import (
    AssistantAudioChunk, UserTranscriptDelta, VoiceDelegationRequested,
)
from jarvis.domain.voice_frontend import (
    VoiceAudioChunk, VoiceCorrelation, VoiceFrontendConfig, VoiceOperation,
)
from jarvis.runtime.live_frontend_session import LiveFrontendSession
from jarvis.runtime.realtime_audio import RealtimeConversationBridge, SoundDeviceRealtimeAudio
from jarvis.runtime.visual_signals import VisualSignalBus
from jarvis.runtime.voice_v2 import PersistentVoiceRuntime
from tests.fakes.voice_frontend import FakeVoiceFrontend


#: Palette réelle de l'orbe, lue dans le rendu du Control Center : le test
#: parle de couleurs, pas de noms d'états internes.
ORB = Path(__file__).resolve().parents[2] / "jarvis" / "runtime" / "control_center_work.js"


def palette() -> dict[str, str]:
    text = ORB.read_text(encoding="utf-8")
    colors = dict(re.findall(r"(idle|listening|speaking|thinking):\[(\d+,\d+,\d+)\]", text))
    assert colors["idle"] == "67,170,255", "l'orbe au repos n'est plus bleue"
    assert colors["thinking"] == "175,88,255", "la réflexion n'est plus violette"
    assert colors["speaking"] == "255,151,61"
    return {"thinking": "violet", "speaking": "orange",
            "listening": "écoute", "idle": "veille"}


class Wake:
    async def suspend_for_active_session(self) -> None: ...
    async def resume(self) -> None: ...
    async def close(self) -> None: ...


class Speaker:
    """Périphérique de test : il accepte les octets, et sait se taire.

    `stop()` est ce que le vrai `confirm_live_output_quiescence` appelle pour
    constater que le haut-parleur a fini de jouer. C'est la seule preuve de
    fin de parole disponible sur le fil Live.
    """

    latency = 0

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.stops = 0

    def write(self, block) -> None:  # noqa: ANN001
        self.writes.append(block)

    def stop(self, ignore_errors: bool = True) -> None:
        self.stops += 1


class BrainCore:
    def __init__(self) -> None:
        self.turns: list[str] = []

    async def submit_brain_turn(self, conversation_id, *, content, correlation_id, source="realtime",  # noqa: ANN001
                                addressing="addressed", provider_item_id=None, interrupted_speech_id=None):
        self.turns.append(content)
        return {"turn_id": f"turn-{len(self.turns)}", "revision": len(self.turns), "duplicate": False}

    async def append_turn(self, *args, **kwargs):  # noqa: ANN002,ANN003
        return {"id": "turn"}


class Colors:
    """Toutes les couleurs publiées sur le bus, dans l'ordre, sans les répétitions.

    On observe le fichier `.voice_state` lui-même — ce que le Control Center
    lit — et non un champ interne.
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


async def _never(_context):  # noqa: ANN001
    raise AssertionError("aucune session n'est ouverte par ce test")


def _never_called():
    raise AssertionError("le test ne coupe jamais la voix")


async def rig(bus_root):  # noqa: ANN001
    """Monter la vraie chaîne duplex : fournisseur → façade Live → bridge → bus.

    `bus_root` est le répertoire du bus de signaux. Les tests lui donnent un
    tmp_path ; le banc de mesure pixel lui donne le bus que lit un vrai
    serveur ai-visualizer, ce qui prolonge la même chaîne jusqu'aux pixels.
    """

    frontend = FakeVoiceFrontend()
    await frontend.start(
        VoiceFrontendConfig(DuplexVoiceConfig(VoiceModelRef("openai", "gpt-live-1"))),
        operation=VoiceOperation("start", VoiceCorrelation("live-session")),
    )
    session = LiveFrontendSession(frontend, "live-session")

    bus = VisualSignalBus(bus_root)
    runtime = PersistentVoiceRuntime(
        wakeword=Wake(), core=SimpleNamespace(), realtime_factory=_never, signals=bus,
        auto_turn=True, active_timeout_s=0,
        conversation_architecture=VoiceArchitectureId.DUPLEX,
    )
    runtime.runtime.state = VoiceLifecycleState.ACTIVE
    runtime._session = session

    audio = SoundDeviceRealtimeAudio()
    audio._output = Speaker()
    bridge = RealtimeConversationBridge(
        core=BrainCore(), session=session, conversation_id="conversation", audio=audio,
        continuous=True, auto_turn=True,
        on_addressed=runtime.addressed_activity, on_ambient=runtime.ambient_activity,
        on_mute=_never_called,
        on_listening=runtime.visual_listening, on_idle=runtime.visual_idle,
        on_thinking=runtime.visual_thinking, on_speaking=runtime.visual_speaking,
        on_response_done=runtime.turn_completed,
        on_brain_pending=runtime.brain_pending,
    )
    return frontend, session, bus, runtime, bridge


async def pump(session, bridge, counter, *, budget_s: float = .5) -> None:
    """Passer au bridge tout ce que la façade duplex a traduit, dans l'ordre."""

    deadline = asyncio.get_running_loop().time() + budget_s
    events = session._legacy_pending  # rempli par drain(), ci-dessous
    while events:
        envelope = events.pop(0)
        if envelope.message_type == "realtime.audio":
            counter[0] += 1
            await bridge._play_audio(counter[0], envelope)
        else:
            await bridge._handle_event(envelope)
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("le pompage du fil duplex ne se termine pas")


def drain(session, frontend) -> None:
    """Traduire en legacy tout ce que le fournisseur a mis dans la file.

    On traverse le vrai `_observe` + `_legacy_events` de la façade duplex :
    c'est précisément la couche qui décide quels faits du fil GPT-Live
    parviennent au bridge, donc à la couleur de l'orbe.
    """

    pending = []
    while frontend._queue:
        event = frontend._queue.popleft()
        session._observe(event)
        pending.extend(session._legacy_events(event))
    session._legacy_pending = pending


def word(frontend, text: str, sequence: int):
    """Un delta de transcription d'entrée : GPT-Live en émet un PAR MOT."""

    return frontend.event(
        UserTranscriptDelta("input-transcript", text, sequence),
        correlation=VoiceCorrelation("live-session"),
    )


def audio_chunk(frontend, output_id: str):
    return frontend.event(
        AssistantAudioChunk(VoiceAudioChunk(bytes(960))),
        correlation=VoiceCorrelation("live-session", output_id=output_id),
    )


async def test_the_orb_turns_violet_when_the_duplex_brain_starts_working(tmp_path):
    """Le fournisseur délègue un vrai travail : l'écran doit passer au violet.

    C'est le seul signal de finalité du fil Live. Sans lui l'orbe n'a aucun
    moyen d'annoncer que JARVIS réfléchit.
    """

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    colors, counter = Colors(bus), [0]

    for index, text in enumerate([" Jarvis", ", compare", " les", " prix"], start=1):
        frontend.inject(word(frontend, text, index))
    frontend.inject(frontend.event(
        VoiceDelegationRequested(1), correlation=VoiceCorrelation("live-session")))
    drain(session, frontend)
    await pump(session, bridge, counter)

    assert colors.now == "violet", (
        "en duplex l'orbe ne passe jamais au violet : la délégation du "
        "fournisseur n'est traduite par aucun évènement de surface"
    )


async def test_the_orb_leaves_speaking_when_the_duplex_device_falls_silent(tmp_path):
    """Le fil Live n'annonce jamais la fin d'une sortie : seule la quiescence
    locale peut rendre l'écran. Sans elle l'orbe reste bloquée sur orange."""

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    colors = Colors(bus)

    for _ in range(3):
        frontend.inject(audio_chunk(frontend, "output-1"))
    drain(session, frontend)

    # Vraie tâche de lecture du bridge : c'est elle qui, sur le fil Live,
    # constate la quiescence locale faute d'évènement de fin du fournisseur.
    bridge._inbox, bridge._playout = asyncio.Queue(), asyncio.Queue()
    player = asyncio.create_task(bridge._play_out())
    try:
        for envelope in session._legacy_pending:
            if envelope.message_type == "realtime.audio":
                bridge._dispatch(envelope)
        async with asyncio.timeout(3):
            while colors.now != "orange":
                await asyncio.sleep(.01)
        assert colors.now == "orange", "JARVIS parle : l'orbe doit être orange"

        # Le périphérique confirme qu'il s'est tu. Aucun évènement fournisseur
        # ne suivra : sur le fil Live, il n'en vient jamais.
        async with asyncio.timeout(3):
            while not bridge._live_output_quiescent:
                await asyncio.sleep(.01)
        await asyncio.sleep(.05)
    finally:
        player.cancel()

    assert colors.now != "orange", (
        "l'orbe reste bloquée sur « JARVIS parle » : rien ne la rend au repos "
        "quand le périphérique s'est tu"
    )
    assert colors.seen[-1] in {"violet", "écoute", "veille"}


async def test_the_duplex_orb_alternates_over_several_turns(tmp_path):
    """Deux tours de suite, sans rester coincée sur une couleur.

    Le défaut historique de l'orbe est la latche : une couleur gagne et ne
    rend plus la main. Un seul aller-retour ne le prouve pas ; deux, si.
    On lit la suite publiée sur le bus, pas son instantané : une couleur brève
    reste une couleur vue.
    """

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    colors = Colors(bus)
    bridge._inbox, bridge._playout = asyncio.Queue(), asyncio.Queue()
    player = asyncio.create_task(bridge._play_out())
    try:
        for turn in range(2):
            # L'utilisateur demande un vrai travail : le cerveau s'y met.
            frontend.inject(frontend.event(
                VoiceDelegationRequested(turn + 1),
                correlation=VoiceCorrelation("live-session")))
            drain(session, frontend)
            for envelope in session._legacy_pending:
                await bridge._handle_event(envelope)
            assert colors.now == "violet", f"tour {turn}: pas de réflexion"

            # Le cerveau rend sa réponse, portée par une demande de parole.
            bridge._live_output_quiescent = False
            for _ in range(2):
                frontend.inject(frontend.event(
                    AssistantAudioChunk(VoiceAudioChunk(bytes(960))),
                    correlation=VoiceCorrelation(
                        "live-session", output_id=f"output-{turn}",
                        speech_id=f"speech-{turn}")))
            drain(session, frontend)
            for envelope in session._legacy_pending:
                if envelope.message_type == "realtime.audio":
                    bridge._dispatch(envelope)
                else:
                    await bridge._handle_event(envelope)

            # Le périphérique se tait : l'écran redescend, prêt pour la suite.
            async with asyncio.timeout(3):
                while not bridge._live_output_quiescent:
                    await asyncio.sleep(.01)
            assert colors.now == "écoute", f"tour {turn}: l'orbe reste sur la parole"
    finally:
        player.cancel()

    # `Colors` est posé après le montage : la veille initiale du constructeur
    # précède l'observation, la suite commence donc au premier tour.
    assert colors.seen == [
        "violet", "orange", "écoute",
        "violet", "orange", "écoute",
    ], colors.seen
