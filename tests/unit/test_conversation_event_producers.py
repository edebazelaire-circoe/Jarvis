"""Core producers of Conversation Events: user admission and Brain (Slice 03a).

Real Core (`JarvisCoreApplication`, SQLite state DB in tmp_path) with a scripted
backend: the store read back is the one production writes.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.core.conversation_event_emitter import (
    PRODUCER_BRAIN_OUTCOMES, PRODUCER_BRAIN_SERVICE, PRODUCER_VOICE_ADMISSION,
)
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_events import (
    ConversationEventType as T,
    TraceSource,
    derive_conversation_event_id,
    encode_conversation_event,
    reconstruct_conversation,
    to_event_time,
    trace_entry_matches,
)
from jarvis.domain.v2 import (
    AddressingDecision, BrainEvent, BrainEventKind, BrainRunStatus, BrainTurnInput, BrainTurnResult, BrainTurnSource,
    SpeechKind, SpeechRequest,
)
from jarvis.domain.voice_admission import VoiceTurnAdmissionRequest
from jarvis.domain.voice_event_codec import encode_voice_event
from jarvis.domain.voice_events import UserCommitSource, UserTranscriptCommitted, UserTurnOpened, VoiceActivitySource
from jarvis.domain.voice_frontend import VoiceCorrelation
from jarvis.domain.work_attention_prompt import WORK_ATTENTION_WAKE_PROMPT
from tests.fakes.conversation_events import wait_emitter_settled
from tests.fakes.voice_frontend import FakeVoiceFrontend


class Journal:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def emit(self, kind, message, *, level="info", data=None):
        self.entries.append({"kind": kind, "level": level, "data": dict(data or {})})

    def of(self, kind):
        return [entry for entry in self.entries if entry["kind"] == kind]


class ScriptBackend:
    """Runs `script(turn, emit)` for each turn; the script's return is the result."""

    def __init__(self, script=None) -> None:
        self.script = script
        self.enqueued_at_start: list[int] = []
        self.core: JarvisCoreApplication | None = None

    async def run_turn(self, turn, state, emit):
        if self.core is not None:
            self.enqueued_at_start.append(self.core.conversation_event_emitter.counters.enqueued)
        if self.script is None:
            return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.COMPLETED)
        return await self.script(turn, emit)


async def start_core(tmp_path, backend=None, journal=None) -> JarvisCoreApplication:
    core = JarvisCoreApplication(data_root=tmp_path, brain_backend=backend, diagnostics=journal)
    if isinstance(backend, ScriptBackend):
        backend.core = core
    await core.start()
    return core


async def settle(core: JarvisCoreApplication) -> None:
    await asyncio.wait_for(asyncio.gather(*tuple(core.brain._tasks.values()), return_exceptions=True), 5)
    await wait_emitter_settled(core.conversation_event_emitter)


async def stored(core: JarvisCoreApplication, conversation_id: str):
    page = await core.conversation_events.list_conversation_events(conversation_id, limit=500)
    assert page.skipped_rows == 0
    return [item.event for item in page.events]


def of_type(events, event_type):
    return [event for event in events if event.event_type is event_type]


async def test_submitted_turn_is_recorded_before_the_backend_runs(tmp_path):
    backend = ScriptBackend()
    core = await start_core(tmp_path, backend)
    try:
        conversation = await core.conversations.create()
        turn = BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-1", text="Quelle heure est-il ?",
                              source=BrainTurnSource.TEXT, addressing=AddressingDecision.UNCERTAIN)
        acceptance = await core.brain.submit(turn)
        await settle(core)
        # Enqueued synchronously inside submit(), before the backend task ran.
        assert backend.enqueued_at_start == [2]
        events = await stored(core, conversation.id)
        user, accepted = of_type(events, T.USER_TRANSCRIPT_ACCEPTED), of_type(events, T.BRAIN_TURN_ACCEPTED)
        assert len(user) == 1 and len(accepted) == 1
        record = await core.state.get_turn(acceptance.turn_id)
        user = user[0]
        assert user.event_id == derive_conversation_event_id(
            producer=PRODUCER_VOICE_ADMISSION, event_type=T.USER_TRANSCRIPT_ACCEPTED,
            conversation_id=conversation.id, source_ids=(acceptance.turn_id,))
        assert (user.producer, user.content, user.correlation_id, user.turn_id, user.session_id) == (
            PRODUCER_VOICE_ADMISSION, "Quelle heure est-il ?", "corr-1", acceptance.turn_id, None)
        assert user.occurred_at == to_event_time(record.created_at)
        assert dict(user.attributes) == {"source": "text", "addressing": "uncertain"}
        assert user.trace_ref is None  # user entries have no diagnostic drill-down
        accepted = accepted[0]
        assert (accepted.producer, accepted.turn_id, accepted.correlation_id, accepted.content) == (
            PRODUCER_BRAIN_SERVICE, acceptance.turn_id, "corr-1", None)
        assert dict(accepted.attributes) == {"source": "text", "addressing": "uncertain", "revision": acceptance.revision}
        assert [event.event_type for event in events][:2] == [T.USER_TRANSCRIPT_ACCEPTED, T.BRAIN_TURN_ACCEPTED]
    finally:
        await core.stop()


async def test_duplicate_submissions_and_durable_replays_emit_nothing_new(tmp_path):
    turn_text = "Rappelle-moi demain."
    core = await start_core(tmp_path, ScriptBackend())
    try:
        conversation = await core.conversations.create()
        turn = BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-dup", text=turn_text)
        await core.brain.submit(turn)
        await settle(core)
        before = core.conversation_event_emitter.counters.enqueued
        again = await core.brain.submit(turn)  # in-memory duplicate
        assert again.duplicate is True
        await settle(core)
        assert core.conversation_event_emitter.counters.enqueued == before
    finally:
        await core.stop()
    # After a Core restart the replay is a durable duplicate: executed again
    # (historical ingress), but neither the user input nor the acceptance is a new fact.
    core = await start_core(tmp_path, ScriptBackend())
    try:
        await wait_emitter_settled(core.conversation_event_emitter)
        counters = core.conversation_event_emitter.counters
        # start-up backfill re-recorded the recent user turn: identical, so a duplicate
        assert (counters.enqueued, counters.duplicates, counters.conflicts) == (1, 1, 0)
        replay = await core.brain.submit(turn)
        await settle(core)
        events = await stored(core, conversation.id)
        assert len(of_type(events, T.USER_TRANSCRIPT_ACCEPTED)) == 1
        assert len(of_type(events, T.BRAIN_TURN_ACCEPTED)) == 1
        # the durable replay itself records nothing, not even an identical re-emission
        assert (counters.enqueued, counters.duplicates, counters.conflicts) == (1, 1, 0)
        assert replay.turn_id == events[0].turn_id
    finally:
        await core.stop()


async def test_core_opened_wake_turn_is_not_user_speech_and_its_prompt_never_stored(tmp_path):
    core = await start_core(tmp_path, ScriptBackend())
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="wake-1",
                                               text=WORK_ATTENTION_WAKE_PROMPT, source=BrainTurnSource.SYSTEM))
        await settle(core)
        events = await stored(core, conversation.id)
        assert of_type(events, T.USER_TRANSCRIPT_ACCEPTED) == []
        assert [dict(e.attributes)["source"] for e in of_type(events, T.BRAIN_TURN_ACCEPTED)] == ["system"]
        dumped = json.dumps([encode_conversation_event(event) for event in events], ensure_ascii=False)
        assert WORK_ATTENTION_WAKE_PROMPT[:40] not in dumped
    finally:
        await core.stop()


async def admitted_request(core, *, item="a", text="Une question exacte."):
    conversation_id = (await core.conversations.create()).id
    await core.voice_ledger.bind_session(conversation_id, "session-a")
    source = FakeVoiceFrontend()
    correlation = VoiceCorrelation("session-a", turn_id="canonical-" + item, provider_input_id="item-" + item)
    await core.voice_ledger.ingest(conversation_id, "session-a", [
        encode_voice_event(source.event(UserTurnOpened(None, VoiceActivitySource.PROVIDER), correlation=correlation)),
        encode_voice_event(source.event(UserTranscriptCommitted("transcript-" + item, text, 1, UserCommitSource.PROVIDER),
                                        correlation=correlation)),
    ])
    return VoiceTurnAdmissionRequest(conversation_id=conversation_id, text=text, addressing=AddressingDecision.ADDRESSED,
                                     session_id="session-a", canonical_turn_id=correlation.turn_id,
                                     transcript_id="transcript-" + item, transcript_revision=1,
                                     provider_item_id=correlation.provider_input_id)


async def test_direct_voice_admission_records_one_user_event_with_its_session(tmp_path):
    core = await start_core(tmp_path, ScriptBackend())
    try:
        request = await admitted_request(core)
        first = await core.voice_admission.admit_voice_turn(request)
        second = await core.voice_admission.admit_voice_turn(request)
        assert second.duplicate is True
        await wait_emitter_settled(core.conversation_event_emitter)
        events = await stored(core, request.conversation_id)
        assert [event.event_type for event in events] == [T.USER_TRANSCRIPT_ACCEPTED]  # no execution, no brain event
        user = events[0]
        assert (user.session_id, user.turn_id, user.correlation_id, user.content) == (
            "session-a", first.turn_id, first.correlation_id, "Une question exacte.")
        assert dict(user.attributes) == {"source": "realtime", "addressing": "addressed"}
        assert core.conversation_event_emitter.counters.enqueued == 1
    finally:
        await core.stop()


async def test_work_speech_and_outcomes_reconstruct_with_trace_joins_and_no_private_text(tmp_path):
    async def script(turn, emit):
        def event(kind, work_id=None, **fields):
            return BrainEvent(kind=kind, conversation_id=turn.conversation_id, correlation_id=turn.correlation_id,
                              work_id=work_id, **fields)
        await emit.emit(event(BrainEventKind.ACCEPTED, "work-1", public_summary="Je lis le dossier"))
        await emit.emit(event(BrainEventKind.COMPLETED, "work-1", public_summary="Dossier lu"))
        await emit.emit(event(BrainEventKind.ACCEPTED, "work-2"))
        await emit.emit(event(BrainEventKind.FAILED, "work-2", error="PRIVATE provider said org 42 over quota"))
        await emit.emit(event(BrainEventKind.ACCEPTED, "work-3"))
        await emit.emit(event(BrainEventKind.CANCELLED, "work-3"))
        await emit.emit(event(BrainEventKind.SPEECH, speech=SpeechRequest(
            conversation_id=turn.conversation_id, correlation_id=turn.correlation_id, text="Voici le résumé.",
            kind=SpeechKind.RESULT, work_id="work-1")))
        # work-4: its result is spoken first, then confirmed by COMPLETED with the
        # same text -> one outcome whose kind matures (speech_result -> work_result).
        await emit.emit(event(BrainEventKind.ACCEPTED, "work-4"))
        await emit.emit(event(BrainEventKind.SPEECH, speech=SpeechRequest(
            conversation_id=turn.conversation_id, correlation_id=turn.correlation_id, text="Quatre est fini.",
            kind=SpeechKind.RESULT, work_id="work-4")))
        await emit.emit(event(BrainEventKind.COMPLETED, "work-4", public_summary="Quatre est fini."))
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Résumé livré.")

    journal = Journal()
    core = await start_core(tmp_path, ScriptBackend(script), journal)
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-w", text="Lis le dossier."))
        await settle(core)
        events = await stored(core, conversation.id)
        types = [event.event_type for event in events]
        for expected in (T.BRAIN_WORK_STARTED, T.BRAIN_WORK_COMPLETED, T.BRAIN_WORK_FAILED, T.BRAIN_WORK_CANCELLED,
                         T.BRAIN_SPEECH_REQUESTED, T.BRAIN_MESSAGE_PUBLISHED):
            assert expected in types, expected
        dumped = json.dumps([encode_conversation_event(event) for event in events], ensure_ascii=False)
        assert "PRIVATE" not in dumped and "quota" not in dumped
        failed = of_type(events, T.BRAIN_WORK_FAILED)[0]
        assert "error_class" not in failed.attributes  # a sentence is never an error_class
        started = of_type(events, T.BRAIN_WORK_STARTED)
        assert [e.content for e in started] == ["Je lis le dossier", None, None, None]
        speech = of_type(events, T.BRAIN_SPEECH_REQUESTED)[0]
        assert (speech.content, speech.work_id) == ("Voici le résumé.", "work-1")
        assert speech.outcome_id is not None
        messages = of_type(events, T.BRAIN_MESSAGE_PUBLISHED)
        assert {m.producer for m in messages} == {PRODUCER_BRAIN_OUTCOMES}
        assert {m.content for m in messages} >= {"Voici le résumé.", "Résumé livré.", "Dossier lu"}
        assert speech.outcome_id in {m.outcome_id for m in messages}
        matured = [m for m in messages if m.content == "Quatre est fini."]
        assert len(matured) == 1  # the maturation is not a second message
        retained = [line for line in journal.of("core.brain.outcome_retained")
                    if line["data"]["outcome_id"] == matured[0].outcome_id]
        maturation = [line for line in journal.of("core.brain.outcome_matured")
                      if line["data"]["outcome_id"] == matured[0].outcome_id]
        assert [line["data"]["kind"] for line in retained + maturation] == ["speech_result", "work_result"]
        assert maturation[0]["data"]["conversation_event_id"] == matured[0].event_id

        items = {(item.event_type, item.span_id): item for item in reconstruct_conversation(events)}
        assert items[(T.BRAIN_WORK_STARTED, "work-1")].status == "completed"
        assert items[(T.BRAIN_WORK_STARTED, "work-2")].status == "failed"
        assert items[(T.BRAIN_WORK_STARTED, "work-3")].status == "cancelled"
        assert all(not item.anomalies for item in items.values())
        user_text = [item.text for item in reconstruct_conversation(events, include_diagnostic=False)]
        assert user_text[0] == "Lis le dossier."

        # Every event with a journal trace_ref joins exactly its own journal line.
        lines = [{"kind": entry["kind"], "data": entry["data"]} for entry in journal.entries]
        for event in events:
            if event.trace_ref is None:
                continue
            assert event.trace_ref.source is TraceSource.RUNTIME_JOURNAL
            matches = [line for line in lines if trace_entry_matches(event, line)]
            assert len(matches) == 1, (event.event_type, len(matches))
            assert matches[0]["data"].get("conversation_event_id") == event.event_id, event.event_type
        assert len(journal.of("core.brain.backend_task_started")) == 4
        assert {e.trace_ref.journal_kind for e in events if e.trace_ref} == {
            "core.brain.backend_task_started", "core.brain.backend_task_result", "core.brain.work_cancelled",
            "core.brain.outcome_retained"}
    finally:
        await core.stop()


@pytest.mark.parametrize(("mode", "code", "error_class"), [
    ("raise", "brain_backend_exception", "RuntimeError"),
    ("raise_odd_class", "brain_backend_exception", None),
    ("failed_sentence", "brain_backend_failed", None),
    ("failed_token", "brain_backend_failed", "claude_handover"),
    ("mismatch", "backend_correlation_mismatch", None),
])
async def test_turn_failure_records_codes_only(tmp_path, mode, code, error_class):
    async def script(turn, emit):
        await emit.emit(BrainEvent(kind=BrainEventKind.ACCEPTED, conversation_id=turn.conversation_id,
                                   correlation_id=turn.correlation_id, work_id="orphan"))
        if mode == "raise":
            raise RuntimeError("PRIVATE api key sk-123 rejected")
        if mode == "raise_odd_class":
            raise type("Ünïcode PRIVATE error with spaces", (Exception,), {})("boom")
        if mode == "mismatch":
            return BrainTurnResult(correlation_id="someone-else", status=BrainRunStatus.COMPLETED)
        error = "claude_handover" if mode == "failed_token" else "PRIVATE upstream said no"
        return BrainTurnResult(correlation_id=turn.correlation_id, status=BrainRunStatus.FAILED, error=error)

    journal = Journal()
    core = await start_core(tmp_path, ScriptBackend(script), journal)
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-f", text="Fais-le."))
        await settle(core)
        events = await stored(core, conversation.id)
        failed = of_type(events, T.BRAIN_TURN_FAILED)
        assert len(failed) == 1 and failed[0].content is None
        expected = {"code": code} if error_class is None else {"code": code, "error_class": error_class}
        assert dict(failed[0].attributes) == expected
        orphan = of_type(events, T.BRAIN_WORK_FAILED)
        assert [(e.work_id, e.attributes["code"]) for e in orphan] == [("orphan", "turn_failed")]
        assert "PRIVATE" not in json.dumps([encode_conversation_event(e) for e in events])
        lines = [{"kind": entry["kind"], "data": entry["data"]} for entry in journal.entries]
        assert [line["kind"] for line in lines if trace_entry_matches(failed[0], line)] == [failed[0].trace_ref.journal_kind]
    finally:
        await core.stop()


async def test_settlement_failure_is_a_system_failure_event(tmp_path, monkeypatch):
    async def script(turn, emit):
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="PRIVATE_TERMINAL")

    journal = Journal()
    core = await start_core(tmp_path, ScriptBackend(script), journal)
    try:
        conversation = await core.conversations.create()

        async def fail(value):
            raise OSError("PRIVATE_STORAGE")
        monkeypatch.setattr(core.state, "save_brain_outcome", fail)
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-s", text="Question"))
        await settle(core)
        events = await stored(core, conversation.id)
        failure = of_type(events, T.SYSTEM_FAILURE)
        assert len(failure) == 1
        assert dict(failure[0].attributes) == {"code": "brain_turn_settlement_failed", "error_class": "OSError"}
        assert of_type(events, T.BRAIN_MESSAGE_PUBLISHED) == []
        line = journal.of("core.brain.turn_settlement_failed")[0]
        assert line["data"]["conversation_event_id"] == failure[0].event_id
    finally:
        await core.stop()


async def test_selected_outcome_speech_joins_the_selection_journal_line(tmp_path):
    async def script(turn, emit):
        return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="Il fait beau.")

    journal = Journal()
    core = await start_core(tmp_path, ScriptBackend(script), journal)
    try:
        conversation = await core.conversations.create()
        await core.brain.submit(BrainTurnInput(conversation_id=conversation.id, correlation_id="corr-o", text="Météo ?"))
        await settle(core)
        outcome = (await core.outcomes.list(conversation.id))["outcomes"][0]
        await core.brain.select_outcome(conversation.id, outcome["id"], "selection-1")
        again = await core.brain.select_outcome(conversation.id, outcome["id"], "selection-1")
        assert again["duplicate"] is True
        await wait_emitter_settled(core.conversation_event_emitter)
        speech = of_type(await stored(core, conversation.id), T.BRAIN_SPEECH_REQUESTED)
        assert len(speech) == 1 and speech[0].outcome_id == outcome["id"] and speech[0].content == "Il fait beau."
        line = {"kind": "core.brain.outcome_selected", "data": journal.of("core.brain.outcome_selected")[0]["data"]}
        assert trace_entry_matches(speech[0], line)
    finally:
        await core.stop()


async def test_headless_core_without_store_wiring_records_nothing_and_keeps_behaviour(tmp_path):
    """A BrainOrchestrator built without an emitter (unit wiring) behaves exactly as before."""
    from jarvis.adapters.jsonl_history import JsonlHistoryStore
    from jarvis.adapters.sqlite_state import SQLiteStateRepository
    from jarvis.core.brain_service import BrainOrchestrator
    from jarvis.core.v2_services import ConversationService, CoreEventBus

    state = SQLiteStateRepository(tmp_path / "state.sqlite3")
    await state.initialize()
    try:
        conversations = ConversationService(state, JsonlHistoryStore(tmp_path / "history"))
        brain = BrainOrchestrator(conversations=conversations, events=CoreEventBus())
        conversation = await conversations.create()
        acceptance = await brain.submit(BrainTurnInput(conversation_id=conversation.id, text="Bonjour"))
        assert acceptance.duplicate is False
        await brain.stop()
    finally:
        await state.close()
