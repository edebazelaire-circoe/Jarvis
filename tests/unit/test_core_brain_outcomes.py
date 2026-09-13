from __future__ import annotations

import asyncio
from dataclasses import replace
import json

import pytest

from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.brain_outcomes import BrainOutcomeService
from jarvis.core.v2_services import ConversationService, CoreEventBus
from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.domain.speech_presentation import BackendOutcome, OutcomeKind, OutcomeStatus, SpeechDependency, SpeechSource
from jarvis.domain.v2 import TurnKind, utc_now
from jarvis.runtime.journal import RuntimeJournal, read_jsonl_tail


@pytest.fixture
async def store(tmp_path):
    repository = SQLiteStateRepository(tmp_path / "state.sqlite")
    await repository.initialize()
    conversations = ConversationService(repository, JsonlHistoryStore(tmp_path / "history"))
    conversation = await conversations.create()
    journal = RuntimeJournal(tmp_path / "runtime")
    service = BrainOutcomeService(repository, CoreEventBus(), journal)
    try:
        yield repository, conversations, conversation.id, service, journal
    finally:
        await repository.close()


async def source_for(repository, conversations, conversation_id, correlation_id):
    turn = await conversations.append_turn(conversation_id, TurnKind.USER, "intent", correlation_id=correlation_id)
    return await repository.allocate_brain_source(conversation_id, turn.id, correlation_id)


async def test_source_epoch_order_is_durable_and_old_promotion_cannot_replace_current(store):
    repo, conversations, conv, service, _ = store
    old = await source_for(repo, conversations, conv, "old")
    current = await source_for(repo, conversations, conv, "current")
    assert await repo.activate_brain_source(conv, current)
    assert not await repo.activate_brain_source(conv, old)
    assert not await repo.activate_brain_source(conv, current)
    assert (await service.context(conv))["current_speech_source"] == current.to_payload()
    await repo.close()
    await repo.initialize()
    later = await source_for(repo, conversations, conv, "later")
    assert later.intent_epoch > current.intent_epoch > old.intent_epoch
    assert await repo.get_current_brain_source(conv) == current
    with pytest.raises(ValueError, match="unowned"):
        await repo.activate_brain_source(conv, replace(later, intent_epoch=later.intent_epoch + 1))


async def test_outcome_concurrent_dedup_kind_promotion_and_exact_terminal_versions(store):
    repo, conversations, conv, service, _ = store
    source = await source_for(repo, conversations, conv, "origin")
    arguments = dict(conversation_id=conv, correlation_id="origin", work_id="work", text=" Exact.\n\nText ")
    results = await asyncio.gather(*(service.retain(**arguments, kind=OutcomeKind.SPEECH_RESULT) for _ in range(12)))
    assert len({item.id for item in results}) == 1
    first = results[0]
    terminal = await service.retain(**arguments, kind=OutcomeKind.WORK_RESULT)
    assert terminal.id == first.id and terminal.created_at == first.created_at
    assert terminal.kind is OutcomeKind.WORK_RESULT
    assert terminal.source == replace(source, dependencies=(SpeechDependency("work", "origin"),))
    await service.retain(**arguments, kind=OutcomeKind.SPEECH_RESULT)
    changed = await service.retain(**{**arguments, "text": "Different terminal text"}, kind=OutcomeKind.WORK_RESULT)
    aggregate = await service.retain(**{**arguments, "work_id": None}, kind=OutcomeKind.TURN_RESULT)
    assert len({terminal.id, changed.id, aggregate.id}) == 3
    await repo.close()
    await repo.initialize()
    assert (await service.retain(**arguments, kind=OutcomeKind.SPEECH_RESULT)).kind is OutcomeKind.WORK_RESULT
    assert len((await service.list(conv))["outcomes"]) == 3
    for field, value in (("text", "conflict"), ("work_id", "other"), ("source", source), ("status", OutcomeStatus.FAILED)):
        with pytest.raises(ValueError, match="identity conflict"):
            await repo.save_brain_outcome(replace(terminal, **{field: value}))


async def test_dependency_generation_and_saturation_are_conservative(store):
    repo, conversations, conv, service, _ = store
    current = await source_for(repo, conversations, conv, "current")
    await repo.activate_brain_source(conv, current)
    await repo.invalidate_brain_dependency(conv, SpeechDependency("reused", "old"))
    context = await service.context(conv)
    assert context["source_complete"]
    assert SpeechDependency("reused", "current").to_payload() not in context["invalidated_dependencies"]
    for index in range(256):
        await repo.invalidate_brain_dependency(conv, SpeechDependency(f"work-{index}", "old"))
    context = await service.context(conv)
    assert not context["source_complete"] and len(context["invalidated_dependencies"]) == 256
    assert context["current_speech_source"] == current.to_payload()
    context["current_speech_source"]["intent_epoch"] = -1
    context["invalidated_dependencies"].clear()
    assert (await service.context(conv))["current_speech_source"] == current.to_payload()


async def test_real_journal_persistence_failure_is_private_and_retry_is_observable(store, monkeypatch):
    repo, _, conv, service, journal = store
    original = repo.save_brain_outcome
    async def failure(value):
        raise OSError("PRIVATE_STORAGE_DETAIL")
    monkeypatch.setattr(repo, "save_brain_outcome", failure)
    with pytest.raises(OSError):
        await service.retain(conversation_id=conv, correlation_id="origin", work_id=None,
                             text="PRIVATE_UNHEARD_RESULT", kind=OutcomeKind.TURN_RESULT)
    monkeypatch.setattr(repo, "save_brain_outcome", original)
    await service.retain(conversation_id=conv, correlation_id="origin", work_id=None,
                         text="PRIVATE_UNHEARD_RESULT", kind=OutcomeKind.TURN_RESULT)
    rows = read_jsonl_tail(journal.trace_path)
    assert [row["kind"] for row in rows] == ["core.brain.outcome_persistence_failed", "core.brain.outcome_retained"]
    assert "PRIVATE_" not in json.dumps(rows)
    assert read_jsonl_tail(journal.error_path)[0]["data"]["code"] == "brain_outcome_persistence_failed"


async def test_owned_turn_observes_terminal_persistence_failure_without_false_publication(store, monkeypatch):
    from jarvis.core.brain_service import BrainOrchestrator
    from jarvis.domain.v2 import BrainTurnInput, BrainTurnResult

    repo, conversations, conv, _, journal = store
    class SummaryBackend:
        async def run_turn(self, turn, state, emit):
            return BrainTurnResult(correlation_id=turn.correlation_id, public_summary="PRIVATE_TERMINAL")
    events = CoreEventBus()
    brain = BrainOrchestrator(conversations=conversations, events=events, backend=SummaryBackend(), diagnostics=journal)
    queue = events.subscribe()
    async def fail(value):
        raise OSError("PRIVATE_STORAGE")
    monkeypatch.setattr(repo, "save_brain_outcome", fail)
    turn = BrainTurnInput(conversation_id=conv, correlation_id="terminal", text="request")
    await brain.submit(turn)
    task = brain._tasks[turn.correlation_id]
    await asyncio.wait_for(task, 1)
    assert task.exception() is None and brain.active_turn_count == 0
    published = []
    while not queue.empty():
        published.append(queue.get_nowait().message_type)
    assert "brain.outcome.available" not in published and "brain.speech.requested" not in published
    errors = read_jsonl_tail(journal.error_path)
    assert [row["data"]["code"] for row in errors] == ["brain_outcome_persistence_failed", "brain_turn_settlement_failed"]
    assert "PRIVATE_" not in json.dumps(read_jsonl_tail(journal.trace_path))


@pytest.mark.parametrize("case", ["single_oversized", "semantic_long", "too_many_parts"])
async def test_real_control_center_backend_retains_long_unpresentable_result(store, case):
    from aiohttp import web
    from jarvis.core.brain_service import BrainOrchestrator
    from jarvis.domain.v2 import BrainTurnInput
    from tests.unit.test_v2_brain_migration import serve_agent

    repo, conversations, conv, _, journal = store
    paragraph = ("Résultat exact sans frontière de paragraphe. " * 150).rstrip()
    answer = {"single_oversized": paragraph * 2, "semantic_long": paragraph + "\n\n" + paragraph,
              "too_many_parts": "\n\n".join(f"Résultat paragraphe {index}" for index in range(17))}[case]
    assert len(answer) <= 65536
    if case != "too_many_parts":
        assert len(answer) > 8192
    async def handler(request):
        return web.json_response({"ok": True, "text": answer, "duration_ms": 1})
    backend, runner = await serve_agent(handler)
    events = CoreEventBus()
    brain = BrainOrchestrator(conversations=conversations, events=events, backend=backend, diagnostics=journal)
    queue = events.subscribe()
    try:
        turn = BrainTurnInput(conversation_id=conv, correlation_id="long-result", text="Retrieve the complete result")
        await brain.submit(turn)
        await asyncio.wait_for(brain._tasks[turn.correlation_id], 2)
        outcomes = (await brain.outcomes.list(conv))["outcomes"]
        assert outcomes and all(outcome["text"] == answer for outcome in outcomes)
        assert all(outcome["status"] == "completed" for outcome in outcomes)
        published = []
        while not queue.empty():
            published.append(queue.get_nowait())
        kinds = [event.message_type for event in published]
        assert "brain.work.completed" in kinds and "brain.outcome.available" in kinds
        assert "brain.work.failed" not in kinds
        speeches = [event.payload for event in published if event.message_type == "brain.speech.requested"]
        if case == "semantic_long":
            assert len(speeches) == 1 and speeches[0]["text"] == answer
            spans = speeches[0]["chunks"]
            assert len(spans) == 2 and all(span["end"] - span["start"] <= 8192 for span in spans)
            assert "".join(answer[span["start"]:span["end"]] for span in spans) == answer
        else:
            assert speeches == []
        assert all(turn.kind is TurnKind.USER for turn in await repo.list_turns(conv))
        await repo.close()
        await repo.initialize()
        assert all(outcome.text == answer for outcome in await repo.list_brain_outcomes(conv))
    finally:
        await brain.stop()
        await backend.close()
        await runner.cleanup()


@pytest.mark.parametrize("limit", [0, 129, True, 1.2, "32"])
async def test_outcome_list_rejects_non_integer_and_unbounded_limits(store, limit):
    _, _, conv, service, _ = store
    with pytest.raises(ValueError):
        await service.list(conv, limit=limit)


@pytest.mark.parametrize("field,value", [("text", "x" * 65537), ("text", []), ("id", " bad "), ("kind", []),
                                        ("status", None), ("created_at", "2026-09-12"), ("extra", True)],
                         ids=["oversized", "nontext", "bad-id", "bad-kind", "bad-status", "naive-date", "extra-field"])
def test_outcome_json_schema_is_strict(field, value):
    outcome = BackendOutcome("id", "conversation", None, None, "text", utc_now(), OutcomeKind.TURN_RESULT, OutcomeStatus.COMPLETED)
    payload = outcome.to_payload()
    payload[field] = value
    with pytest.raises((ValueError, TypeError)):
        BackendOutcome.from_payload(payload)


@pytest.mark.parametrize("epoch", [float("nan"), float("inf"), True, 1.5, -1, 2**63])
def test_source_json_refuses_invalid_epoch(epoch):
    payload = SpeechSource("turn", "corr", "intent", 1).to_payload()
    payload["intent_epoch"] = epoch
    with pytest.raises(ValueError):
        SpeechSource.from_payload(payload)


async def test_reused_work_id_keeps_old_invalidation_and_allows_new_generation(tmp_path):
    from tests.unit.test_v2_intent_revision import DrivenBackend, build_orchestrator, start_turn, work_event, speech_event, drain
    from jarvis.domain.v2 import BrainEventKind
    from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED

    backend = DrivenBackend()
    brain, events, repo, conv = await build_orchestrator(tmp_path, backend)
    try:
        old = await start_turn(brain, backend, conv, "first")
        old_sink = backend.sink
        await old_sink.emit(work_event(BrainEventKind.ACCEPTED, conv, old.correlation_id, "reused"))
        await old_sink.emit(work_event(BrainEventKind.CANCELLED, conv, old.correlation_id, "reused"))
        backend.started.clear()
        current = await start_turn(brain, backend, conv, "second")
        await backend.emit(work_event(BrainEventKind.ACCEPTED, conv, current.correlation_id, "reused"))
        for kind in (BrainEventKind.ACCEPTED, BrainEventKind.PROGRESS, BrainEventKind.SUPERSEDED,
                     BrainEventKind.CANCELLED, BrainEventKind.COMPLETED):
            await old_sink.emit(work_event(kind, conv, old.correlation_id, "reused"))
            assert brain.working_state(conv).active_work_ids == ("reused",)
            assert brain._work_owners[(conv, "reused")] == current.correlation_id
        queue = events.subscribe()
        await old_sink.emit(speech_event(conv, old.correlation_id, work_id="reused", text="old result"))
        await backend.emit(speech_event(conv, current.correlation_id, work_id="reused", text="new result"))
        speeches = [event.payload for event in drain(queue) if event.message_type == BRAIN_SPEECH_REQUESTED]
        assert [speech["text"] for speech in speeches] == ["new result"]
        assert speeches[0]["source"]["dependencies"] == [SpeechDependency("reused", current.correlation_id).to_payload()]
        assert {outcome["text"] for outcome in (await brain.outcomes.list(conv))["outcomes"]} == {"old result", "new result", "Recherche des messages"}
        assert (await brain.speech_context(conv))["invalidated_dependencies"] == [SpeechDependency("reused", old.correlation_id).to_payload()]
    finally:
        await brain.stop()
        await repo.close()


async def test_newer_intent_can_explicitly_cancel_still_active_older_work(tmp_path):
    from tests.unit.test_v2_intent_revision import DrivenBackend, build_orchestrator, start_turn, work_event, speech_event, drain
    from jarvis.domain.v2 import BrainEventKind
    from jarvis.core.brain_service import BRAIN_SPEECH_REQUESTED

    backend = DrivenBackend()
    brain, events, repo, conv = await build_orchestrator(tmp_path, backend)
    try:
        old = await start_turn(brain, backend, conv, "start work")
        await backend.emit(work_event(BrainEventKind.ACCEPTED, conv, old.correlation_id, "work"))
        backend.started.clear()
        current = await start_turn(brain, backend, conv, "cancel it")
        queue = events.subscribe()
        await backend.emit(speech_event(conv, current.correlation_id, work_id="work", text="B describes old work"))
        assert not [event for event in drain(queue) if event.message_type == BRAIN_SPEECH_REQUESTED]
        outcome = (await brain.outcomes.list(conv))["outcomes"][0]
        assert outcome["source"]["correlation_id"] == current.correlation_id
        assert outcome["source"]["dependencies"] == []
        await backend.emit(work_event(BrainEventKind.CANCELLED, conv, current.correlation_id, "work"))
        assert brain.working_state(conv).active_work_ids == ()
        assert (await brain.speech_context(conv))["invalidated_dependencies"] == [SpeechDependency("work", old.correlation_id).to_payload()]
        await backend.emit(speech_event(conv, current.correlation_id, work_id="work", text="B describes old work"))
        assert not [event for event in drain(queue) if event.message_type == BRAIN_SPEECH_REQUESTED]
        selection = await brain.select_outcome(conv, outcome["id"], "explicit")
        assert selection["speech"]["source"] == (await brain.speech_context(conv))["current_speech_source"]
    finally:
        await brain.stop()
        await repo.close()


async def test_uncertain_source_has_own_order_but_late_reply_cannot_become_current(tmp_path):
    from tests.unit.test_v2_intent_revision import DrivenBackend, build_orchestrator, speech_event
    from jarvis.domain.v2 import AddressingDecision, BrainTurnInput
    from jarvis.core.brain_service import BrainOrchestrator

    backend = DrivenBackend()
    brain, events, repo, conv = await build_orchestrator(tmp_path, backend)
    try:
        old = BrainTurnInput(conversation_id=conv, correlation_id="uncertain", text="ambient", addressing=AddressingDecision.UNCERTAIN)
        await brain.submit(old)
        await asyncio.wait_for(backend.started.wait(), 1)
        old_sink = backend.sink
        assert (await brain.speech_context(conv))["current_speech_source"] is None
        current = BrainTurnInput(conversation_id=conv, correlation_id="current", text="real request")
        await brain.submit(current)
        current_source = (await brain.speech_context(conv))["current_speech_source"]
        await old_sink.emit(speech_event(conv, old.correlation_id, work_id="oldwork", text="late response"))
        assert (await brain.speech_context(conv))["current_speech_source"] == current_source
        assert brain.working_state(conv).current_user_intent == "real request"
        outcome = (await brain.outcomes.list(conv))["outcomes"][0]
        assert outcome["source"]["intent_epoch"] < current_source["intent_epoch"]
        await brain.stop()
        restarted = BrainOrchestrator(conversations=brain._conversations, events=events)
        assert (await restarted.rehydrate(conv))["current_user_intent"] == "real request"
        assert (await restarted.speech_context(conv))["current_speech_source"] == current_source
        duplicate = await restarted.submit(current)
        assert duplicate.duplicate and restarted.active_turn_count == 0
    finally:
        await brain.stop()
        await repo.close()
