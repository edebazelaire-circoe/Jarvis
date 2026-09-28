"""Vérité ≠ formulation : ce qui a été rédigé pour un tour passé attend le cerveau.

Tests ROUGES de la Slice 01 (tâche `jarvis-voice-stale-speech-presentation`),
reprise QA comprise. Chaque test nomme, dans son `xfail`, la Slice qui doit le
faire passer.

Invariant (README de la tâche, décision du 28/09/2026) : un résultat peut rester
vrai indéfiniment sans que la phrase préparée pour l'annoncer reste prononçable
indéfiniment. Dès qu'une nouvelle intention s'impose, une formulation non
commencée d'une intention passée n'est plus prononçable d'elle-même : elle est
retenue (`held_for_brain`) et le cerveau la reçoit (`pending_replies`) pour la
redire (réémission) ou non. Un tour du cerveau en échec ne tranche rien : la
formulation reste retenue et passe au tour suivant.

Défauts visés, vérifiés à `202333d` (READINESS B1) :

- `_eligibility` reporte (`carried_over`) toute parole durable d'une intention
  passée, et `ordering_key = (-priority, created_at)` la sert AVANT la réponse
  fraîche à priorité égale — le « tour de retard » (T3, T4, T4b, T5 → Slice 04) ;
- `announce_notice` crée des RESULT/NORMAL sans TTL ni `supersedes_key`, y
  compris l'accusé de calibration (T6a, T6b → Slice 03 ; le chemin réel du
  Control Center est dans `test_spontaneous_notice_typing.py`) ;
- `note_interruption` ne gèle rien : la file repart dès que l'utilisateur se
  tait, avant toute décision d'adressage (T7, T7b, T7c → Slice 05).

Montage : Core réel en mémoire (`BrainOrchestrator`, `CoreEventBus`,
`JobService`, SQLite dans `tmp_path`) relié à l'ordonnanceur de production par un
client Core en processus ; cerveau scripté ; surface classique de test
(`FakeVoiceSession`) qui annonce ses fins de sortie — la fin de parole Live est
l'affaire de `test_speech_scheduler_live_completion*.py`. T7b/T7c passent par le
vrai bridge (`RealtimeConversationBridge._consume`) sur `FakeRealtimeSession`.

Tout tourne en temps virtuel (`run_virtual`) : les attentes bornées sont des
secondes simulées, et « rien n'a démarré pendant 2 s » est un constat
déterministe. Pas de réseau.

Les noms de statut que la Slice 04 choisira ne sont pas connus : les tests
reconnaissent une parole retirée par sa **raison** (`not_revalidated`,
`revalidated_as`) sur un statut terminal non dit, et une parole dite par la
surface ou par une décision `started`.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED, BrainOrchestrator
from jarvis.core.v2_services import ConversationService, CoreEventBus, JobService
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    Job,
    JobStatus,
    SpeechKind,
    SpeechRequest,
    utc_now,
)
from jarvis.runtime.barehands_calibration import CALIBRATION_ANALYSIS_ACK
from jarvis.runtime.realtime_audio import RealtimeConversationBridge
from jarvis.runtime.speech_scheduler import SpeechScheduler
from jarvis.testlab.virtual.harness import FakeAudio, FakeRealtimeSession
from tests.fakes.speech_context import source
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION,
    FakeCore,
    FakeVoiceSession,
    RecordingJournal,
    build_scheduler,
    busy_surface,
    finish_speech,
    release_surface,
)

#: Borne (virtuelle) de chaque attente conditionnelle.
TIMEOUT_S = 5.0
SPEECH_DECIDED = "voice.speech.presentation_decided"
#: Statuts d'une parole dite ou en train de l'être.
SPOKEN_STATUSES = {"started", "completed", "interrupted"}
#: Statuts d'une parole encore vivante (ni dite, ni retirée). `held_for_brain`
#: y figure au cas où la Slice 04 en ferait un statut plutôt qu'une raison.
LIVE_STATUSES = {"queued", "eligible", "deferred", "selected", "held_for_brain", "held"}


def retired(status: str) -> bool:
    """Statut terminal non dit : ni vivant, ni dit (`superseded`, `expired`, ou un nom neuf)."""
    return status not in SPOKEN_STATUSES and status not in LIVE_STATUSES


# --------------------------------------------------------------------------- montage


@dataclass
class ScriptedBrain:
    """Cerveau dont chaque tour dit ce qu'on lui dicte, puis réussit.

    `replies[texte du tour]` : les paroles à émettre, `(texte, genre)`. Un tour
    absent du script réussit sans rien dire — c'est le « tour terminé sans
    réémission » de T4. Un tour de `failing` lève : c'est le tour en échec de T4b.
    """

    replies: dict[str, list[tuple[str, SpeechKind]]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    #: `(texte du tour, BrainContext)` de chaque tour reçu.
    contexts: list = field(default_factory=list)

    async def run_turn_with_context(self, turn: BrainTurnInput, context, emit) -> BrainTurnResult:
        self.contexts.append((turn.text, context))
        return await self.run_turn(turn, context.state, emit)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        del state
        if turn.text in self.failing:
            raise RuntimeError("cerveau en panne (scénario)")
        work_id = f"brain-turn:{turn.correlation_id}"
        said = self.replies.get(turn.text, [])
        for text, kind in said:
            await emit.emit(BrainEvent(
                kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
                correlation_id=turn.correlation_id, work_id=work_id,
                speech=SpeechRequest(conversation_id=turn.conversation_id, text=text, kind=kind, work_id=work_id)))
        return BrainTurnResult(correlation_id=turn.correlation_id,
                               public_summary=" ".join(text for text, _ in said))

    def pending_texts(self, turn_text: str) -> list[str]:
        """Textes remis au cerveau (`pending_replies`) pour le tour de ce texte."""
        return [reply.text for text, context in self.contexts if text == turn_text
                for reply in getattr(context, "pending_replies", ())]


class NullSink:
    def emit(self, kind: str, message: str, *, level: str = "info", data=None) -> None:  # noqa: ANN001
        del kind, message, level, data


class HeldWorker:
    """Job long qui ne finit que quand le test le libère ; note toute annulation."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.cancelled: list[str] = []

    async def execute(self, job: Job) -> dict[str, object]:
        del job
        await self.release.wait()
        return {"ok": True}

    async def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)


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
    session: FakeVoiceSession | FakeRealtimeSession
    journal: RecordingJournal
    conversation_id: str
    state: SQLiteStateRepository
    bus: CoreEventBus
    jobs: JobService | None
    #: `speech_id -> texte` de chaque parole que Core a publiée (bus), pour ne
    #: pas lire l'état privé de la bouche.
    speech_texts: dict[str, str]
    recorder: asyncio.Task
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
                await asyncio.sleep(0.005)
        await asyncio.wait_for(loop(), timeout=TIMEOUT_S)

    def queued(self, text: str) -> list[str]:
        """Identifiants des paroles de ce texte que la bouche a reçues."""
        return [str(event["data"]["speech_id"]) for event in self.journal.of("voice.speech.queued")
                if self.speech_texts.get(str(event["data"].get("speech_id"))) == text]

    def decisions(self, speech_id: str) -> list[tuple[str, str]]:
        return [(event["data"]["status"], event["data"]["reason"]) for event in self.journal.of(SPEECH_DECIDED)
                if event["data"].get("speech_id") == speech_id]

    def started(self, speech_id: str) -> bool:
        return any(status in SPOKEN_STATUSES for status, _ in self.decisions(speech_id))

    def retired_for(self, speech_id: str, reason: str) -> bool:
        return any(retired(status) and why == reason for status, why in self.decisions(speech_id))

    def spoken(self) -> list[str]:
        return self.session.texts()

    async def until(self, predicate, *, what: str, budget_s: float = TIMEOUT_S) -> None:
        async def loop() -> None:
            while not predicate():
                await asyncio.sleep(0.005)
        try:
            await asyncio.wait_for(loop(), timeout=budget_s)
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

    async def let_the_mouth_speak(self, seconds: float) -> None:
        """Pendant `seconds` simulées, finir toute sortie que la bouche ouvre."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while loop.time() < deadline:
            if self.session.active_output_id is not None:
                await finish_speech(self.scheduler, self.session)
            await asyncio.sleep(0.01)


async def _record_speech(queue: asyncio.Queue, texts: dict[str, str]) -> None:
    while True:
        envelope = await queue.get()
        if envelope.message_type == BRAIN_SPEECH_REQUESTED:
            texts[str(envelope.payload.get("speech_id"))] = str(envelope.payload.get("text"))


async def stage(tmp_path, brain_script: ScriptedBrain, *, session=None, workers=None) -> Stage:
    loop = asyncio.get_running_loop()
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    bus = CoreEventBus()
    jobs = JobService(state, bus, workers, diagnostics=NullSink()) if workers else None
    brain = BrainOrchestrator(conversations=conversations, events=bus, backend=brain_script, jobs=jobs,
                              diagnostics=NullSink())
    texts: dict[str, str] = {}
    recorder = asyncio.create_task(_record_speech(bus.subscribe(), texts), name="test-speech-texts")
    conversation = await conversations.create()
    session = session if session is not None else FakeVoiceSession()
    journal = RecordingJournal()
    scheduler = SpeechScheduler(core=InProcessCore(brain, bus), conversation_id=conversation.id, session=session,
                                journal=journal, clock=VirtualWallClock(loop, utc_now()), reconnect_delay_s=0.0,
                                output_timeout_s=TIMEOUT_S)
    await scheduler.start()
    return Stage(brain, scheduler, session, journal, conversation.id, state, bus, jobs, texts, recorder)


async def close(scene: Stage) -> None:
    await scene.scheduler.stop()
    await scene.brain.stop()
    if scene.jobs is not None:
        await scene.jobs.stop()
    scene.recorder.cancel()
    await asyncio.gather(scene.recorder, return_exceptions=True)
    await scene.state.close()


def staged(tmp_path, brain_script: ScriptedBrain, play, **options):
    """Monter la scène, jouer `play(scene)` en temps virtuel, tout démonter."""

    async def main():
        scene = await stage(tmp_path, brain_script, **options)
        try:
            return await play(scene)
        finally:
            await close(scene)

    return run_virtual(main())


# ----------------------------------------------------------- tour de retard (S04)

FIRST_QUESTION = "Quelle heure est-il ?"
OLD_ANSWER = "Il est midi."
SECOND_QUESTION = "Et quel temps fait-il ?"
NEW_ANSWER = "Il fait beau."
THIRD_QUESTION = "Tu es toujours là ?"


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
def test_the_fresh_answer_is_said_before_an_answer_written_for_the_previous_question(tmp_path):
    """T3 — B' (RESULT, intention N) arrive alors que A (RESULT, N-1) attend :
    la bouche sert B' d'abord."""

    async def play(scene: Stage):
        await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await scene.until(lambda: scene.queued(NEW_ANSWER), what="B' reçue par la bouche")
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.until(lambda: scene.spoken(), what="une première parole")
        return scene.spoken()

    spoken = staged(tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)],
                                             SECOND_QUESTION: [(NEW_ANSWER, SpeechKind.RESULT)]}), play)
    assert spoken[0] == NEW_ANSWER, (
        f"la bouche a servi {spoken[0]!r} (rédigée pour la question précédente) avant la réponse fraîche "
        f"{NEW_ANSWER!r}")


@pytest.mark.xfail(strict=True, reason="S04: a past-intent formulation must be held_for_brain, then retired as "
                                       "not_revalidated when the brain does not re-emit it, never spoken")
def test_an_old_answer_the_brain_does_not_repeat_is_never_said(tmp_path):
    """T4 — même scène ; le cerveau termine son tour sans réémettre A : A n'est
    jamais dite, et sa trace dit pourquoi — retenue (`held_for_brain`) puis
    retirée (`not_revalidated`)."""

    async def play(scene: Stage):
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.until(lambda: OLD_ANSWER in scene.spoken() or scene.retired_for(old, "not_revalidated"),
                          what="un sort pour A (dite ou retirée not_revalidated)")
        return scene.spoken(), scene.started(old), scene.decisions(old)

    spoken, started, decisions = staged(
        tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}), play)
    assert OLD_ANSWER not in spoken and not started, (
        f"A ({OLD_ANSWER!r}) a été dite alors que le cerveau ne l'a pas réémise ; décisions de A : {decisions}")
    reasons = [reason for _, reason in decisions]
    assert any(retired(status) and reason == "not_revalidated" for status, reason in decisions), (
        f"A n'est pas retirée not_revalidated : {decisions}")
    assert "held_for_brain" in reasons and reasons.index("held_for_brain") < reasons.index("not_revalidated"), (
        f"A n'est pas passée par held_for_brain avant not_revalidated : {decisions}")


@pytest.mark.xfail(strict=True, reason="S04: a failed brain turn gives no verdict: the held formulation is neither "
                                       "spoken nor retired, and reaches the next successful turn in pending_replies")
def test_an_old_answer_survives_a_failed_brain_turn_and_is_judged_by_the_next_one(tmp_path):
    """T4b — A attend ; le tour N du cerveau échoue : A n'est ni dite ni retirée.
    Le tour suivant, réussi, reçoit A dans `pending_replies` et lui donne un
    verdict (ici : pas de réémission ⇒ `not_revalidated`)."""

    brain = ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}, failing={SECOND_QUESTION})

    async def play(scene: Stage):
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await release_surface(scene.scheduler, scene.surface_output)
        # Assez longtemps pour que la bouche dise A si elle le peut.
        await scene.let_the_mouth_speak(3.0)
        after_failure = (list(scene.spoken()), scene.decisions(old))
        await scene.turn(THIRD_QUESTION)
        await scene.until(lambda: OLD_ANSWER in scene.spoken() or any(retired(s) for s, _ in scene.decisions(old)),
                          what="un verdict pour A après le tour réussi")
        return old, after_failure, scene.spoken(), scene.started(old), scene.decisions(old)

    old, (spoken_after_failure, decisions_after_failure), spoken, started, decisions = staged(tmp_path, brain, play)
    assert OLD_ANSWER not in spoken_after_failure, (
        f"A a été dite après l'échec du tour du cerveau, sans verdict : décisions de A : {decisions_after_failure}")
    assert not any(retired(status) for status, _ in decisions_after_failure), (
        f"A a été retirée sans verdict du cerveau (tour en échec) : {decisions_after_failure}")
    assert OLD_ANSWER in brain.pending_texts(THIRD_QUESTION), (
        f"le tour réussi suivant n'a pas reçu A dans pending_replies : "
        f"{[(text, [r.text for r in getattr(ctx, 'pending_replies', ())]) for text, ctx in brain.contexts]}")
    assert OLD_ANSWER not in spoken and not started, f"A dite sans réémission : {decisions}"
    assert any(retired(status) and reason == "not_revalidated" for status, reason in decisions), (
        f"A n'a reçu aucun verdict après le tour réussi : {decisions}")


@pytest.mark.xfail(strict=True, reason="S04: a re-emitted answer must be said once, the old formulation "
                                       "retired as revalidated_as the new speech")
def test_an_old_answer_the_brain_repeats_is_said_exactly_once(tmp_path):
    """T5 — le cerveau réémet A sous l'intention courante (nouvelle parole) : le
    texte est dit une seule fois, l'ancienne formulation n'a jamais démarré, et
    elle est retirée `revalidated_as`.

    Le rattachement de la réémission à l'ancienne parole est un choix de la
    Slice 04 (champ explicite du cerveau ou règle documentée) ; si elle retient
    un champ explicite, c'est le script du cerveau ci-dessous qui le portera.
    """

    async def play(scene: Stage):
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await scene.until(lambda: len(scene.queued(OLD_ANSWER)) == 2, what="la réémission reçue par la bouche")
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.speak_until(lambda: scene.spoken().count(OLD_ANSWER) >= 2
                                or (scene.spoken().count(OLD_ANSWER) == 1
                                    and any(retired(status) for status, _ in scene.decisions(old))),
                                what="la réémission dite et l'ancienne soldée")
        return scene.spoken(), scene.started(old), scene.decisions(old)

    spoken, started, decisions = staged(tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)],
                                                                 SECOND_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}),
                                        play)
    assert spoken.count(OLD_ANSWER) == 1, (
        f"{OLD_ANSWER!r} a été dite {spoken.count(OLD_ANSWER)} fois ; décisions de l'ancienne : {decisions}")
    assert not started, f"c'est l'ancienne formulation qui a été dite, pas la réémission : {decisions}"
    assert any(retired(status) and reason == "revalidated_as" for status, reason in decisions), (
        f"l'ancienne formulation n'est pas retirée revalidated_as : {decisions}")


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


async def calibration_scene(scene: Stage) -> None:
    # Un tour silencieux installe l'intention courante que les relais empruntent.
    await scene.turn(CALIBRATION_START)
    scene.surface_output = await busy_surface(scene.scheduler)


@pytest.mark.xfail(strict=True, reason="S03: the calibration ACK must be typed ACK with a supersedes_key "
                                       "shared with its analysis; today both are eternal RESULT/NORMAL")
def test_the_calibration_acknowledgement_is_never_said_once_its_analysis_is_ready(tmp_path):
    """T6a — accusé puis analyse du même évènement, bouche occupée : quand la
    bouche se libère, l'analyse est dite et l'accusé ne l'est jamais."""

    async def play(scene: Stage):
        await calibration_scene(scene)
        assert await announce(scene.brain, CALIBRATION_ANALYSIS_ACK, kind=SpeechKind.ACK,
                              supersedes_key=CALIBRATION_KEY, ttl_s=ACK_TTL_S)
        assert await announce(scene.brain, CALIBRATION_ANALYSIS, kind=SpeechKind.RESULT,
                              supersedes_key=CALIBRATION_KEY)
        await scene.until(lambda: scene.queued(CALIBRATION_ANALYSIS), what="l'analyse reçue par la bouche")
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.speak_until(lambda: CALIBRATION_ANALYSIS in scene.spoken(), what="l'analyse dite")
        return scene.spoken()

    spoken = staged(tmp_path, ScriptedBrain(), play)
    assert CALIBRATION_ANALYSIS_ACK not in spoken, (
        f"l'accusé {CALIBRATION_ANALYSIS_ACK!r} a été dit alors que l'analyse était prête : {spoken}")


@pytest.mark.xfail(strict=True, reason="S03: an unsaid calibration ACK must expire (TTL); today it has none "
                                       "and is said whenever the mouth frees up")
def test_an_unsaid_calibration_acknowledgement_expires_instead_of_being_said_late(tmp_path):
    """T6b — l'accusé attend derrière une bouche occupée au-delà de sa durée de
    vie : il expire, tracé, et n'est jamais dit."""

    async def play(scene: Stage):
        await calibration_scene(scene)
        assert await announce(scene.brain, CALIBRATION_ANALYSIS_ACK, kind=SpeechKind.ACK,
                              supersedes_key=CALIBRATION_KEY, ttl_s=ACK_TTL_S)
        await scene.until(lambda: scene.queued(CALIBRATION_ANALYSIS_ACK), what="l'accusé reçu par la bouche")
        [ack] = scene.queued(CALIBRATION_ANALYSIS_ACK)
        # Au-delà de toute durée de vie d'un transitoire (Core 45 s, repli 60 s).
        await asyncio.sleep(120.0)
        await release_surface(scene.scheduler, scene.surface_output)
        await scene.until(lambda: CALIBRATION_ANALYSIS_ACK in scene.spoken()
                          or any(retired(status) for status, _ in scene.decisions(ack)),
                          what="un sort pour l'accusé (dit ou retiré)")
        return scene.spoken(), scene.decisions(ack)

    spoken, decisions = staged(tmp_path, ScriptedBrain(), play)
    assert CALIBRATION_ANALYSIS_ACK not in spoken, (
        f"l'accusé a été dit 120 s (simulées) après son émission ; décisions : {decisions}")
    assert ("expired", "ttl") in decisions, f"l'accusé n'a pas expiré : {decisions}"


# ------------------------------------------------------- interruption unifiée (S05)

#: Au plus ce délai sépare la fin de la phrase de l'utilisateur de la décision
#: d'adressage de son tour (transcription finale + classement). La file ne
#: redémarre pas d'elle-même avant.
ADDRESSING_WINDOW_S = 2.0
#: Après une décision « non adressé », la file reprend au plus dans ce délai.
RESUME_S = 1.0
#: Ce que dit un micro qui n'entend que du bruit : une hésitation isolée, que
#: `noise_reason` classe `filler` — le bridge l'écarte (`voice.transcript_dropped`)
#: et n'en fait pas un tour.
NOISE = "hum"
PLAYING = "Voici une longue réponse…"
QUEUED = "Et une seconde chose."


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
            playing = SpeechRequest(CONVERSATION, PLAYING, kind=SpeechKind.RESULT,
                                    correlation_id="corr-1", source=source("corr-1"))
            queued = SpeechRequest(CONVERSATION, QUEUED, kind=SpeechKind.RESULT,
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
    assert spoken == [PLAYING], (
        f"après le barge-in, la file est repartie sans attendre la décision d'adressage : dit = {spoken}")


def wire_bridge(scheduler: SpeechScheduler, session: FakeRealtimeSession, journal: RecordingJournal):
    """Le vrai bridge continu, câblé à la bouche comme `PersistentVoiceRuntime`.

    `FakeRealtimeSession` joue le fournisseur (`interrupt` = VAD serveur,
    `ambient` = transcript sans tour) ; `FakeAudio` le périphérique. Rend la
    tâche de consommation du flux fournisseur.
    """
    loop = asyncio.get_running_loop()
    bridge = RealtimeConversationBridge(
        core=FakeCore(), session=session, conversation_id=scheduler.conversation_id, audio=FakeAudio(),
        continuous=True, auto_turn=True, clock=loop.time,
        on_addressed=lambda: None, on_mute=lambda: None,
        on_output_event=scheduler.note_output_event,
        on_interruption=scheduler.note_interruption,
        on_user_speech=scheduler.note_user_speech,
        on_turn_abandoned=scheduler.abandon_turn,
        on_addressed_turn=scheduler.note_addressed_turn,
        output_admission=scheduler.output_admission,
        journal=journal,
    )
    scheduler.output_alive = bridge.output_pending
    return asyncio.create_task(bridge._consume(session.events()), name="test-bridge")


async def barge_in_then_noise(session: FakeRealtimeSession, journal: RecordingJournal) -> tuple[list[str], list[str]]:
    """Jarvis dit PLAYING (QUEUED attend) ; l'utilisateur le coupe, se tait ; la
    décision d'adressage tombe ADDRESSING_WINDOW_S / 2 plus tard : du bruit.

    Rend `(dit avant la décision, dit RESUME_S après)`.
    """
    while len(session.spoken) < 1:
        await asyncio.sleep(0.01)
    await session.play_audio(chunks=30)
    await asyncio.sleep(0.2)
    await session.interrupt()
    await asyncio.sleep(0.8)
    await session.push("realtime.speech_stopped")
    await asyncio.sleep(ADDRESSING_WINDOW_S / 2)
    before = session.texts()
    dropped = journal.count("voice.transcript_dropped")
    await session.ambient(NOISE)
    while journal.count("voice.transcript_dropped") == dropped:
        await asyncio.sleep(0.01)
    await asyncio.sleep(RESUME_S)
    assert journal.count("voice.barge_in") >= 1, "le scénario n'a pas produit de barge-in réel"
    return before, session.texts()


@pytest.mark.xfail(strict=True, reason="S05: the queue frozen by a barge-in must stay frozen until the addressing "
                                       "decision, then resume on an unaddressed/noise decision")
def test_a_queued_answer_resumes_once_the_barge_in_turns_out_to_be_noise():
    """T7b — barge-in réel (bridge), A en file ; l'utilisateur se tait, puis le
    bridge classe ce qu'il a dit comme du bruit (`voice.transcript_dropped`) :
    A n'a pas démarré avant cette décision, et démarre juste après. Une file
    gelée pour toujours échoue ici."""

    async def scenario():
        loop = asyncio.get_running_loop()
        session, journal = FakeRealtimeSession(), RecordingJournal()
        scheduler = build_scheduler(FakeCore(), session, journal=journal,
                                    clock=VirtualWallClock(loop, utc_now()), output_timeout_s=None)
        await scheduler.start()
        consumer = wire_bridge(scheduler, session, journal)
        try:
            for text in (PLAYING, QUEUED):
                scheduler._enqueue(SpeechRequest(CONVERSATION, text, kind=SpeechKind.RESULT,
                                                 correlation_id="corr-1", source=source("corr-1")))
            return await barge_in_then_noise(session, journal)
        finally:
            await scheduler.stop()
            await session.close()
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)

    before, after = run_virtual(scenario())
    assert before == [PLAYING], f"A a démarré avant la décision d'adressage : dit = {before}"
    assert after == [PLAYING, QUEUED], (
        f"la décision « bruit » n'a pas rendu la file : A n'a pas démarré {RESUME_S} s après ; dit = {after}")


@pytest.mark.xfail(strict=True, reason="S05: freezing the queue on a barge-in must not cancel the work in progress "
                                       "(Decisions 15/35); today the queue is not frozen at all")
def test_a_barge_in_freezes_the_queue_without_cancelling_the_work_in_progress(tmp_path):
    """T7c — Core réel, un job lancé par le tour en cours tourne ; le cerveau a dit
    PLAYING puis QUEUED (en file). Barge-in réel, puis bruit : le job n'est pas
    annulé (ni statut, ni `cancel` du worker), et la file a attendu la décision
    avant de reprendre."""

    worker = HeldWorker()
    ask = "Lance le rapport et préviens-moi."

    async def play(scene: Stage):
        consumer = wire_bridge(scene.scheduler, scene.session, scene.journal)
        try:
            turn = await scene.turn(ask)
            job = await scene.jobs.submit(Job(kind="report", requested_by_conversation_id=scene.conversation_id),
                                          work_id=f"brain-turn:{turn.correlation_id}",
                                          correlation_id=turn.correlation_id)
            before, after = await barge_in_then_noise(scene.session, scene.journal)
            stored = await scene.state.get_job(job.id)
            return before, after, stored.status, list(worker.cancelled)
        finally:
            worker.release.set()
            await scene.session.close()
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)

    before, after, job_status, cancelled = staged(
        tmp_path, ScriptedBrain({ask: [(PLAYING, SpeechKind.RESULT), (QUEUED, SpeechKind.RESULT)]}), play,
        session=FakeRealtimeSession(), workers={"report": worker})
    assert job_status == JobStatus.RUNNING and cancelled == [], (
        f"le barge-in a touché au travail en cours : job {job_status}, cancel du worker {cancelled}")
    assert before == [PLAYING], f"A a démarré avant la décision d'adressage : dit = {before}"
    assert after == [PLAYING, QUEUED], f"la file n'a pas repris après la décision « bruit » : dit = {after}"
