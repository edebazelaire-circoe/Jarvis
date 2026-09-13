"""Révision d'intention côté Core (Tâche 09b).

Ce fichier prouve l'intention verrouillée du projet : « User interruption stops
speech quickly but does not auto-cancel work ». Autrement dit, une nouvelle
intention utilisateur **garde** le travail en cours, et seule une décision
explicite du cerveau désignant un `work_id` peut le retirer.

Trois frontières sont éprouvées ici :

- la rétention par défaut, y compris quand plusieurs tours s'enchaînent ;
- l'annulation explicite, qui arrête le job visé et lui seul ;
- la course « le résultat du cerveau arrive au moment de la révision », qui doit
  se solder de façon déterministe et non selon l'ordonnancement asyncio.

Ce qui n'est **pas** prouvé ici : la séquence de barge-in côté surface
(`realtime.speech_started`, troncature, `interrupted_speech_id`), qui appartient
aux tranches 09a et 09c.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_service import (
    BRAIN_INTENT_REVISED,
    BRAIN_SPEECH_REQUESTED,
    BRAIN_STATE_UPDATED,
    BRAIN_TURN_ACCEPTED,
    BrainOrchestrator,
)
from jarvis.core.v2_services import ConversationService, CoreEventBus, JobService
from jarvis.core.brain_outcomes import BRAIN_OUTCOME_AVAILABLE
from jarvis.domain.v2 import (
    AddressingDecision,
    BrainEvent,
    BrainEventKind,
    BrainIntentRevision,
    BrainTurnInput,
    BrainTurnResult,
    Job,
    JobStatus,
    ProtocolEnvelope,
    SpeechKind,
    SpeechRequest,
    SpeechProvenance,
    TurnKind,
)

# Clés exigées par docs/handoff-realtime-brain/docs/05-event-contracts.md pour
# `brain.intent.revised`.
DOC_REVISION_KEYS = {"revision", "previous_revision", "superseded_work_ids", "cancelled_work_ids", "retained_work_ids"}

TIMEOUT_S = 5.0


# --- doubles -----------------------------------------------------------------


@dataclass(slots=True)
class RecordingSink:
    events: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _level, _data in self.events]

    def of(self, kind: str) -> list[dict]:
        return [data for name, _level, data in self.events if name == kind]


@dataclass(slots=True)
class RecordingCanceller:
    """`WorkCanceller` de test : il note ce qu'on lui demande d'arrêter."""

    jobs_by_work: dict[str, tuple[str, ...]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def cancel_work(self, work_id: str) -> tuple[str, ...]:
        self.calls.append(work_id)
        return self.jobs_by_work.get(work_id, ())


@dataclass(slots=True)
class ExplodingCanceller:
    calls: list[str] = field(default_factory=list)

    async def cancel_work(self, work_id: str) -> tuple[str, ...]:
        self.calls.append(work_id)
        raise RuntimeError("job service unreachable")


@dataclass(slots=True)
class DrivenBackend:
    """Backend piloté pas à pas par le test.

    Il expose le `BrainEventSink` que l'orchestrateur lui remet, puis attend
    `release`. Le test émet donc ses `BrainEvent` par le vrai chemin — celui
    qu'un backend réel emprunte — pendant que le tour est **encore en vol**.
    """

    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    sink: object | None = None
    cancelled: list[str] = field(default_factory=list)
    summary: str = ""

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.sink = emit
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.append(turn.correlation_id)
            raise
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=self.summary)

    async def emit(self, event: BrainEvent) -> None:
        await self.sink.emit(event)


@dataclass(slots=True)
class IdleWorker:
    """Worker qui ne se termine jamais tout seul : seul un cancel le solde."""

    started: dict[str, asyncio.Event] = field(default_factory=dict)
    cancel_calls: list[str] = field(default_factory=list)

    async def execute(self, job: Job) -> dict[str, object]:
        self.started.setdefault(job.id, asyncio.Event()).set()
        await asyncio.Event().wait()
        return {"ok": True}

    async def cancel(self, job_id: str) -> None:
        self.cancel_calls.append(job_id)


# --- outillage ---------------------------------------------------------------


async def build_orchestrator(tmp_path, backend=None, *, jobs=None, diagnostics=None):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    events = CoreEventBus()
    brain = BrainOrchestrator(
        conversations=conversations,
        events=events,
        backend=backend,
        jobs=jobs,
        diagnostics=diagnostics,
    )
    conversation = await conversations.create()
    return brain, events, state, conversation.id


async def start_turn(brain, backend, conversation_id: str, text: str) -> BrainTurnInput:
    """Soumettre un tour et rendre la main quand le backend a reçu son puits."""

    turn = BrainTurnInput(conversation_id=conversation_id, text=text)
    await brain.submit(turn)
    await asyncio.wait_for(backend.started.wait(), timeout=TIMEOUT_S)
    return turn


def drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected: list[ProtocolEnvelope] = []
    while True:
        try:
            collected.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return collected


def revisions(published: list[ProtocolEnvelope]) -> list[dict]:
    return [envelope.payload for envelope in published if envelope.message_type == BRAIN_INTENT_REVISED]


def work_event(kind: BrainEventKind, conversation_id: str, correlation_id: str, work_id: str | None = "work-1") -> BrainEvent:
    return BrainEvent(
        kind=kind,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        work_id=work_id,
        public_summary="Recherche des messages",
    )


def speech_event(conversation_id: str, correlation_id: str, *, work_id: str, text: str, kind=SpeechKind.RESULT) -> BrainEvent:
    return BrainEvent(
        kind=BrainEventKind.SPEECH,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        work_id=work_id,
        speech=SpeechRequest(conversation_id=conversation_id, text=text, kind=kind, work_id=work_id),
    )


# --- contrat de l'évènement --------------------------------------------------


def test_intent_revision_partitions_work_and_must_advance():
    revision = BrainIntentRevision(
        conversation_id="conv-1",
        revision=9,
        previous_revision=8,
        cancelled_work_ids=("work-2",),
        retained_work_ids=("work-1",),
    )
    assert set(revision.to_payload()) == DOC_REVISION_KEYS | {"conversation_id"}
    assert revision.to_payload()["superseded_work_ids"] == []

    with pytest.raises(ValueError):
        # Une révision qui n'avance pas rendrait la détection de trou aveugle.
        BrainIntentRevision(conversation_id="conv-1", revision=8, previous_revision=8)
    with pytest.raises(ValueError):
        # Un travail ne peut pas être gardé et annulé à la fois.
        BrainIntentRevision(
            conversation_id="conv-1",
            revision=9,
            previous_revision=8,
            cancelled_work_ids=("work-1",),
            retained_work_ids=("work-1",),
        )


def test_removing_work_always_names_it():
    """Retirer du travail se fait par désignation, jamais en bloc."""

    for kind in (BrainEventKind.SUPERSEDED, BrainEventKind.CANCELLED):
        with pytest.raises(ValueError):
            BrainEvent(kind=kind, conversation_id="conv-1", correlation_id="corr-1")
        assert BrainEvent(kind=kind, conversation_id="conv-1", correlation_id="corr-1", work_id="work-1").work_id == "work-1"


# --- rétention par défaut ----------------------------------------------------


async def test_a_new_user_intent_retains_running_work(tmp_path):
    """Intention verrouillée : interrompre n'annule pas le travail en cours."""

    backend = DrivenBackend()
    canceller = RecordingCanceller()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend, jobs=canceller)
    try:
        first = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        await backend.emit(work_event(BrainEventKind.ACCEPTED, conversation_id, first.correlation_id))
        assert brain.working_state(conversation_id).active_work_ids == ("work-1",)

        queue = events.subscribe()
        # L'utilisateur reprend la parole pendant que le travail tourne.
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="En fait, seulement ceux de cette semaine."))

        payloads = revisions(drain(queue))
        assert len(payloads) == 1
        assert payloads[0]["retained_work_ids"] == ["work-1"]
        assert payloads[0]["cancelled_work_ids"] == []
        assert payloads[0]["superseded_work_ids"] == []
        # Le travail tourne toujours, et rien n'a été demandé à l'exécuteur.
        assert brain.working_state(conversation_id).active_work_ids == ("work-1",)
        assert canceller.calls == []
        assert backend.cancelled == []
        assert brain.active_turn_count == 2
    finally:
        await brain.stop()
        await state.close()


async def test_the_revision_is_published_between_acceptance_and_state(tmp_path):
    """Ordre causal : accusé, puis révision d'intention, puis état public."""

    brain, events, state, conversation_id = await build_orchestrator(tmp_path)
    queue = events.subscribe()
    try:
        turn = BrainTurnInput(conversation_id=conversation_id, text="Bonjour.")
        acceptance = await brain.submit(turn)
        published = drain(queue)
        assert [e.message_type for e in published][:3] == [BRAIN_TURN_ACCEPTED, BRAIN_INTENT_REVISED, BRAIN_STATE_UPDATED]

        payload = revisions(published)[0]
        assert set(payload) == DOC_REVISION_KEYS | {"conversation_id", "schema_version", "source", "current_speech_source", "source_complete", "invalidated_dependencies"}
        assert payload["revision"] == acceptance.revision == 1
        assert payload["previous_revision"] == 0
        assert published[1].correlation_id == turn.correlation_id
        assert published[1].conversation_id == conversation_id
    finally:
        await brain.stop()
        await state.close()


# --- décision explicite ------------------------------------------------------


async def test_explicit_brain_cancellation_stops_the_named_work_only(tmp_path):
    backend = DrivenBackend()
    canceller = RecordingCanceller(jobs_by_work={"work-1": ("job-1",)})
    sink = RecordingSink()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend, jobs=canceller, diagnostics=sink)
    try:
        turn = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        for work_id in ("work-1", "work-2"):
            await backend.emit(work_event(BrainEventKind.ACCEPTED, conversation_id, turn.correlation_id, work_id))
        assert brain.working_state(conversation_id).active_work_ids == ("work-1", "work-2")

        queue = events.subscribe()
        await backend.emit(work_event(BrainEventKind.CANCELLED, conversation_id, turn.correlation_id, "work-1"))

        payload = revisions(drain(queue))[0]
        assert payload["cancelled_work_ids"] == ["work-1"]
        assert payload["retained_work_ids"] == ["work-2"]
        assert payload["superseded_work_ids"] == []
        # L'annulation est réelle : elle atteint l'exécutant, et lui seul.
        assert canceller.calls == ["work-1"]
        assert brain.working_state(conversation_id).active_work_ids == ("work-2",)
        assert sink.of("core.brain.work_cancelled")[0]["job_ids"] == ["job-1"]
    finally:
        await brain.stop()
        await state.close()


async def test_cancelling_twice_produces_a_single_revision(tmp_path):
    backend = DrivenBackend()
    canceller = RecordingCanceller()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend, jobs=canceller)
    try:
        turn = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        queue = events.subscribe()
        event = work_event(BrainEventKind.CANCELLED, conversation_id, turn.correlation_id, "work-1")
        await backend.emit(event)
        await backend.emit(event)

        assert len(revisions(drain(queue))) == 1
        assert canceller.calls == ["work-1"]
    finally:
        await brain.stop()
        await state.close()


async def test_a_failing_canceller_does_not_hide_the_decision(tmp_path):
    """Un exécutant injoignable ne doit pas faire disparaître la révision."""

    backend = DrivenBackend()
    sink = RecordingSink()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend, jobs=ExplodingCanceller(), diagnostics=sink)
    try:
        turn = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        queue = events.subscribe()
        await backend.emit(work_event(BrainEventKind.CANCELLED, conversation_id, turn.correlation_id, "work-1"))

        assert revisions(drain(queue))[0]["cancelled_work_ids"] == ["work-1"]
        assert "core.brain.work_cancel_failed" in sink.kinds()
    finally:
        await brain.stop()
        await state.close()


async def test_supersession_keeps_the_work_running(tmp_path):
    """Moitié non destructrice : la parole périme, le travail continue."""

    backend = DrivenBackend()
    canceller = RecordingCanceller()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend, jobs=canceller)
    try:
        turn = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        await backend.emit(work_event(BrainEventKind.ACCEPTED, conversation_id, turn.correlation_id))
        assert brain.working_state(conversation_id).active_work_ids == ("work-1",)

        queue = events.subscribe()
        await backend.emit(work_event(BrainEventKind.SUPERSEDED, conversation_id, turn.correlation_id))

        published = drain(queue)
        payload = revisions(published)[0]
        assert payload["superseded_work_ids"] == ["work-1"]
        assert payload["cancelled_work_ids"] == []
        assert payload["retained_work_ids"] == []
        # Le contenu de l'état public n'a pas bougé : rien ne le republie.
        assert [e.message_type for e in published] == [BRAIN_INTENT_REVISED]
        assert brain.working_state(conversation_id).active_work_ids == ("work-1",)
        assert canceller.calls == []
    finally:
        await brain.stop()
        await state.close()


# --- course résultat / révision ----------------------------------------------


async def test_a_result_arriving_during_the_revision_is_still_spoken_by_default(tmp_path):
    """Rétention : le tour en vol garde le droit de rendre son résultat."""

    backend = DrivenBackend()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    try:
        turn = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        await backend.emit(work_event(BrainEventKind.ACCEPTED, conversation_id, turn.correlation_id))

        queue = events.subscribe()
        # L'utilisateur reprend la parole exactement quand le résultat part.
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Autre chose."))
        await backend.emit(
            speech_event(conversation_id, turn.correlation_id, work_id="work-1", text="Trois messages attendent une réponse.")
        )

        spoken = [e.payload["text"] for e in drain(queue) if e.message_type == BRAIN_SPEECH_REQUESTED]
        assert spoken == ["Trois messages attendent une réponse."]
    finally:
        await brain.stop()
        await state.close()


async def test_a_result_of_cancelled_work_is_never_published(tmp_path):
    """Course tranchée dans Core, pas laissée à l'ordonnancement asyncio."""

    backend = DrivenBackend()
    sink = RecordingSink()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend, diagnostics=sink)
    try:
        turn = await start_turn(brain, backend, conversation_id, "Regarde les mails de Paul.")
        await backend.emit(work_event(BrainEventKind.ACCEPTED, conversation_id, turn.correlation_id))

        await backend.emit(work_event(BrainEventKind.CANCELLED, conversation_id, turn.correlation_id))
        queue = events.subscribe()
        # La tâche du tour n'a pas encore vu l'annulation et émet son résultat.
        await backend.emit(
            speech_event(conversation_id, turn.correlation_id, work_id="work-1", text="Trois messages attendent une réponse.")
        )
        # Une parole d'un autre travail n'est, elle, pas concernée.
        await backend.emit(
            speech_event(conversation_id, turn.correlation_id, work_id="work-2", text="Le dossier est prêt.")
        )

        spoken = [e.payload["text"] for e in drain(queue) if e.message_type == BRAIN_SPEECH_REQUESTED]
        assert spoken == ["Le dossier est prêt."]
        assert sink.of("core.brain.speech_dropped")[0]["work_id"] == "work-1"
    finally:
        await brain.stop()
        await state.close()


# --- annulation réelle du job ------------------------------------------------


async def test_cancel_work_cancels_only_the_jobs_of_that_work(tmp_path):
    """`JobService` annule le job désigné par le `work_id`, et lui seul."""

    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    worker = IdleWorker()
    jobs = JobService(state, CoreEventBus(), {"mail_search": worker})
    try:
        kept = await jobs.submit(Job(kind="mail_search"), work_id="work-2", correlation_id="corr-1")
        doomed = await jobs.submit(Job(kind="mail_search"), work_id="work-1", correlation_id="corr-1")
        for job in (kept, doomed):
            await asyncio.wait_for(worker.started.setdefault(job.id, asyncio.Event()).wait(), timeout=TIMEOUT_S)

        cancelled = await jobs.cancel_work("work-1")
        assert cancelled == (doomed.id,)

        async def statuses() -> dict[str, JobStatus]:
            return {job.id: job.status for job in await state.list_jobs()}

        while (await statuses())[doomed.id] is JobStatus.RUNNING:
            await asyncio.sleep(0)
        stored = await statuses()
        assert stored[doomed.id] is JobStatus.CANCELLED
        assert stored[kept.id] is JobStatus.RUNNING
        assert worker.cancel_calls == [doomed.id]
        # Un travail inconnu n'annule rien : ce n'est pas une panne.
        assert await jobs.cancel_work("work-404") == ()
    finally:
        await jobs.stop()
        await state.close()


# --- adressage incertain (Décision 44, moitié aval) --------------------------


@dataclass(slots=True)
class AnsweringBackend:
    """Backend qui rend l'issue qu'on lui dicte, sans rien émettre d'autre.

    `summary` vide reproduit exactement la récusation `[pas-pour-moi]` :
    `ControlCenterBrainBackend._public_answer` la traduit en réponse vide, et
    c'est cette réponse vide qui arrive jusqu'ici.
    """

    summary: str = ""
    seen_states: list = field(default_factory=list)

    async def run_turn(self, turn: BrainTurnInput, state, emit) -> BrainTurnResult:
        self.seen_states.append(state)
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=self.summary)


async def wait_idle(brain) -> None:
    async def loop() -> None:
        while brain.active_turn_count:
            await asyncio.sleep(0)

    await asyncio.wait_for(loop(), timeout=TIMEOUT_S)


@pytest.mark.parametrize("newer", ["addressed", "confirmed", "recused", "unconfirmed"])
async def test_late_uncertain_confirmation_preserves_latest_confirmed_intent(tmp_path, newer):
    class OrderedBackend:
        def __init__(self):
            self.release = {key: asyncio.Event() for key in ("old", "new")}
            self.started = {key: asyncio.Event() for key in ("old", "new")}

        async def run_turn(self, turn, state, emit):
            work_id = f"work-{turn.correlation_id}"
            await emit.emit(BrainEvent(kind=BrainEventKind.ACCEPTED, conversation_id=turn.conversation_id, correlation_id=turn.correlation_id, work_id=work_id))
            self.started[turn.correlation_id].set()
            await self.release[turn.correlation_id].wait()
            summary = "" if turn.correlation_id == "new" and newer == "recused" else f"Result {turn.correlation_id}"
            if summary:
                await emit.emit(BrainEvent(
                    kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id, work_id=work_id,
                    speech=SpeechRequest(conversation_id=turn.conversation_id, text=summary, kind=SpeechKind.RESULT, work_id=work_id),
                ))
            await emit.emit(BrainEvent(kind=BrainEventKind.COMPLETED, conversation_id=turn.conversation_id, correlation_id=turn.correlation_id, work_id=work_id, public_summary=summary))
            return BrainTurnResult(correlation_id=turn.correlation_id, public_summary=summary)

    backend = OrderedBackend()
    canceller = RecordingCanceller()
    brain, events, repository, conversation_id = await build_orchestrator(tmp_path, backend, jobs=canceller)
    queue = events.subscribe()
    cold = BrainOrchestrator(conversations=brain._conversations, events=CoreEventBus())
    revisions = []
    try:
        for correlation_id, text, addressing in (
            ("old", "January", AddressingDecision.UNCERTAIN),
            ("new", "February", AddressingDecision.ADDRESSED if newer == "addressed" else AddressingDecision.UNCERTAIN),
        ):
            await brain.submit(BrainTurnInput(conversation_id=conversation_id, text=text, correlation_id=correlation_id, addressing=addressing))
            await asyncio.wait_for(backend.started[correlation_id].wait(), timeout=TIMEOUT_S)

        # Newer replies first; the unconfirmed case stays in flight throughout.
        for correlation_id in (("old",) if newer == "unconfirmed" else ("new", "old")):
            task = brain._tasks[correlation_id]
            backend.release[correlation_id].set()
            await asyncio.wait_for(asyncio.shield(task), timeout=TIMEOUT_S)
            # Model the ordinary assistant-turn persistence on completed delivery.
            for event in drain(queue):
                if event.message_type == BRAIN_INTENT_REVISED:
                    revisions.append(event.correlation_id)
                if event.message_type == BRAIN_SPEECH_REQUESTED:
                    await brain._conversations.append_turn(
                        conversation_id, TurnKind.ASSISTANT, event.payload["text"],
                        correlation_id=event.correlation_id,
                        metadata={"provenance": SpeechProvenance.BRAIN.value, "speech_kind": SpeechKind.RESULT.value},
                    )

        expected = "February" if newer in ("addressed", "confirmed") else "January"
        current = brain.working_state(conversation_id)
        assert current.current_user_intent == expected
        restored = await cold.rehydrate(conversation_id)
        assert restored["current_user_intent"] == expected
        assert revisions == (["new"] if newer in ("addressed", "confirmed") else ["old"])
        assert "Result old" in current.known_public_facts
        assert "Result old" in restored["known_public_facts"]
        assert "work-old" in current.completed_work_ids
        assert current.active_work_ids == (("work-new",) if newer == "unconfirmed" else ())
        assert canceller.calls == []
    finally:
        await cold.stop()
        await brain.stop()
        await repository.close()


async def test_an_uncertain_turn_does_not_overwrite_the_current_intent(tmp_path):
    """Scénario du critique : une phrase captée à côté n'efface pas l'état public.

    Un tour adressé pose une intention, le cerveau pose une question, puis une
    phrase dont la surface n'a pas su si elle lui était adressée arrive marquée
    `uncertain`. Tant que le cerveau n'a pas dit qu'elle le concernait,
    l'intention courante et les questions ouvertes de Core doivent être
    exactement celles d'avant — c'est cet état-là que la Décision 45 envoie au
    cerveau au tour suivant.
    """

    backend = DrivenBackend()
    brain, _events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    try:
        addressed = await start_turn(brain, backend, conversation_id, "Jarvis fais les comptes")
        await backend.emit(
            speech_event(
                conversation_id,
                addressed.correlation_id,
                work_id="work-1",
                text="Quel mois ?",
                kind=SpeechKind.QUESTION,
            )
        )
        before = brain.working_state(conversation_id)
        assert before.current_user_intent == "Jarvis fais les comptes"
        assert before.unresolved_questions == ("Quel mois ?",)

        await brain.submit(
            BrainTurnInput(
                conversation_id=conversation_id,
                text="il faudrait vraiment que quelqu un rappelle le plombier demain matin",
                addressing=AddressingDecision.UNCERTAIN,
            )
        )

        after = brain.working_state(conversation_id)
        assert after.current_user_intent == "Jarvis fais les comptes"
        assert after.unresolved_questions == ("Quel mois ?",)
        assert after.revision == before.revision
    finally:
        await brain.stop()
        await state.close()


async def test_an_uncertain_turn_is_acknowledged_without_announcing_a_revision(tmp_path):
    """Un tour incertain publie l'accusé, et rien qui prétende avoir révisé.

    Publier `brain.intent.revised` sans avoir rien révisé serait un mensonge ;
    l'accusé, lui, reste dû — le tour a bien été reçu et persisté. Il porte la
    révision courante, inchangée, donc aucun trou pour l'ordonnanceur de parole
    (Décision 31).
    """

    backend = DrivenBackend()
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()
    try:
        turn = BrainTurnInput(
            conversation_id=conversation_id,
            text="on ira peut etre au cinema ce soir si la pluie s arrete",
            addressing=AddressingDecision.UNCERTAIN,
        )
        acceptance = await brain.submit(turn)

        published = drain(queue)
        assert [e.message_type for e in published] == [BRAIN_TURN_ACCEPTED]
        assert acceptance.revision == 0
        assert brain.working_state(conversation_id).revision == 0
    finally:
        await brain.stop()
        await state.close()


async def test_an_uncertain_turn_is_persisted_even_though_the_state_stays_untouched(tmp_path):
    """Ce qui a été dit a été dit : l'ingress reste unique (Décisions 06 et 30)."""

    backend = DrivenBackend()
    brain, _events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    try:
        await brain.submit(
            BrainTurnInput(
                conversation_id=conversation_id,
                text="il faudrait rappeler le plombier",
                addressing=AddressingDecision.UNCERTAIN,
            )
        )
        turns = await brain._conversations.list_turns(conversation_id)  # noqa: SLF001
        assert [turn.content for turn in turns] == ["il faudrait rappeler le plombier"]
        assert turns[0].metadata["addressing"] == "uncertain"
        assert turns[0].metadata["authoritative"] is True
    finally:
        await brain.stop()
        await state.close()


async def test_the_brain_taking_the_turn_promotes_it_to_the_current_intent(tmp_path):
    """Le cerveau répond : le tour incertain devient l'intention courante.

    C'est la confirmation la plus honnête disponible — le cerveau a produit une
    réponse publique pour ce tour — et elle publie alors la vraie séquence
    `brain.intent.revised` puis `brain.state.updated`.
    """

    backend = AnsweringBackend(summary="J'ai appelé le plombier.")
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    queue = events.subscribe()
    try:
        await brain.submit(
            BrainTurnInput(
                conversation_id=conversation_id,
                text="rappelle le plombier",
                addressing=AddressingDecision.UNCERTAIN,
            )
        )
        await wait_idle(brain)

        final = brain.working_state(conversation_id)
        assert final.current_user_intent == "rappelle le plombier"
        assert final.known_public_facts == ("J'ai appelé le plombier.",)
        assert [e.message_type for e in drain(queue)] == [
            BRAIN_TURN_ACCEPTED,
            BRAIN_OUTCOME_AVAILABLE,
            BRAIN_INTENT_REVISED,
            BRAIN_STATE_UPDATED,
            BRAIN_STATE_UPDATED,
        ]
    finally:
        await brain.stop()
        await state.close()


async def test_a_recused_uncertain_turn_leaves_no_trace_in_the_public_state(tmp_path):
    """`[pas-pour-moi]` arrive ici en réponse vide : rien ne doit bouger."""

    backend = AnsweringBackend(summary="")
    brain, events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    try:
        await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Jarvis fais les comptes"))
        await wait_idle(brain)
        before = brain.working_state(conversation_id)

        queue = events.subscribe()
        await brain.submit(
            BrainTurnInput(
                conversation_id=conversation_id,
                text="et toi tu penses quoi du match d hier soir",
                addressing=AddressingDecision.UNCERTAIN,
            )
        )
        await wait_idle(brain)

        after = brain.working_state(conversation_id)
        assert after.current_user_intent == before.current_user_intent == "Jarvis fais les comptes"
        assert after.known_public_facts == before.known_public_facts
        assert after.revision == before.revision
        assert [e.message_type for e in drain(queue)] == [BRAIN_TURN_ACCEPTED]
    finally:
        await brain.stop()
        await state.close()


async def test_a_question_asked_on_an_uncertain_turn_survives_its_promotion(tmp_path):
    """Le cerveau qui parle prend le tour : la promotion précède sa question.

    Sans cet ordre, la promotion — qui vide les questions ouvertes — effacerait
    la question que le cerveau vient de poser sur ce tour-là.
    """

    backend = DrivenBackend()
    brain, _events, state, conversation_id = await build_orchestrator(tmp_path, backend)
    try:
        turn = BrainTurnInput(
            conversation_id=conversation_id,
            text="regarde les comptes de janvier",
            addressing=AddressingDecision.UNCERTAIN,
        )
        await brain.submit(turn)
        await asyncio.wait_for(backend.started.wait(), timeout=TIMEOUT_S)
        await backend.emit(
            speech_event(
                conversation_id,
                turn.correlation_id,
                work_id="work-1",
                text="Quel format veux-tu ?",
                kind=SpeechKind.QUESTION,
            )
        )

        promoted = brain.working_state(conversation_id)
        assert promoted.current_user_intent == "regarde les comptes de janvier"
        assert promoted.unresolved_questions == ("Quel format veux-tu ?",)
    finally:
        await brain.stop()
        await state.close()
