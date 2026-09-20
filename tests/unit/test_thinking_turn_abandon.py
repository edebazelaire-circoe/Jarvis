"""Abandonner un tour du cerveau sans tuer ce qu'il a lancé (19/09/2026).

Couper JARVIS pendant qu'il réfléchit ne coupe aucune phrase : il n'en dit pas.
Ce qui doit s'arrêter est ailleurs — la tâche du tour, dans Core, et la parole
qu'elle avait déjà mise en file, dans l'ordonnanceur. Sans ces deux gestes,
l'interruption ne ferait que **taire** le cerveau : il continuerait de
travailler pour une question périmée, et répondrait plus tard, en travers de la
suivante.

Ce que ces tests fixent, dans les deux sens :

- l'abandon arrête bien la tâche du tour et retire de l'état public le travail
  que **ce tour** portait, pour qu'aucun écran ne reste occupé par un cerveau
  qui ne pense plus ;
- il ne touche à aucun job : sous-agents et travail de fond continuent
  (Décisions 15, 16 et 35). C'est la promesse faite à l'utilisateur — on
  interrompt une réponse, pas une tâche.
"""

from __future__ import annotations

import asyncio

from jarvis.core.brain_service import BRAIN_TURN_ABANDONED_KIND, BRAIN_TURN_CANCELLED_KIND
from jarvis.domain.speech_presentation import SpeechCandidateStatus
from jarvis.domain.v2 import BrainTurnInput, BrainTurnSource, SpeechKind
from tests.unit.test_v2_brain_orchestrator import RecordingSink, SlowBackend, build_orchestrator, wait_idle
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeCore, FakeVoiceSession, RecordingJournal, build_scheduler, busy_surface,
    speech_envelope,
)


class CountingJobs:
    """Annuleur de travail exécutable : il ne doit jamais être appelé ici."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def cancel_work(self, work_id: str) -> tuple[str, ...]:
        self.calls.append(work_id)
        return ()


# --------------------------------------------------------------------------
# 1. Core : la tâche du tour s'arrête, les jobs continuent


async def test_cancelling_a_turn_stops_its_task_and_leaves_the_jobs_running(tmp_path):
    backend, sink, jobs = SlowBackend(), RecordingSink(), CountingJobs()
    brain, _conversations, events, _state, conversation_id = await build_orchestrator(tmp_path, backend, sink)
    brain._jobs = jobs
    queue = events.subscribe()

    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Jarvis, prépare le rapport",
                                      correlation_id="corr-1", source=BrainTurnSource.REALTIME))
    await asyncio.wait_for(backend.started.wait(), timeout=5)

    result = await brain.cancel_turn(conversation_id, "corr-1")
    await wait_idle(brain)

    assert result["cancelled"] is True
    assert backend.cancelled == ["corr-1"]  # le backend a bien reçu son CancelledError
    assert brain.active_turn_count == 0
    # La promesse : rien de ce que le tour avait lancé n'est tué.
    assert jobs.calls == []
    kinds = sink.kinds()
    assert BRAIN_TURN_ABANDONED_KIND in kinds and BRAIN_TURN_CANCELLED_KIND in kinds
    abandoned = next(data for kind, _level, data in sink.events if kind == BRAIN_TURN_ABANDONED_KIND)
    assert abandoned["jobs_cancelled"] is False
    # Aucun échec publié : un tour abandonné n'est pas un tour en panne.
    published = []
    while not queue.empty():
        published.append(queue.get_nowait().message_type)
    assert "brain.work.failed" not in published
    assert "brain.speech.requested" not in published


async def test_cancelling_retires_only_the_work_that_turn_declared(tmp_path):
    """Sans cela, un tour sans réponse laisserait son travail actif pour toujours."""

    backend, sink = SlowBackend(), RecordingSink()
    brain, _conversations, _events, _state, conversation_id = await build_orchestrator(tmp_path, backend, sink)
    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Jarvis, prépare le rapport",
                                      correlation_id="corr-1", source=BrainTurnSource.REALTIME))
    await asyncio.wait_for(backend.started.wait(), timeout=5)
    # Le tour a déclaré son travail, et un autre tourne déjà pour un autre tour.
    brain._states[conversation_id] = brain._revise(conversation_id, active_work_ids=("work-du-tour", "work-de-fond"))
    brain._work_owners[(conversation_id, "work-du-tour")] = "corr-1"
    brain._work_owners[(conversation_id, "work-de-fond")] = "corr-precedente"

    result = await brain.cancel_turn(conversation_id, "corr-1")
    await wait_idle(brain)

    assert result["retired_work_ids"] == ["work-du-tour"]
    assert brain.working_state(conversation_id).active_work_ids == ("work-de-fond",)


async def test_cancelling_a_turn_that_already_finished_is_not_an_error(tmp_path):
    backend, sink = SlowBackend(), RecordingSink()
    brain, _conversations, _events, _state, conversation_id = await build_orchestrator(tmp_path, backend, sink)
    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Jarvis, prépare le rapport",
                                      correlation_id="corr-1", source=BrainTurnSource.REALTIME))
    await asyncio.wait_for(backend.started.wait(), timeout=5)
    backend.release.set()
    await wait_idle(brain)

    result = await brain.cancel_turn(conversation_id, "corr-1")

    assert result["cancelled"] is False and result["reason"] == "no_turn_in_flight"


async def test_a_turn_of_another_conversation_is_never_cancelled(tmp_path):
    backend, sink = SlowBackend(), RecordingSink()
    brain, _conversations, _events, _state, conversation_id = await build_orchestrator(tmp_path, backend, sink)
    await brain.submit(BrainTurnInput(conversation_id=conversation_id, text="Jarvis, prépare le rapport",
                                      correlation_id="corr-1", source=BrainTurnSource.REALTIME))
    await asyncio.wait_for(backend.started.wait(), timeout=5)

    result = await brain.cancel_turn("conv-etrangere", "corr-1")

    assert result["cancelled"] is False
    assert brain.active_turn_count == 1
    backend.release.set()
    await wait_idle(brain)


# --------------------------------------------------------------------------
# 2. Ordonnanceur : la file se purge, et Core est prévenu


class CancellingCore(FakeCore):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled: list[tuple[str, str]] = []

    async def cancel_brain_turn(self, conversation_id: str, *, correlation_id: str) -> dict[str, object]:
        self.cancelled.append((conversation_id, correlation_id))
        return {"cancelled": True, "correlation_id": correlation_id}


async def test_abandoning_a_turn_purges_its_queued_speech_and_tells_core():
    core, session, journal = CancellingCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await busy_surface(scheduler)  # le fournisseur est occupé : la file s'accumule
    await scheduler.handle_core_event(speech_envelope("Le rapport est prêt.", kind=SpeechKind.RESULT, correlation_id="corr-1"))
    assert scheduler.pending_count == 1

    assert await scheduler.abandon_turn("corr-1") is True

    assert scheduler.pending_count == 0
    assert core.cancelled == [(CONVERSATION, "corr-1")]
    assert journal.count("voice.speech.turn_abandoned") == 1
    assert journal.of("voice.speech.turn_abandoned")[-1]["data"]["core_cancelled"] is True


async def test_speech_written_just_before_the_interruption_is_never_spoken():
    """La course réelle : Core a déjà émis la parole quand l'utilisateur coupe.

    Elle traverse `/v1/events` après l'abandon. Sans la mémoire des corrélations
    abandonnées, elle serait prononcée par-dessus la nouvelle question.
    """

    core, session, journal = CancellingCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await busy_surface(scheduler)
    await scheduler.abandon_turn("corr-1")

    await scheduler.handle_core_event(speech_envelope("Le rapport est prêt.", kind=SpeechKind.RESULT, correlation_id="corr-1"))

    assert scheduler.pending_count == 0
    superseded = [event for event in journal.of("voice.speech.presentation_decided")
                  if event["data"]["reason"] == "turn_abandoned"]
    assert superseded and superseded[-1]["data"]["status"] == SpeechCandidateStatus.SUPERSEDED.value


async def test_a_core_that_cannot_cancel_still_gives_the_floor_back():
    """Panne de transport : la file est purgée quand même, et la trace le dit."""

    class BrokenCore(FakeCore):
        async def cancel_brain_turn(self, conversation_id: str, *, correlation_id: str):
            raise ConnectionError("core injoignable")

    core, session, journal = BrokenCore(), FakeVoiceSession(), RecordingJournal()
    scheduler = build_scheduler(core, session, journal=journal)
    await busy_surface(scheduler)
    await scheduler.handle_core_event(speech_envelope("Le rapport est prêt.", kind=SpeechKind.RESULT, correlation_id="corr-1"))

    assert await scheduler.abandon_turn("corr-1") is True

    assert scheduler.pending_count == 0
    trace = journal.of("voice.speech.turn_abandoned")[-1]
    assert trace["level"] == "warning" and "ConnectionError" in str(trace["data"]["error"])


async def test_abandoning_twice_or_without_a_turn_does_nothing():
    core, session = CancellingCore(), FakeVoiceSession()
    scheduler = build_scheduler(core, session)

    assert await scheduler.abandon_turn(None) is False
    assert await scheduler.abandon_turn("corr-1") is True
    assert await scheduler.abandon_turn("corr-1") is False
    assert core.cancelled == [(CONVERSATION, "corr-1")]
