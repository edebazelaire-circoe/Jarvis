"""Présentation revalidée : contrat Core ↔ bouche (Slice 04, Décision 48).

Complète les juges de la Slice 01 (`test_speech_presentation_revalidation.py`,
T3–T5) par les points du contrat qu'ils ne couvrent pas
(`docs/conversation-events.md`, « Presentation revalidation ») :

- Core : la vérité n'est jamais touchée par une décision de présentation
  (outcomes, faits publics, travaux, dépendances, jobs) ; remise bornée
  (`pending_capacity`) ; parole tardive d'une corrélation dépassée remise au
  tour suivant ; lien de réémission honoré seulement pour ce qui a été remis à
  ce tour ; preuve de dispatch du registre vocal ;
- bouche : filet `held_for_brain_timeout` ; intention courante d'abord, une
  erreur garde son rang dans l'intention courante ; verdict d'une parole déjà
  tentée ignoré et dit ; chaîne remise par Core retenue ; évènements
  `mouth.speech.held` et `revalidated_as` joints au journal ;
- cerveau Control Center : rendu des formulations remises et marqueur
  `[[jarvis:redit <speech_id>]]`.
"""

from __future__ import annotations

import asyncio

from jarvis.adapters.control_center_brain import _take_redit, _take_retired
from jarvis.core.brain_service import BRAIN_PRESENTATION_HANDED, BRAIN_PRESENTATION_VERDICT
from jarvis.domain.brain_context import MAX_BRAIN_PENDING_REPLIES, BrainPendingReply
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.v2 import (
    BrainEvent,
    BrainEventKind,
    BrainTurnInput,
    BrainTurnResult,
    Job,
    JobStatus,
    ProtocolEnvelope,
    SpeechKind,
    SpeechPriority,
    SpeechRequest,
    utc_now,
)
from jarvis.runtime.control_center import render_pending_speech
from jarvis.runtime.speech_scheduler import SpeechScheduler
from tests.fakes.conversation_events import assert_each_trace_ref_joins_one_line, queued, recording_forwarder
from tests.fakes.speech_context import context, source
from tests.fakes.virtual_time_loop import VirtualWallClock, run_virtual
from tests.unit.test_speech_presentation_revalidation import (
    FIRST_QUESTION,
    OLD_ANSWER,
    SECOND_QUESTION,
    THIRD_QUESTION,
    HeldWorker,
    ScriptedBrain,
    Stage,
    a_stale_answer_waits_behind_a_busy_mouth,
    staged,
)
from tests.unit.test_v2_speech_scheduler import CONVERSATION, FakeCore, FakeVoiceSession, RecordingJournal, build_scheduler


class BusRecorder:
    """Les évènements `brain.presentation.*` que Core publie, dans l'ordre."""

    def __init__(self, scene: Stage) -> None:
        self.queue = scene.bus.subscribe()
        self.seen: list[ProtocolEnvelope] = []

    def of(self, message_type: str) -> list[dict]:
        while not self.queue.empty():
            self.seen.append(self.queue.get_nowait())
        return [envelope.payload for envelope in self.seen if envelope.message_type == message_type]


# ------------------------------------------------------------------- Core


def test_presentation_decisions_never_touch_truth_nor_work(tmp_path):
    """Invariant : retenir, remettre et solder une formulation ne change ni
    outcome, ni fait public, ni travail, ni dépendance, et n'annule aucun job
    (Décisions 15, 35)."""

    worker = HeldWorker()

    async def play(scene: Stage):
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        job = await scene.jobs.submit(Job(kind="report", requested_by_conversation_id=scene.conversation_id),
                                      work_id="report-work", correlation_id="report-corr")
        await scene.until(lambda: scene.retired_for(old, "not_revalidated"), what="A soldée not_revalidated")
        state = scene.brain.working_state(scene.conversation_id)
        outcomes = (await scene.brain.outcomes.list(scene.conversation_id))["outcomes"]
        invalidated = await scene.state.list_invalidated_brain_dependencies(scene.conversation_id)
        stored = await scene.state.get_job(job.id)
        worker.release.set()
        return state, outcomes, invalidated, stored.status, list(worker.cancelled)

    state, outcomes, invalidated, job_status, cancelled = staged(
        tmp_path, ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}), play,
        workers={"report": worker})
    assert OLD_ANSWER in state.known_public_facts
    assert OLD_ANSWER in [item["text"] for item in outcomes]
    assert list(invalidated) == []
    assert job_status == JobStatus.RUNNING and cancelled == []


def test_the_hand_over_is_bounded_and_the_oldest_beyond_are_not_revalidated(tmp_path):
    answers = [f"Réponse {index}." for index in range(MAX_BRAIN_PENDING_REPLIES + 1)]
    brain = ScriptedBrain({FIRST_QUESTION: [(text, SpeechKind.RESULT) for text in answers]})

    async def play(scene: Stage):
        bus = BusRecorder(scene)
        await scene.turn(FIRST_QUESTION)
        await scene.turn(SECOND_QUESTION)
        return bus.of(BRAIN_PRESENTATION_HANDED), bus.of(BRAIN_PRESENTATION_VERDICT), dict(scene.speech_texts)

    handed, verdicts, texts = staged(tmp_path, brain, play)
    assert [texts[item] for item in handed[0]["speech_ids"]] == answers[1:]
    assert brain.pending_texts(SECOND_QUESTION) == answers[1:]
    capacity = [item for payload in verdicts for item in payload["verdicts"] if item["reason"] == "pending_capacity"]
    assert [(texts[item["speech_id"]], item["verdict"]) for item in capacity] == [(answers[0], "not_revalidated")]


def test_a_late_speech_of_an_outdated_correlation_goes_to_the_next_turn(tmp_path):
    """Le cerveau en retard parle encore pour le tour N après l'activation de N+1 :
    la bouche la retient à l'arrivée, et Core la remet au tour qui commence ensuite."""

    gate = asyncio.Event()

    class LateBrain(ScriptedBrain):
        async def run_turn(self, turn, state, emit):  # noqa: ANN001
            if turn.text == FIRST_QUESTION:
                await gate.wait()
            return await super().run_turn(turn, state, emit)

    brain = LateBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]})

    async def play(scene: Stage):
        first = BrainTurnInput(conversation_id=scene.conversation_id, text=FIRST_QUESTION)
        await scene.brain.submit(first)
        await scene.brain.submit(BrainTurnInput(conversation_id=scene.conversation_id, text=SECOND_QUESTION))
        await asyncio.sleep(0.05)
        gate.set()
        await scene.idle()
        # Retenue dès l'arrivée : jamais « en file » (`voice.speech.queued`).
        await scene.until(lambda: any(scene.decisions(sid) for sid, text in scene.speech_texts.items()
                                      if text == OLD_ANSWER), what="A tardive reçue par la bouche")
        [late] = [sid for sid, text in scene.speech_texts.items() if text == OLD_ANSWER]
        held = scene.decisions(late)
        await scene.turn(THIRD_QUESTION)
        await scene.until(lambda: scene.retired_for(late, "not_revalidated"), what="verdict du tour suivant")
        return held, scene.spoken()

    held, spoken = staged(tmp_path, brain, play)
    assert ("deferred", "held_for_brain") in held and not any(status == "started" for status, _ in held)
    assert brain.pending_texts(SECOND_QUESTION) == []
    assert brain.pending_texts(THIRD_QUESTION) == [OLD_ANSWER]
    assert OLD_ANSWER not in spoken


def test_a_link_to_a_speech_not_handed_to_this_turn_is_ignored_and_traced(tmp_path):
    class ForgingBrain(ScriptedBrain):
        async def run_turn(self, turn, state, emit):  # noqa: ANN001
            if turn.text == SECOND_QUESTION:
                work_id = f"brain-turn:{turn.correlation_id}"
                await emit.emit(BrainEvent(
                    kind=BrainEventKind.SPEECH, conversation_id=turn.conversation_id,
                    correlation_id=turn.correlation_id, work_id=work_id, revalidates=("never-handed",),
                    speech=SpeechRequest(conversation_id=turn.conversation_id, text="Autre chose.",
                                         kind=SpeechKind.RESULT, work_id=work_id)))
                return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Autre chose.")
            return await super().run_turn(turn, state, emit)

    sink_events: list[tuple[str, dict]] = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
            del message, level
            sink_events.append((kind, data or {}))

    async def play(scene: Stage):
        scene.brain._diagnostics = Sink()
        old = await a_stale_answer_waits_behind_a_busy_mouth(scene)
        await scene.until(lambda: scene.retired_for(old, "not_revalidated"), what="A soldée")
        return scene.decisions(old)

    decisions = staged(tmp_path, ForgingBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]}), play)
    assert ("superseded", "not_revalidated") in decisions
    [ignored] = [data for kind, data in sink_events if kind == "core.brain.revalidation_ignored"]
    assert (ignored["speech_id"], ignored["reason"]) == ("never-handed", "not_handed_to_this_turn")


def test_a_formulation_the_voice_ledger_saw_dispatched_is_not_handed(tmp_path):
    """Preuve de dispatch (registre vocal) : la phrase a été dite, elle ne va pas au cerveau."""

    async def play(scene: Stage):
        bus = BusRecorder(scene)
        await scene.turn(FIRST_QUESTION)
        await scene.until(lambda: scene.queued(OLD_ANSWER), what="A reçue")
        [old] = scene.queued(OLD_ANSWER)

        class Ledger:
            async def registered_speech_ids(self, conversation_id):  # noqa: ANN001
                del conversation_id
                return frozenset({old})

        scene.brain._voice_ledger = Ledger()
        await scene.turn(SECOND_QUESTION)
        return bus.of(BRAIN_PRESENTATION_HANDED)

    brain = ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]})
    handed = staged(tmp_path, brain, play)
    assert handed == [] and brain.pending_texts(SECOND_QUESTION) == []


# ------------------------------------------------------------------ bouche


def _past(text: str, **kwargs) -> SpeechRequest:
    return SpeechRequest(CONVERSATION, text, correlation_id="corr-1", source=source("corr-1", epoch=1), **kwargs)


def _current(text: str, **kwargs) -> SpeechRequest:
    return SpeechRequest(CONVERSATION, text, correlation_id="corr-2", source=source("corr-2", epoch=2), **kwargs)


def test_a_held_formulation_without_verdict_expires_at_the_safety_net():
    async def scenario():
        loop = asyncio.get_running_loop()
        journal = RecordingJournal()
        scheduler = SpeechScheduler(core=FakeCore(), conversation_id=CONVERSATION, session=FakeVoiceSession(),
                                    journal=journal, clock=VirtualWallClock(loop, utc_now()), reconnect_delay_s=0.0,
                                    output_timeout_s=5.0, held_for_brain_max_s=30.0)
        await scheduler.start()
        await asyncio.sleep(0.1)  # abonnement établi : la source relue ne l'effacera plus
        scheduler.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
        try:
            old = _past("Il est midi.", kind=SpeechKind.RESULT)
            scheduler._enqueue(old)
            await asyncio.sleep(29.0)
            before = [(e["data"]["status"], e["data"]["reason"]) for e in journal.of("voice.speech.presentation_decided")]
            await asyncio.sleep(2.0)
            after = [(e["data"]["status"], e["data"]["reason"]) for e in journal.of("voice.speech.presentation_decided")]
            return before, after, journal.of("voice.speech.abandoned"), scheduler.session.texts()
        finally:
            await scheduler.stop()

    before, after, abandoned, spoken = run_virtual(scenario())
    assert before == [("deferred", "held_for_brain")]
    assert after[-1] == ("expired", "held_for_brain_timeout")
    assert [item["data"]["reason"] for item in abandoned] == ["held_for_brain_timeout"]
    assert spoken == []


async def test_the_current_intent_is_served_first_and_an_error_keeps_its_rank_inside_it():
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession())
    scheduler.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    normal = _current("Réponse.", kind=SpeechKind.RESULT)
    error = _current("Panne.", kind=SpeechKind.ERROR, priority=SpeechPriority.HIGH)
    scheduler._enqueue(normal)
    scheduler._enqueue(error)
    # Une parole d'une intention passée restée en file (défense : normalement retenue).
    stray = _past("Vieux.", kind=SpeechKind.ERROR, priority=SpeechPriority.IMMEDIATE)
    assert scheduler._select([stray, normal, error]) is error
    assert scheduler._select([stray, normal]) is normal
    assert scheduler._pop_next() == error and scheduler._pop_next() == normal


async def test_a_chain_handed_by_core_is_held_even_before_the_mouth_sees_it_as_past():
    journal = RecordingJournal()
    scheduler = build_scheduler(FakeCore(), FakeVoiceSession(), journal=journal)
    scheduler.update_speech_context(context(CONVERSATION, "corr-1", epoch=1))
    answer = _past("Il est midi.", kind=SpeechKind.RESULT)
    scheduler._enqueue(answer)
    await scheduler.handle_core_event(ProtocolEnvelope(message_type=BRAIN_PRESENTATION_HANDED, payload={
        "schema_version": 1, "conversation_id": CONVERSATION, "correlation_id": "corr-2", "speech_ids": [answer.id]}))
    assert scheduler._pop_next() is None
    assert scheduler.presentation_snapshot()["candidates"][0]["reason"] == "held_for_brain"


async def test_a_verdict_for_a_speech_already_attempted_changes_nothing_and_says_so():
    journal = RecordingJournal()
    session = FakeVoiceSession()
    scheduler = build_scheduler(FakeCore(), session, journal=journal)
    scheduler.update_speech_context(context(CONVERSATION, "corr-1", epoch=1))
    await scheduler.start()
    try:
        answer = _past("Il est midi.", kind=SpeechKind.RESULT)
        scheduler._enqueue(answer)
        while not session.texts():
            await asyncio.sleep(0.005)
        await scheduler.handle_core_event(ProtocolEnvelope(message_type=BRAIN_PRESENTATION_VERDICT, payload={
            "schema_version": 1, "conversation_id": CONVERSATION, "correlation_id": "corr-2",
            "verdicts": [{"speech_id": answer.id, "verdict": "not_revalidated", "revalidated_as": None,
                          "reason": "not_reemitted"}]}))
        [ignored] = journal.of("voice.speech.verdict_ignored")
        assert ignored["data"]["reason"] == "already_attempted"
        assert journal.of("voice.speech.superseded") == []
    finally:
        await scheduler.stop()


async def test_held_and_revalidated_as_are_conversation_events_joined_to_their_journal_lines():
    journal, forwarder = RecordingJournal(), recording_forwarder()
    scheduler = SpeechScheduler(core=FakeCore(), conversation_id=CONVERSATION, session=FakeVoiceSession(),
                                journal=journal, reconnect_delay_s=0.0, output_timeout_s=5.0,
                                conversation_events=forwarder)
    scheduler.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    old = _past("Il est midi.", kind=SpeechKind.RESULT)
    scheduler._enqueue(old)
    await scheduler.handle_core_event(ProtocolEnvelope(message_type=BRAIN_PRESENTATION_VERDICT, payload={
        "schema_version": 1, "conversation_id": CONVERSATION, "correlation_id": "corr-2",
        "verdicts": [{"speech_id": old.id, "verdict": "revalidated_as", "revalidated_as": "speech-new",
                      "reason": "reemitted"}]}))
    await scheduler.stop()
    events = [event for event in queued(forwarder) if event.speech_id == old.id]
    held = [event for event in events if event.event_type is T.MOUTH_SPEECH_HELD]
    superseded = [event for event in events if event.event_type is T.MOUTH_SPEECH_SUPERSEDED]
    assert [dict(event.attributes)["reason"] for event in held] == ["held_for_brain"]
    assert [(dict(event.attributes)["reason"], dict(event.attributes)["revalidated_as"]) for event in superseded] == [
        ("revalidated_as", "speech-new")]
    assert_each_trace_ref_joins_one_line(events, journal.events)


# ------------------------------------------------------ cerveau Control Center


def test_the_brief_asks_to_re_say_what_still_matters_and_to_name_it():
    reply = BrainPendingReply(speech_id="speech-a", correlation_id="corr-1", kind="result", text="Il est midi.")
    [line] = render_pending_speech([reply.to_payload()])
    assert "n'a pas été dite" in line and "Redis ce qui reste utile, reformulé" in line
    assert "sinon n'en dis rien" in line and line.endswith("[[jarvis:redit speech-a]]")
    # Un relais sans travail garde son identité de présentation.
    assert reply.to_payload()["work_id"] is None


def test_the_redit_marker_links_only_what_core_handed_and_is_never_spoken():
    pending = (BrainPendingReply(speech_id="speech-a", correlation_id="corr-1", kind="result", text="Il est midi.",
                                 work_id="work-a"),)
    answer = "[[jarvis:redit speech-a]]\n[[jarvis:redit forged]]\nIl est midi passé, et il fait beau."
    spoken, linked = _take_redit(answer, pending)
    assert spoken == "Il est midi passé, et il fait beau." and linked == ("speech-a",)
    # Le marqueur de retrait de la Décision 47 reste honoré (non enseigné).
    kept, retired = _take_retired("[[jarvis:retire work-a]]\nD'accord.", pending)
    assert kept == "D'accord." and retired == ("work-a",)
