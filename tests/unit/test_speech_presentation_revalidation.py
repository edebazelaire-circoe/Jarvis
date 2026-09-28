"""Vérité ≠ formulation : ce qui a été rédigé pour un tour passé attend le cerveau.

Tests ROUGES de la Slice 01 (tâche `jarvis-voice-stale-speech-presentation`).
Chaque test nomme, dans son `xfail`, la Slice qui doit le faire passer.

Invariant (README de la tâche, décision du 28/09/2026) : un résultat peut rester
vrai indéfiniment sans que la phrase préparée pour l'annoncer reste prononçable
indéfiniment. Dès qu'une nouvelle intention s'impose, une formulation non
commencée d'une intention passée n'est plus prononçable d'elle-même ; le cerveau
la reçoit et décide de la redire (réémission) ou non.

Défauts visés, vérifiés à `202333d` (READINESS B1) :

- `_eligibility` reporte (`carried_over`) toute parole durable d'une intention
  passée, et `ordering_key = (-priority, created_at)` la sert AVANT la réponse
  fraîche à priorité égale — le « tour de retard » (T3, T4, T5 → Slice 04) ;
- `announce_notice` crée des RESULT/NORMAL sans TTL ni `supersedes_key`, y
  compris l'accusé de calibration (T6 → Slice 03) ;
- `note_interruption` ne gèle rien : la file repart dès que l'utilisateur se
  tait, avant toute décision d'adressage (T7 → Slice 05).

Montage : Core réel en mémoire (`BrainOrchestrator`, `CoreEventBus`, SQLite dans
`tmp_path`) relié à l'ordonnanceur de production par un client Core en
processus ; cerveau scripté ; surface classique de test (`FakeVoiceSession`),
qui annonce ses fins de sortie — la fin de parole Live est l'affaire de
`test_speech_scheduler_live_completion.py`. Pas de réseau. Les attentes sont
des conditions bornées ; T7 tourne en temps virtuel pour constater une absence.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import BrainOrchestrator
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    SpeechKind,
    SpeechRequest,
    utc_now,
)
from jarvis.runtime.barehands_calibration import CALIBRATION_ANALYSIS_ACK
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.speech_context import source
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION,
    FakeClock,
    FakeCore,
    FakeVoiceSession,
    RecordingJournal,
    build_scheduler,
    busy_surface,
    finish_speech,
    release_surface,
)

TIMEOUT_S = 5.0
SPEECH_DECIDED = "voice.speech.presentation_decided"
#: Statuts qui soldent une présentation sans qu'elle soit dite.
RETIRED = {"superseded", "expired"}


# --------------------------------------------------------------------------- montage


@dataclass
class ScriptedBrain:
    """Cerveau dont chaque tour dit ce qu'on lui dicte, puis réussit.

    `replies[texte du tour]` : les paroles à émettre, `(texte, genre)`. Un tour
    absent du script réussit sans rien dire — c'est le « tour terminé sans
    réémission » de T4.
    """

    replies: dict[str, list[tuple[str, SpeechKind]]] = field(default_factory=dict)
    contexts: list = field(default_factory=list)

    async def run_turn_with_context(self, turn: BrainTurnInput, context, emit) -> BrainTurnResult:
        self.contexts.append(context)
        return await self.run_turn(turn, context.state, emit)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        del state
        work_id = f"brain-turn:{turn.correlation_id}"
        said = self.replies.get(turn.text, [])
        for text, kind in said:
            await emit.emit(BrainEvent(
                kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id, work_id=work_id,
                speech=SpeechRequest(conversation_id=turn.conversation_id, text=text, kind=kind, work_id=work_id)))
        return BrainTurnResult(correlation_id=turn.correlation_id,
                               public_summary=" ".join(text for text, _ in said))


class NullSink:
    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        del kind, message, level, data


class InProcessCore:
    """Le client Core que voit l'ordonnanceur, branché sur un Core en mémoire.

    Même rôle que `LocalCoreClient` sans HTTP : `/v1/events` est un abonnement
    au `CoreEventBus`, `speech-context` une lecture directe.
    """

    def __init__(self, brain: BrainOrchestrator, bus: CoreEventBus) -> None:
        self.brain, self.bus = brain, bus

    async def events(self, *, on_connected=None):  # noqa: ANN001
        queue = self.bus.subscribe()
        if on_connected is not None:
            on_connected()
        while True:
            yield await queue.get()

    async def speech_context(self, conversation_id: str):
        return await self.brain.speech_context(conversation_id)

    async def append_turn(self, conversation_id: str, **kwargs):  # noqa: ANN003
        del conversation_id, kwargs
        return {"id": "turn"}

    async def cancel_brain_turn(self, conversation_id: str, *, correlation_id: str):
        return await self.brain.cancel_turn(conversation_id, correlation_id)


@dataclass
class Stage:
    brain: BrainOrchestrator
    scheduler: SpeechScheduler
    session: FakeVoiceSession
    journal: RecordingJournal
    clock: FakeClock
    conversation_id: str
    state: SQLiteStateRepository
    #: Sortie de surface qui occupe la bouche, tant que le test ne la libère pas.
    surface_output: str | None = None

    async def turn(self, text: str) -> BrainTurnInput:
        turn = BrainTurnInput(conversation_id=self.conversation_id, text=text)
        await self.brain.submit(turn)
        await self.idle()
        return turn

    async def idle(self) -> None:
        async def loop() -> None:
            while self.brain.active_turn_count:
                await asyncio.sleep(0)
        await asyncio.wait_for(loop(), timeout=TIMEOUT_S)

    def queued(self, text: str) -> list[str]:
        """Identifiants des paroles de ce texte que la bouche a reçues."""
        return [str(event["data"]["speech_id"]) for event in self.journal.of("voice.speech.queued")
                if self.text_of(event["data"].get("speech_id")) == text]

    def text_of(self, speech_id) -> str | None:  # noqa: ANN001
        candidate = self.scheduler._candidates.get(speech_id)
        return None if candidate is None else candidate.request.text

    def decisions(self, speech_id: str) -> list[tuple[str, str]]:
        return [(event["data"]["status"], event["data"]["reason"]) for event in self.journal.of(SPEECH_DECIDED)
                if event["data"].get("speech_id") == speech_id]

    def spoken(self) -> list[str]:
        return self.session.texts()

    async def until(self, predicate, *, what: str) -> None:
        async def loop() -> None:
            while not predicate():
                await asyncio.sleep(0.005)
        try:
            await asyncio.wait_for(loop(), timeout=TIMEOUT_S)
        except TimeoutError:
            raise AssertionError(f"jamais constaté : {what} ; dit = {self.spoken()}") from None

    async def speak_until(self, done, *, what: str) -> None:
        """Laisser la bouche dire ce qu'elle choisit, sortie après sortie, jusqu'à `done()`."""
        async def loop() -> None:
            while not done():
                if self.session.active_output_id is not None:
                    await finish_speech(self.scheduler, self.session)
                await asyncio.sleep(0.005)
        try:
            await asyncio.wait_for(loop(), timeout=TIMEOUT_S)
        except TimeoutError:
            raise AssertionError(f"jamais constaté : {what} ; dit = {self.spoken()}") from None


async def stage(tmp_path, brain_script: ScriptedBrain) -> Stage:
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    bus = CoreEventBus()
    brain = BrainOrchestrator(conversations=conversations, events=bus, backend=brain_script, diagnostics=NullSink())
    conversation = await conversations.create()
    session, journal, clock = FakeVoiceSession(), RecordingJournal(), FakeClock()
    scheduler = SpeechScheduler(core=InProcessCore(brain, bus), conversation_id=conversation.id, session=session,
                                journal=journal, clock=clock, reconnect_delay_s=0.0, output_timeout_s=TIMEOUT_S)
    await scheduler.start()
    return Stage(brain, scheduler, session, journal, clock, conversation.id, state)


async def close(scene: Stage) -> None:
    await scene.scheduler.stop()
    await scene.brain.stop()
    await scene.state.close()


# ----------------------------------------------------------- tour de retard (S04)

FIRST_QUESTION = "Quelle heure est-il ?"
OLD_ANSWER = "Il est midi."
SECOND_QUESTION = "Et quel temps fait-il ?"
NEW_ANSWER = "Il fait beau."


async def a_stale_answer_waits_behind_a_busy_mouth(scene: Stage) -> str:
    """A (RESULT, intention N-1) prête et non démarrée, puis nouvelle intention N.

    La bouche est occupée par une sortie de surface : A attend en file, comme
    derrière une phrase Live qui ne rend pas la main. Rend l'id de A.
    """
    scene.surface_output = await busy_surface(scene.scheduler)
    await scene.turn(FIRST_QUESTION)
    await scene.until(lambda: scene.queued(OLD_ANSWER), what="A reçue par la bouche")
    [old] = scene.queued(OLD_ANSWER)
    await scene.turn(SECOND_QUESTION)
    return old


@pytest.mark.xfail(strict=True, reason="S04: the current intent must be served first; today ordering_key "
                                       "(-priority, created_at) serves the carried-over A before B'")
async def test_the_fresh_answer_is_said_before_an_answer_written_for_the_previous_question(tmp_path):
    """T3 — B' (RESULT, intention N) arrive alors que A (RESULT, N-1) attend :
    la bouche sert B' d'abord."""
    scene = await stage(tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)],
                                                 SECOND_QUESTION: [(NEW_ANSWER, SpeechKind.RESULT)]}))
    try:
        await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await scene.until(lambda: scene.queued(NEW_ANSWER), what="B' reçue par la bouche")
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.until(lambda: scene.spoken(), what="une première parole")
        assert scene.spoken()[0] == NEW_ANSWER, (
            f"la bouche a servi {scene.spoken()[0]!r} (rédigée pour la question précédente) "
            f"avant la réponse fraîche {NEW_ANSWER!r}")
    finally:
        await close(scene)


@pytest.mark.xfail(strict=True, reason="S04: a past-intent formulation the brain did not re-emit must be "
                                       "retired as not_revalidated, never spoken")
async def test_an_old_answer_the_brain_does_not_repeat_is_never_said(tmp_path):
    """T4 — même scène ; le cerveau termine son tour sans réémettre A : A n'est
    jamais dite, et sa trace dit pourquoi (`not_revalidated`)."""
    scene = await stage(tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}))
    try:
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.until(lambda: OLD_ANSWER in scene.spoken()
                          or any(status in RETIRED for status, _ in scene.decisions(old)),
                          what="un sort pour A (dite ou retirée)")
        assert OLD_ANSWER not in scene.spoken(), (
            f"A ({OLD_ANSWER!r}) a été dite alors que le cerveau ne l'a pas réémise ; "
            f"décisions de A : {scene.decisions(old)}")
        assert any(reason == "not_revalidated" for status, reason in scene.decisions(old) if status in RETIRED), (
            f"A n'est pas tracée not_revalidated : {scene.decisions(old)}")
    finally:
        await close(scene)


@pytest.mark.xfail(strict=True, reason="S04: a re-emitted answer must be said once, the old formulation "
                                       "retired as revalidated_as the new speech")
async def test_an_old_answer_the_brain_repeats_is_said_exactly_once(tmp_path):
    """T5 — le cerveau réémet A sous l'intention courante (nouvelle parole) : le
    texte est dit une seule fois, et l'ancienne formulation est tracée
    `revalidated_as`.

    Le rattachement de la réémission à l'ancienne parole est un choix de la
    Slice 04 (champ explicite du cerveau ou règle documentée) ; si elle retient
    un champ explicite, c'est le script du cerveau ci-dessous qui le portera.
    """
    scene = await stage(tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)],
                                                 SECOND_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}))
    try:
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await scene.until(lambda: len(scene.queued(OLD_ANSWER)) == 2, what="la réémission reçue par la bouche")
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.speak_until(lambda: scene.spoken().count(OLD_ANSWER) >= 2
                                or (scene.spoken().count(OLD_ANSWER) == 1
                                    and any(status in RETIRED for status, _ in scene.decisions(old))),
                                what="la réémission dite et l'ancienne soldée")
        assert scene.spoken().count(OLD_ANSWER) == 1, (
            f"{OLD_ANSWER!r} a été dite {scene.spoken().count(OLD_ANSWER)} fois ; décisions de l'ancienne : "
            f"{scene.decisions(old)}")
        assert any(reason == "revalidated_as" for status, reason in scene.decisions(old) if status in RETIRED), (
            f"l'ancienne formulation n'est pas tracée revalidated_as : {scene.decisions(old)}")
    finally:
        await close(scene)


# ------------------------------------------------------- relais spontanés (S03)

CALIBRATION_START = "Je lance la calibration."
CALIBRATION_ANALYSIS = "Ton geste C est net ; l'ouverture de la paume reste trop faible."
CALIBRATION_KEY = "calibration:event-1"
#: TTL que le test déclare pour l'accusé ; bien en deçà de l'attente simulée.
ACK_TTL_S = 20.0


async def announce(brain: BrainOrchestrator, text: str, **declared) -> bool:
    """Faire passer un relais par `announce_notice`, avec ce que son genre déclare.

    Le contrat typé (`docs/02-architecture.md` de la tâche) est
    `announce_notice(text, *, kind, supersedes_key, ttl_s, work_id)` ; il n'existe
    pas encore. Les champs déclarés ne sont passés que si la signature les
    accepte : aujourd'hui l'appel reste l'appel actuel, et le test échoue sur ce
    que la bouche DIT, pas sur une signature.
    """
    accepted = inspect.signature(brain.announce_notice).parameters
    return await brain.announce_notice(text, **{name: value for name, value in declared.items() if name in accepted})


async def calibration_scene(tmp_path) -> Stage:
    scene = await stage(tmp_path, ScriptedBrain())
    # Un tour silencieux installe l'intention courante que les relais empruntent.
    await scene.turn(CALIBRATION_START)
    scene.surface_output = await busy_surface(scene.scheduler)
    return scene


@pytest.mark.xfail(strict=True, reason="S03: the calibration ACK must be typed ACK with a supersedes_key "
                                       "shared with its analysis; today both are eternal RESULT/NORMAL")
async def test_the_calibration_acknowledgement_is_never_said_once_its_analysis_is_ready(tmp_path):
    """T6a — accusé puis analyse du même évènement, bouche occupée : quand la
    bouche se libère, l'analyse est dite et l'accusé ne l'est jamais."""
    scene = await calibration_scene(tmp_path)
    try:
        assert await announce(scene.brain, CALIBRATION_ANALYSIS_ACK, kind=SpeechKind.ACK,
                              supersedes_key=CALIBRATION_KEY, ttl_s=ACK_TTL_S)
        assert await announce(scene.brain, CALIBRATION_ANALYSIS, kind=SpeechKind.RESULT,
                              supersedes_key=CALIBRATION_KEY)
        await scene.until(lambda: scene.queued(CALIBRATION_ANALYSIS), what="l'analyse reçue par la bouche")
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.speak_until(lambda: CALIBRATION_ANALYSIS in scene.spoken(), what="l'analyse dite")
        assert CALIBRATION_ANALYSIS_ACK not in scene.spoken(), (
            f"l'accusé {CALIBRATION_ANALYSIS_ACK!r} a été dit alors que l'analyse était prête : {scene.spoken()}")
    finally:
        await close(scene)


@pytest.mark.xfail(strict=True, reason="S03: an unsaid calibration ACK must expire (TTL); today it has none "
                                       "and is said whenever the mouth frees up")
async def test_an_unsaid_calibration_acknowledgement_expires_instead_of_being_said_late(tmp_path):
    """T6b — l'accusé attend derrière une bouche occupée au-delà de sa durée de
    vie : il expire, tracé, et n'est jamais dit."""
    scene = await calibration_scene(tmp_path)
    try:
        assert await announce(scene.brain, CALIBRATION_ANALYSIS_ACK, kind=SpeechKind.ACK,
                              supersedes_key=CALIBRATION_KEY, ttl_s=ACK_TTL_S)
        await scene.until(lambda: scene.queued(CALIBRATION_ANALYSIS_ACK), what="l'accusé reçu par la bouche")
        [ack] = scene.queued(CALIBRATION_ANALYSIS_ACK)
        # Au-delà de toute durée de vie d'un transitoire (Core 45 s, repli 60 s).
        scene.clock.advance(120.0)
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.until(lambda: CALIBRATION_ANALYSIS_ACK in scene.spoken()
                          or any(status in RETIRED for status, _ in scene.decisions(ack)),
                          what="un sort pour l'accusé (dit ou retiré)")
        assert CALIBRATION_ANALYSIS_ACK not in scene.spoken(), (
            f"l'accusé a été dit 120 s après son émission ; décisions : {scene.decisions(ack)}")
        assert ("expired", "ttl") in scene.decisions(ack), f"l'accusé n'a pas expiré : {scene.decisions(ack)}"
    finally:
        await close(scene)


# ------------------------------------------------------- interruption unifiée (S05)

#: Au plus ce délai sépare la fin de la phrase de l'utilisateur de la décision
#: d'adressage de son tour (transcription finale + classement). La file ne
#: redémarre pas d'elle-même avant.
ADDRESSING_WINDOW_S = 2.0


@pytest.mark.xfail(strict=True, reason="S05: a barge-in while speaking must freeze the queue until the new "
                                       "turn's addressing decision; today note_interruption purges nothing")
def test_a_queued_answer_waits_for_the_addressing_decision_after_a_barge_in():
    """T7 — l'utilisateur coupe Jarvis pendant une phrase, A attend en file : A ne
    démarre pas avant la décision d'adressage du nouveau tour. Ici aucune
    décision n'arrive dans la fenêtre : A ne doit pas avoir démarré."""

    async def scenario():
        loop = asyncio.get_running_loop()
        session, journal = FakeVoiceSession(), RecordingJournal()
        scheduler = build_scheduler(FakeCore(), session, journal=journal,
                                    clock=VirtualWallClock(loop, utc_now()), output_timeout_s=None)
        await scheduler.start()
        try:
            playing = SpeechRequest(CONVERSATION, "Voici une longue réponse…", kind=SpeechKind.RESULT,
                                    correlation_id="corr-1", source=source("corr-1"))
            queued = SpeechRequest(CONVERSATION, "Et une seconde chose.", kind=SpeechKind.RESULT,
                                   correlation_id="corr-1", source=source("corr-1"))
            scheduler._enqueue(playing)
            scheduler._enqueue(queued)
            while len(session.spoken) < 1:
                await asyncio.sleep(0.01)
            # La séquence du bridge (`_barge_in`) : l'utilisateur parle, la
            # lecture est coupée, la sortie se clôt annulée, puis il se tait.
            scheduler.note_user_speech(True)
            scheduler.note_interruption(None)
            await finish_speech(scheduler, session, status="cancelled")
            await asyncio.sleep(0.8)
            scheduler.note_user_speech(False)
            await asyncio.sleep(ADDRESSING_WINDOW_S)
            return session.texts()
        finally:
            await scheduler.stop()

    spoken = run_virtual(scenario())
    assert spoken == ["Voici une longue réponse…"], (
        f"après le barge-in, la file est repartie sans attendre la décision d'adressage : dit = {spoken}")
