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
import math
from pathlib import Path
import re
import struct
from types import SimpleNamespace

from jarvis.domain.v2 import ProtocolEnvelope, VoiceLifecycleState
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
from jarvis.runtime.speech_scheduler import SpeechScheduler
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
        self.starts = 0

    def write(self, block) -> None:  # noqa: ANN001
        self.writes.append(block)

    def stop(self, ignore_errors: bool = True) -> None:
        self.stops += 1

    def start(self) -> None:
        """Après un drain, la parole suivante relance le flux (comme PortAudio)."""

        self.starts += 1


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


#: 20 ms de voix (crête franche). Des zéros ne sont PAS de la parole : c'est
#: le silence que GPT-Live diffuse en continu (voir plus bas).
VOICE_PCM = b"".join(struct.pack("<h", int(3000 * math.sin(i / 8))) for i in range(480))


def audio_chunk(frontend, output_id: str):
    return frontend.event(
        AssistantAudioChunk(VoiceAudioChunk(VOICE_PCM)),
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
        # On lit la suite publiée, pas l'instantané : la lecture est assez
        # rapide pour que l'orange soit déjà passé quand on regarde.
        async with asyncio.timeout(3):
            while "orange" not in colors.seen:
                await asyncio.sleep(.01)

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
                    AssistantAudioChunk(VoiceAudioChunk(VOICE_PCM)),
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


# -- Ce que GPT-Live envoie vraiment (sonde du 21/09/2026) ---------------------
#
# Mesuré sur le vrai fournisseur (`gpt-live-1`, session séparée, sans
# périphérique) : un bloc audio de 100 ms toutes les 100 ms, du début à la fin
# de la session, que JARVIS parle ou non. Quand il se tait, chaque bloc est fait
# de zéros exacts (crête 0) ; les fins de fondu ont une crête de 1 à 8 ; les
# pauses à l'intérieur d'une phrase gardent une crête de 34 ou plus. Les blocs
# ci-dessous reproduisent ces deux formes-là, rien d'autre.


def spoken_chunk(frontend, output_id: str):
    """100 ms de voix : une crête franche, comme une syllabe prononcée."""

    pcm = b"".join(struct.pack("<h", int(3000 * math.sin(i / 8))) for i in range(2400))
    return frontend.event(
        AssistantAudioChunk(VoiceAudioChunk(pcm)),
        correlation=VoiceCorrelation("live-session", output_id=output_id),
    )


def silent_chunk(frontend, output_id: str):
    """100 ms du silence que GPT-Live diffuse entre deux paroles : des zéros."""

    return frontend.event(
        AssistantAudioChunk(VoiceAudioChunk(bytes(4800))),
        correlation=VoiceCorrelation("live-session", output_id=output_id),
    )


async def feed(session, frontend, bridge) -> None:
    """Traduire et remettre au bridge ce que le fournisseur a émis, dans l'ordre.

    L'audio passe par `_dispatch` (la vraie file de lecture), le reste par le
    traitement d'évènements : exactement le partage du lecteur de production.
    """

    drain(session, frontend)
    for envelope in session._legacy_pending:
        if envelope.message_type == "realtime.audio":
            bridge._dispatch(envelope)
        else:
            await bridge._handle_event(envelope)


async def settle(bridge) -> None:
    """Attendre que tout l'audio remis ait été joué, puis un tour de boucle."""

    async with asyncio.timeout(3):
        while bridge._queued_audio or not bridge._playout.empty():
            await asyncio.sleep(.01)
    await asyncio.sleep(.05)


def brain_event(kind: str, work_id: str, correlation: str = "live:conversation:d1") -> ProtocolEnvelope:
    return ProtocolEnvelope(message_type=f"brain.work.{kind}", payload={
        "conversation_id": "conversation", "correlation_id": correlation, "work_id": work_id,
    })


def scheduler_for(session, runtime) -> SpeechScheduler:
    """Le vrai ordonnanceur de parole, branché sur le runtime comme en production."""

    scheduler = SpeechScheduler(core=SimpleNamespace(), conversation_id="conversation", session=session)
    # Le fil que ce correctif ajoute ; absent, l'ordonnanceur l'ignore.
    scheduler.on_brain_busy = getattr(runtime, "brain_work", None)
    runtime._speech = scheduler
    return scheduler


async def test_the_orb_stays_green_while_gpt_live_streams_silence(tmp_path):
    """L'utilisateur parle, JARVIS se tait : l'orbe est verte, pas orange.

    GPT-Live continue d'envoyer des blocs de silence pendant qu'il écoute.
    Tant qu'un bloc audio suffisait à allumer « JARVIS parle », l'orbe restait
    orange du réveil à la fin de la session.
    """

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    colors = Colors(bus)
    bridge._inbox, bridge._playout = asyncio.Queue(), asyncio.Queue()
    player = asyncio.create_task(bridge._play_out())
    try:
        # JARVIS dit bonjour, puis se tait.
        for _ in range(3):
            frontend.inject(spoken_chunk(frontend, "output-1"))
        await feed(session, frontend, bridge)
        await settle(bridge)
        assert colors.now == "écoute", "après sa phrase, JARVIS écoute"
        spoken_until = len(colors.seen)

        # Il écoute l'utilisateur : le fournisseur n'envoie que du silence,
        # entrecoupé de la transcription de ce que dit l'utilisateur.
        for index in range(12):
            frontend.inject(silent_chunk(frontend, "output-1"))
            if index % 4 == 0:
                frontend.inject(word(frontend, " archive", index + 1))
                frontend.inject(silent_chunk(frontend, "output-2"))
        await feed(session, frontend, bridge)
        await settle(bridge)
    finally:
        player.cancel()

    assert "orange" not in colors.seen[spoken_until:], (
        "l'orbe repasse à l'orange pendant que JARVIS écoute : le silence que "
        f"GPT-Live diffuse est pris pour de la parole ({colors.seen})"
    )
    assert colors.now == "écoute"


async def test_the_orb_is_violet_while_jarvis_acts_and_green_once_done(tmp_path):
    """Le tour complet, dans les couleurs que l'utilisateur attend.

    Il demande une action : violet pendant que le cerveau travaille, orange
    quand JARVIS parle (accusé de réception puis résultat), violet entre les
    deux, et vert une fois tout dit. Aucune sortie de GPT-Live ne porte de
    `speech_id` : c'est la fin du travail du cerveau, pas la bouche, qui dit
    qu'il a fini.
    """

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    scheduler = scheduler_for(session, runtime)
    colors = Colors(bus)
    bridge._inbox, bridge._playout = asyncio.Queue(), asyncio.Queue()
    player = asyncio.create_task(bridge._play_out())
    try:
        frontend.inject(frontend.event(
            VoiceDelegationRequested(1), correlation=VoiceCorrelation("live-session")))
        await feed(session, frontend, bridge)
        await scheduler.handle_core_event(brain_event("started", "work-1"))
        assert colors.now == "violet", "JARVIS agit : l'orbe doit être violette"

        # Accusé de réception de GPT-Live, puis retour au silence.
        for _ in range(3):
            frontend.inject(spoken_chunk(frontend, "ack"))
        for _ in range(3):
            frontend.inject(silent_chunk(frontend, "ack"))
        await feed(session, frontend, bridge)
        await settle(bridge)
        assert colors.now == "violet", "l'accusé dit, le cerveau travaille encore : violet"

        # Le cerveau a fini ; GPT-Live dit le résultat, puis se tait.
        await scheduler.handle_core_event(brain_event("completed", "work-1"))
        for _ in range(4):
            frontend.inject(spoken_chunk(frontend, "result"))
        for _ in range(5):
            frontend.inject(silent_chunk(frontend, "result"))
        await feed(session, frontend, bridge)
        await settle(bridge)
    finally:
        player.cancel()

    assert colors.now == "écoute", (
        f"le travail est fini et tout est dit, l'orbe doit repasser au vert ({colors.seen})"
    )
    assert colors.seen[-2:] == ["orange", "écoute"], colors.seen
    assert colors.seen[:3] == ["violet", "orange", "violet"], colors.seen


async def test_a_silent_brain_completion_brings_the_orb_back_to_green(tmp_path):
    """Une tâche simple, faite sans rien dire : l'orbe ne reste pas violette.

    Le cerveau peut terminer sans parler (règle « pas d'annonce redondante »).
    Aucune bouche ne s'ouvre alors : seule la fin du travail peut rendre l'écran.
    """

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    scheduler = scheduler_for(session, runtime)
    colors = Colors(bus)

    frontend.inject(frontend.event(
        VoiceDelegationRequested(1), correlation=VoiceCorrelation("live-session")))
    drain(session, frontend)
    for envelope in session._legacy_pending:
        await bridge._handle_event(envelope)
    await scheduler.handle_core_event(brain_event("started", "work-1"))
    assert colors.now == "violet"

    await scheduler.handle_core_event(brain_event("completed", "work-1"))
    assert colors.now == "écoute", (
        "le cerveau a fini sans parler et l'orbe reste violette : rien ne "
        "rend l'écran quand aucune parole ne suit"
    )


async def test_a_room_segment_during_the_work_keeps_the_orb_violet(tmp_path):
    """Un bruit de la pièce pendant que JARVIS agit ne le fait pas passer pour inactif."""

    frontend, session, bus, runtime, bridge = await rig(tmp_path / "runtime")
    scheduler = scheduler_for(session, runtime)
    colors = Colors(bus)

    await scheduler.handle_core_event(brain_event("started", "work-1"))
    await runtime.visual_listening()
    await runtime.visual_idle()
    assert colors.now == "violet", colors.seen
    await scheduler.handle_core_event(brain_event("failed", "work-1"))
    assert colors.now == "veille", "la dernière demande était la veille : elle revient"
