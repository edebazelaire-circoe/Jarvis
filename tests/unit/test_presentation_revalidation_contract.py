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

from dataclasses import asdict

import pytest

from jarvis.adapters.control_center_brain import ControlCenterBrainBackend, _take_redit, _take_retired
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_services import ConversationService
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.domain.speech_presentation import semantic_text_spans
from jarvis.domain.voice_frontend import VoiceCorrelation
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


def test_the_redit_marker_is_never_spoken_and_every_named_id_reaches_core():
    pending = (BrainPendingReply(speech_id="speech-a", correlation_id="corr-1", kind="result", text="Il est midi.",
                                 work_id="work-a"),)
    answer = "[[jarvis:redit speech-a]]\n[[jarvis:redit forged]]\nIl est midi passé, et il fait beau."
    spoken, linked = _take_redit(answer, pending)
    # Reprise QA : tout identifiant nommé part vers Core, qui seul sait ce qu'il a
    # remis à ce tour, filtre et trace (`core.brain.revalidation_ignored`).
    assert spoken == "Il est midi passé, et il fait beau." and linked == ("speech-a", "forged")
    # Le marqueur de retrait de la Décision 47 reste honoré (non enseigné).
    kept, retired = _take_retired("[[jarvis:retire work-a]]\nD'accord.", pending)
    assert kept == "D'accord." and retired == ("work-a",)


# ------------------------------------------------------------ reprise QA S04


PENDING = (BrainPendingReply(speech_id="abc", correlation_id="c1", kind="result", text="Trois fenêtres."),)


@pytest.mark.parametrize("answer", [
    "Il y a trois fenêtres. [[jarvis:redit abc]]",           # P2 : en fin de ligne
    "Il y a trois fenêtres.\n[[jarvis:redit abc]].",          # P3 : suivi d'une ponctuation
    "Il y a [[jarvis:redit abc]] trois fenêtres.",           # au milieu d'une phrase
], ids=["inline", "trailing-punctuation", "mid-sentence"])
def test_a_redit_marker_is_never_spoken_wherever_it_stands(answer):
    spoken, linked = _take_redit(answer, PENDING)
    assert spoken == "Il y a trois fenêtres." and linked == ("abc",)


def test_a_retire_marker_is_stripped_inline_too():
    pending = (BrainPendingReply(speech_id="abc", correlation_id="c1", kind="result", text="x", work_id="w-1"),)
    spoken, retired = _take_retired("D'accord, on laisse tomber. [[jarvis:retire w-1]].", pending)
    assert spoken == "D'accord, on laisse tomber." and retired == ("w-1",)


class _Recorder:
    def __init__(self) -> None:
        self.events: list = []
        self.traces: list[tuple[str, dict]] = []

    async def emit(self, event) -> None:  # noqa: ANN001 - BrainEventSink
        self.events.append(event)

    def trace(self, kind, message, *, level="info", data=None):  # noqa: ANN001
        del message, level
        self.traces.append((kind, data or {}))


def test_the_success_settlement_scrubs_any_leftover_marker_and_traces_it():
    backend = ControlCenterBrainBackend(base_url="http://127.0.0.1:1")
    recorder = _Recorder()

    class Sink:
        emit = staticmethod(recorder.trace)

    backend.attach_diagnostics(Sink())

    async def ask(text, context, conversation=None):  # noqa: ANN001
        del text, context, conversation
        return {"ok": True, "text": "Il est midi. [[jarvis:oups x]] Et il fait beau."}

    backend._ask = ask
    turn = BrainTurnInput(conversation_id="c", text="Quelle heure ?")
    result = asyncio.run(backend._run(turn, None, None, recorder))
    [speech] = [event.speech for event in recorder.events if event.kind is BrainEventKind.SPEECH]
    assert "[[jarvis:" not in speech.text and "[[jarvis:" not in result.public_summary
    assert speech.text == "Il est midi. Et il fait beau."
    assert [(kind, data["count"]) for kind, data in recorder.traces] == [("core.brain.marker_scrubbed", 1)]


def test_a_mistyped_redit_id_reaches_core_which_traces_it(tmp_path):
    """P4 : l'identifiant mal recopié par l'agent n'est plus filtré en silence par l'adaptateur."""

    backend = ControlCenterBrainBackend(base_url="http://127.0.0.1:1")
    answers = {FIRST_QUESTION: OLD_ANSWER, SECOND_QUESTION: "[[jarvis:redit typo-id]]\nIl fait beau."}

    async def ask(text, context, conversation=None):  # noqa: ANN001
        del context, conversation
        return {"ok": True, "text": answers[text]}

    backend._ask = ask
    traces: list[tuple[str, dict]] = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
            del message, level
            traces.append((kind, data or {}))

    async def play(scene: Stage):
        scene.brain._diagnostics = Sink()
        await scene.turn(FIRST_QUESTION)
        await scene.turn(SECOND_QUESTION)
        return [data for kind, data in traces if kind == "core.brain.revalidation_ignored"]

    ignored = staged(tmp_path, backend, play)
    assert [(item["speech_id"], item["reason"]) for item in ignored] == [("typo-id", "not_handed_to_this_turn")]


async def test_a_chain_already_being_spoken_finishes_before_the_current_intent():
    """P5 : A1 dit, l'intention passe à l'époque 2, B' arrive : A2 passe avant B' — on ne
    coupe pas une phrase en deux (décision d'agent 0, reprise QA S04)."""

    selected = build_scheduler(FakeCore(), FakeVoiceSession())
    text = "First part.\n\nSecond part."
    chain = _past(text, kind=SpeechKind.RESULT, chunks=semantic_text_spans(text))
    selected.update_speech_context(context(CONVERSATION, "corr-1", epoch=1))
    selected._enqueue(chain)
    first = selected._pop_next()
    assert first is not None and first.text == "First part.\n\n"
    selected._attempted_ids.add(first.id)
    selected._chain_next[chain.id] = 1
    selected.update_speech_context(context(CONVERSATION, "corr-2", epoch=2))
    fresh = _current("Fresh answer.", kind=SpeechKind.RESULT, priority=SpeechPriority.HIGH)
    selected._enqueue(fresh)
    assert selected._pop_next().text == "Second part."
    assert selected._pop_next() == fresh


def test_a_durable_relay_without_work_id_is_tracked_and_handed(tmp_path):
    """M10 : un relais `result` sans `work_id` (Slice 03) est suivi par son `speech_id`."""

    relay = "Le sous-agent a fini : trois fichiers corrigés."

    async def play(scene: Stage):
        await scene.turn(FIRST_QUESTION)
        assert await scene.brain.announce_notice(relay, kind="result")
        await scene.turn(SECOND_QUESTION)

    brain = ScriptedBrain()
    staged(tmp_path, brain, play)
    [handed] = [reply for text, ctx in brain.contexts if text == SECOND_QUESTION for reply in ctx.pending_replies]
    assert handed.text == relay and handed.work_id is None


def test_a_second_turn_in_flight_does_not_re_hand_what_the_first_is_judging(tmp_path):
    """M21 : deux tours en vol ; la seconde remise n'inclut pas ce que le premier juge encore."""

    gate = asyncio.Event()

    class GatedBrain(ScriptedBrain):
        async def run_turn(self, turn, state, emit):  # noqa: ANN001
            if turn.text == SECOND_QUESTION:
                await gate.wait()
            return await super().run_turn(turn, state, emit)

    brain = GatedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]})

    async def play(scene: Stage):
        await scene.turn(FIRST_QUESTION)
        await scene.brain.submit(BrainTurnInput(conversation_id=scene.conversation_id, text=SECOND_QUESTION))
        while not brain.pending_texts(SECOND_QUESTION):
            await asyncio.sleep(0.005)
        await scene.brain.submit(BrainTurnInput(conversation_id=scene.conversation_id, text=THIRD_QUESTION))
        while not any(text == THIRD_QUESTION for text, _ in brain.contexts):
            await asyncio.sleep(0.005)
        gate.set()
        await scene.idle()

    staged(tmp_path, brain, play)
    assert brain.pending_texts(SECOND_QUESTION) == [OLD_ANSWER]
    assert brain.pending_texts(THIRD_QUESTION) == []


def test_a_selected_outcome_is_tracked_and_handed_like_any_formulation(tmp_path):
    """Reprise QA 4a : `select_outcome` publie hors `_emit_speech` ; il est suivi quand même."""

    async def play(scene: Stage):
        await scene.turn(FIRST_QUESTION)
        [outcome] = [item for item in (await scene.brain.outcomes.list(scene.conversation_id))["outcomes"]
                     if item["text"] == OLD_ANSWER][:1]
        selected = await scene.brain.select_outcome(scene.conversation_id, outcome["id"], "selection-1")
        await scene.turn(SECOND_QUESTION)
        return selected["speech"]["speech_id"]

    brain = ScriptedBrain({FIRST_QUESTION: [(OLD_ANSWER, SpeechKind.RESULT)]})
    selected_id = staged(tmp_path, brain, play)
    handed = [reply.speech_id for text, ctx in brain.contexts if text == SECOND_QUESTION for reply in ctx.pending_replies]
    assert selected_id in handed


def test_a_formulation_replaced_by_a_fresher_one_of_its_slot_is_not_handed_again(tmp_path):
    """Reprise QA 4b : accusé et analyse de calibration, puis une analyse plus fraîche du
    même emplacement après un changement d'intention ; l'ancienne n'est plus remise."""

    key = "calibration:session-1:rev-1"
    brain = ScriptedBrain(failing={SECOND_QUESTION})
    traces: list[tuple[str, dict]] = []

    class Sink:
        def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
            del message, level
            traces.append((kind, data or {}))

    async def play(scene: Stage):
        scene.brain._diagnostics = Sink()
        await scene.turn(FIRST_QUESTION)
        assert await scene.brain.announce_notice("Tes résultats arrivent, je les analyse.", kind="ack",
                                                 supersedes_key=key, ttl_s=15)
        assert await scene.brain.announce_notice("Analyse : le C est net.", kind="result", supersedes_key=key)
        await scene.turn(SECOND_QUESTION)          # échoue : l'analyse est rendue, pas jugée
        assert await scene.brain.announce_notice("Analyse révisée : le C et le V sont nets.", kind="result",
                                                 supersedes_key=key)
        await scene.turn(THIRD_QUESTION)

    staged(tmp_path, brain, play)
    assert brain.pending_texts(SECOND_QUESTION) == ["Analyse : le C est net."]
    assert "Analyse : le C est net." not in brain.pending_texts(THIRD_QUESTION)
    assert [data["reason"] for kind, data in traces if kind == "core.brain.presentation_untracked"] == ["superseded"]


async def test_dispatch_evidence_survives_a_ledger_reload(tmp_path):
    """Reprise QA 5 : après éviction ou redémarrage, la preuve de dispatch est relue du stockage."""

    state = SQLiteStateRepository(tmp_path / "state.db")
    await state.initialize()
    conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
    conversation = await conversations.create()
    try:
        ledger = VoiceLedgerService(conversations)
        await ledger.bind_session(conversation.id, "session-1")
        await ledger.register_speech(conversation.id, asdict(VoiceCorrelation("session-1", speech_id="speech-a",
                                                                               output_id="output-a")), "Il est midi.")
        await ledger.snapshot(conversation.id, checkpoint=True)
        restarted = VoiceLedgerService(conversations)
        assert await restarted.registered_speech_ids(conversation.id) == frozenset({"speech-a"})
    finally:
        await state.close()


# ------------------------------------------- suivi : traces réelles du cerveau


def test_a_handed_formulation_is_not_also_listed_as_already_said():
    """Traces réelles (10 tours) : « PAS DIT : A » suivi de « Déjà dit à l'utilisateur : A ».

    Le fait public reste dans l'état de Core (vérité intacte) ; seul le rendu du
    brief l'omet de la ligne « Déjà dit », pour ne pas contredire « PAS DIT ».
    """
    from jarvis.runtime.control_center import build_agent_brief

    reply = BrainPendingReply(speech_id="speech-a", correlation_id="corr-1", kind="result", text="Il est midi.")
    state = {"current_user_intent": "Et quel temps fait-il ?",
             "known_public_facts": ["Il est midi.", "Le rapport est prêt."]}
    brief = build_agent_brief({"addressing": "addressed", "state": state,
                               "pending_speech": [reply.to_payload()]}, "Et quel temps fait-il ?")
    [said] = [line for line in brief.splitlines() if line.startswith("Déjà dit à l'utilisateur")]
    assert "Le rapport est prêt." in said and "Il est midi." not in said
    [unsaid] = [line for line in brief.splitlines() if line.startswith("PAS DIT")]
    assert "« Il est midi. »" in unsaid
    assert state["known_public_facts"] == ["Il est midi.", "Le rapport est prêt."]  # la vérité n'est pas touchée
    # Sans formulation remise, le rendu est celui d'avant.
    plain = build_agent_brief({"addressing": "addressed", "state": state}, "Et quel temps fait-il ?")
    assert "Déjà dit à l'utilisateur : Il est midi. | Le rapport est prêt." in plain


@pytest.mark.parametrize("answer, expected", [
    ("Bonne soirée ! [[jarvis:redit abc]]", "Bonne soirée !"),
    ("Bon, c'est lancé : le rapport arrive.\n[[jarvis:redit abc]]", "Bon, c'est lancé : le rapport arrive."),
    ("C'est lancé : [[jarvis:redit abc]] le rapport arrive. Bonne soirée !",
     "C'est lancé : le rapport arrive. Bonne soirée !"),
], ids=["exclamation", "colon-other-line", "colon-same-line"])
def test_removing_a_marker_leaves_french_typography_elsewhere_untouched(answer, expected):
    spoken, linked = _take_redit(answer, PENDING)
    assert spoken == expected and linked == ("abc",)
