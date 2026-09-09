"""Couture d'avancement du travail long (Tâche 10).

Ce fichier prouve trois frontières :

- un worker rapporte des **faits**, jamais une prise de parole (spec §13) ;
- l'avancement publié suit la charge de `docs/05-event-contracts.md` ;
- un worker bavard ne peut pas faire disparaître un abonné du bus borné
  (Décision 25, question ouverte n°6) — la limitation est faite à la source.

Ce qui n'est **pas** prouvé ici : le comportement d'un vrai worker long. Aucun
worker du dépôt ne rapporte encore d'avancement ; la Tâche 10 livre le contrat
plus une implémentation représentative, comme ses notes de reprise l'autorisent.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_services import (
    BRAIN_WORK_PROGRESS,
    JOB_PROGRESS_COALESCED_KIND,
    ConversationService,
    CoreEventBus,
    JobService,
)
from jarvis.domain.v2 import Job, JobProgress, JobStatus, ProtocolEnvelope, utc_now
from jarvis.ports.v2 import ProgressReportingJobWorker

# Clés exigées par docs/handoff-realtime-brain/docs/05-event-contracts.md.
DOC_PROGRESS_KEYS = {"work_id", "job_id", "phase", "fraction", "public_summary"}

# Un worker n'a aucun moyen d'imposer une phrase : ces marqueurs ne doivent
# apparaître dans aucun champ de `JobProgress`.
SPEECH_MARKERS = ("speech", "speak", "text", "priority", "utterance", "say")


class FrozenClock:
    """Horloge de test immobile, sauf ordre explicite.

    Immobile par défaut : c'est ce qui rend l'étranglement observable sans
    faire dormir le test.
    """

    def __init__(self) -> None:
        self.value = utc_now()

    def now(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


@dataclass(slots=True)
class RecordingSink:
    events: list[tuple[str, str, dict]] = field(default_factory=list)

    def emit(self, kind: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        self.events.append((kind, level, dict(data or {})))

    def kinds(self) -> list[str]:
        return [kind for kind, _level, _data in self.events]


@dataclass(slots=True)
class ReportingWorker:
    """Worker représentatif : il constate, il ne parle pas."""

    steps: tuple[JobProgress, ...] = ()
    seen_job_ids: list[str] = field(default_factory=list)

    async def execute_with_progress(self, job: Job, progress) -> dict[str, object]:
        self.seen_job_ids.append(job.id)
        for step in self.steps:
            await progress.emit(job.id, step)
        return {"ok": True}

    async def cancel(self, job_id: str) -> None:
        del job_id


@dataclass(slots=True)
class ChattyWorker:
    """Worker qui rapporte beaucoup trop, pour éprouver la borne du bus."""

    count: int = 1000

    async def execute_with_progress(self, job: Job, progress) -> dict[str, object]:
        for index in range(self.count):
            await progress.emit(job.id, JobProgress(phase=f"step-{index}", public_summary="Analyse en cours"))
        return {"ok": True}

    async def cancel(self, job_id: str) -> None:
        del job_id


@dataclass(slots=True)
class LegacyWorker:
    """Worker d'avant la couture : il ne doit rien avoir à changer."""

    calls: list[str] = field(default_factory=list)

    async def execute(self, job: Job) -> dict[str, object]:
        self.calls.append(job.id)
        return {"legacy": True}

    async def cancel(self, job_id: str) -> None:
        del job_id


async def build_jobs(tmp_path, workers, *, clock=None, diagnostics=None, min_interval_s=None):
    state = SQLiteStateRepository(tmp_path / "state" / "jarvis.sqlite3")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    conversation = await conversations.create()
    events = CoreEventBus(diagnostics=diagnostics)
    jobs = JobService(
        state,
        events,
        workers,
        clock=clock,
        diagnostics=diagnostics,
        progress_min_interval_s=min_interval_s,
    )
    return jobs, events, state, conversation.id


def drain(queue: asyncio.Queue[ProtocolEnvelope]) -> list[ProtocolEnvelope]:
    collected: list[ProtocolEnvelope] = []
    while True:
        try:
            collected.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return collected


async def wait_settled(jobs: JobService, state: SQLiteStateRepository, job_id: str) -> Job:
    """Attendre qu'un job soit sorti de la table des tâches en vol."""

    async def loop() -> Job:
        while True:
            found = [job for job in await state.list_jobs() if job.id == job_id]
            if found and found[0].status is not JobStatus.PENDING and found[0].status is not JobStatus.RUNNING:
                return found[0]
            await asyncio.sleep(0)

    return await asyncio.wait_for(loop(), timeout=5)


# --- le contrat du worker ----------------------------------------------------


def test_job_progress_carries_no_way_to_decide_speech():
    """Spec §13 : « Workers must not directly decide what Jarvis says. »"""

    for name in (f.name for f in dataclasses.fields(JobProgress)):
        lowered = name.lower()
        assert not any(marker in lowered for marker in SPEECH_MARKERS), name
    assert set(JobProgress().to_payload()) == {"phase", "fraction", "public_summary"}


def test_job_progress_refuses_an_impossible_fraction():
    with pytest.raises(ValueError):
        JobProgress(fraction=1.5)
    with pytest.raises(ValueError):
        JobProgress(fraction=-0.1)


def test_a_plain_worker_is_not_mistaken_for_a_progress_reporting_one():
    """La détection est structurelle : `execute` seul ne suffit pas.

    Sans cette distinction, `JobService` appellerait `execute_with_progress`
    sur tous les workers historiques et les casserait d'un coup.
    """

    assert not isinstance(LegacyWorker(), ProgressReportingJobWorker)
    assert isinstance(ReportingWorker(), ProgressReportingJobWorker)
    # Pas d'`isinstance(..., JobWorker)` ici : `JobWorker` n'est volontairement
    # pas `@runtime_checkable`. Le decorateur marque dans ce depot une capacite
    # optionnelle detectee a l'execution, et `JobService` ne teste jamais le
    # port ordinaire — il resout le worker par `job.kind`. La preuve
    # comportementale que le worker historique reste valide est apportee par
    # `test_a_worker_without_the_capability_runs_unchanged`.


# --- publication -------------------------------------------------------------


async def test_worker_progress_becomes_a_documented_brain_work_progress(tmp_path):
    clock = FrozenClock()
    worker = ReportingWorker(
        steps=(
            JobProgress(phase="cross_checking_calendar", fraction=0.5, public_summary="Messages trouvés ; vérification des réunions"),
        )
    )
    jobs, events, state, conversation_id = await build_jobs(tmp_path, {"mail_search": worker}, clock=clock)
    queue = events.subscribe()

    job = await jobs.submit(
        Job(kind="mail_search", requested_by_conversation_id=conversation_id),
        work_id="work-1",
        correlation_id="corr-1",
    )
    await wait_settled(jobs, state, job.id)

    progress = [event for event in drain(queue) if event.message_type == BRAIN_WORK_PROGRESS]
    assert len(progress) == 1
    payload = progress[0].payload
    assert set(payload) == DOC_PROGRESS_KEYS
    assert payload["work_id"] == "work-1"
    assert payload["job_id"] == job.id
    assert payload["phase"] == "cross_checking_calendar"
    assert payload["fraction"] == 0.5
    assert payload["public_summary"] == "Messages trouvés ; vérification des réunions"
    assert progress[0].correlation_id == "corr-1"
    assert progress[0].conversation_id == conversation_id
    await state.close()


async def test_progress_never_produces_speech(tmp_path):
    """Le service publie un fait ; la décision de parler reste au cerveau."""

    clock = FrozenClock()
    worker = ReportingWorker(steps=(JobProgress(phase="scanning", public_summary="Lecture des messages"),))
    jobs, events, state, conversation_id = await build_jobs(tmp_path, {"mail_search": worker}, clock=clock)
    queue = events.subscribe()

    job = await jobs.submit(Job(kind="mail_search", requested_by_conversation_id=conversation_id))
    await wait_settled(jobs, state, job.id)

    published = {event.message_type for event in drain(queue)}
    assert BRAIN_WORK_PROGRESS in published
    assert "brain.speech.requested" not in published
    await state.close()


async def test_an_unlinked_job_still_gets_a_stable_work_id(tmp_path):
    """Un job du planificateur n'appartient à aucun tour : il reste identifiable."""

    clock = FrozenClock()
    worker = ReportingWorker(steps=(JobProgress(phase="scanning"),))
    jobs, events, state, _conversation_id = await build_jobs(tmp_path, {"maintenance": worker}, clock=clock)
    queue = events.subscribe()

    job = await jobs.submit(Job(kind="maintenance"))
    await wait_settled(jobs, state, job.id)

    progress = [event for event in drain(queue) if event.message_type == BRAIN_WORK_PROGRESS]
    assert progress[0].payload["work_id"] == f"job:{job.id}"
    await state.close()


async def test_a_worker_cannot_report_progress_for_another_job(tmp_path):
    """Un `job_id` étranger est une erreur de contrat, pas un événement à publier."""

    clock = FrozenClock()

    class ImpersonatingWorker:
        async def execute_with_progress(self, job: Job, progress) -> dict[str, object]:
            await progress.emit("un-autre-job", JobProgress(phase="scanning"))
            return {}

        async def cancel(self, job_id: str) -> None:
            del job_id

    jobs, events, state, _conversation_id = await build_jobs(tmp_path, {"mail_search": ImpersonatingWorker()}, clock=clock)
    queue = events.subscribe()

    job = await jobs.submit(Job(kind="mail_search"))
    settled = await wait_settled(jobs, state, job.id)

    assert settled.status is JobStatus.FAILED
    assert [event.message_type for event in drain(queue) if event.message_type == BRAIN_WORK_PROGRESS] == []
    await state.close()


async def test_a_worker_without_the_capability_runs_unchanged(tmp_path):
    """Les workers existants ne sont pas retouchés par la couture."""

    worker = LegacyWorker()
    jobs, events, state, _conversation_id = await build_jobs(tmp_path, {"memory_maintenance": worker})
    queue = events.subscribe()

    job = await jobs.submit(Job(kind="memory_maintenance"))
    settled = await wait_settled(jobs, state, job.id)

    assert settled.status is JobStatus.COMPLETED
    assert worker.calls == [job.id]
    assert [event.message_type for event in drain(queue) if event.message_type == BRAIN_WORK_PROGRESS] == []
    await state.close()


# --- contre-pression (Décision 25 / question ouverte n°6) --------------------


async def test_a_chatty_worker_cannot_evict_a_subscriber(tmp_path):
    """Mille progressions ne doivent pas faire disparaître la surface du flux.

    Le bus reste borné à 128 et continue d'évincer l'abonné saturé : c'est le
    débit qui est corrigé, à la source, et non la borne du bus.
    """

    clock = FrozenClock()
    jobs, events, state, conversation_id = await build_jobs(tmp_path, {"mail_search": ChattyWorker(count=1000)}, clock=clock)
    queue = events.subscribe()

    job = await jobs.submit(Job(kind="mail_search", requested_by_conversation_id=conversation_id), work_id="work-1")
    await wait_settled(jobs, state, job.id)

    assert events.subscriber_count == 1
    assert events.evicted_total == 0
    published = drain(queue)
    progress = [event for event in published if event.message_type == BRAIN_WORK_PROGRESS]
    # L'horloge n'avance pas : tout ce qui suit la première progression tombe
    # dans la même fenêtre, donc est coalescé.
    assert len(progress) == 1
    assert "job.completed" in {event.message_type for event in published}
    await state.close()


async def test_without_throttling_the_bounded_bus_would_drop_the_subscriber(tmp_path):
    """Contre-épreuve : c'est bien l'étranglement qui protège l'abonné.

    Ce test documente la raison d'être de la coalescence. Si un jour il cesse
    d'échouer à évincer, c'est que la borne du bus a bougé — et la Décision 25
    dit qu'elle ne doit pas bouger.
    """

    clock = FrozenClock()
    jobs, events, state, _conversation_id = await build_jobs(
        tmp_path, {"mail_search": ChattyWorker(count=1000)}, clock=clock, min_interval_s=0.0
    )
    events.subscribe()

    job = await jobs.submit(Job(kind="mail_search"))
    await wait_settled(jobs, state, job.id)

    assert events.evicted_total == 1
    assert events.subscriber_count == 0
    await state.close()


async def test_a_moving_clock_lets_progress_through_again(tmp_path):
    """L'étranglement est un débit, pas un plafond : le temps rouvre la fenêtre."""

    clock = FrozenClock()

    class PacedWorker:
        async def execute_with_progress(self, job: Job, progress) -> dict[str, object]:
            for index in range(3):
                await progress.emit(job.id, JobProgress(phase=f"step-{index}"))
                clock.advance(1.0)
            return {}

        async def cancel(self, job_id: str) -> None:
            del job_id

    jobs, events, state, _conversation_id = await build_jobs(tmp_path, {"mail_search": PacedWorker()}, clock=clock)
    queue = events.subscribe()

    job = await jobs.submit(Job(kind="mail_search"))
    await wait_settled(jobs, state, job.id)

    phases = [event.payload["phase"] for event in drain(queue) if event.message_type == BRAIN_WORK_PROGRESS]
    assert phases == ["step-0", "step-1", "step-2"]
    await state.close()


async def test_coalesced_progress_leaves_a_diagnostic_trace(tmp_path):
    """Une progression absorbée n'est pas une panne, mais elle doit être visible."""

    clock = FrozenClock()
    sink = RecordingSink()
    jobs, _events, state, _conversation_id = await build_jobs(
        tmp_path, {"mail_search": ChattyWorker(count=5)}, clock=clock, diagnostics=sink
    )

    job = await jobs.submit(Job(kind="mail_search"), work_id="work-1")
    await wait_settled(jobs, state, job.id)

    traces = [data for kind, _level, data in sink.events if kind == JOB_PROGRESS_COALESCED_KIND]
    assert len(traces) == 1
    assert traces[0]["published_total"] == 1
    assert traces[0]["coalesced_total"] == 4
    assert traces[0]["work_id"] == "work-1"
    await state.close()


async def test_a_quiet_worker_leaves_no_coalescing_trace(tmp_path):
    """Le canal de diagnostic ne doit pas devenir du bruit de fond."""

    clock = FrozenClock()
    sink = RecordingSink()
    worker = ReportingWorker(steps=(JobProgress(phase="scanning"),))
    jobs, _events, state, _conversation_id = await build_jobs(
        tmp_path, {"mail_search": worker}, clock=clock, diagnostics=sink
    )

    job = await jobs.submit(Job(kind="mail_search"))
    await wait_settled(jobs, state, job.id)

    assert JOB_PROGRESS_COALESCED_KIND not in sink.kinds()
    await state.close()
