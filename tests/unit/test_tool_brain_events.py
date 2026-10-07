"""Évènements de conversation du Tool Brain (handoff jarvis-tool-brain-ui-orchestrator, S9). Contrat : §17.

Runtime + file + exécuteur sur une **vraie** scène, décideur factice, horloge factice, et le **vrai**
`ConversationEventEmitter` (il valide chaque évènement : `counters.invalid == 0` est une assertion de chaque test).
Ce qui doit tenir :

- la chaîne causale réveil -> état -> décision -> action -> issue, avec `correlation_id`, `speech_id`, `parent_event_id` ;
- un cycle de vie d'action = un span `span_id` = id de l'action (`queued` ouvre ; une issue ferme, toujours) ;
- aucune donnée privée : jamais de contenu, d'arguments ni de raisonnement ; producteur `core.tool_brain` ;
- l'observation ne change rien : sans `events`, le comportement et les ids de S5-S8 sont inchangés ; un émetteur
  défaillant ne casse ni la décision ni l'exécution ; les évènements du Tool Brain ne le réveillent pas.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.core.conversation_event_emitter import PRODUCER_TOOL_BRAIN, ConversationEventEmitter
from jarvis.domain.conversation_event_ingest import is_core_owned
from jarvis.domain.conversation_event_store import AppendResult, AppendStatus
from jarvis.domain.conversation_events import (
    SPAN_OPENER, ConversationActor, ConversationEventType as T, decode_conversation_event, encode_conversation_event,
    reconstruct_conversation,
)
from jarvis.ports.tool_brain import InspectionRequest, QueueOp, ToolBrainReply
from jarvis.runtime.tool_brain_events import CLOSE_TYPE, FINISHED, QUEUED, STARTED, ToolBrainEvents
from jarvis.runtime.tool_brain_executor import UiActionExecutor, default_adapters
from jarvis.runtime.tool_brain_queue import ToolBrainActionQueue, Trigger
from jarvis.runtime.tool_brain_runtime import (
    DECIDED, ToolBrainConfig, ToolBrainMode, ToolBrainRuntime, WakeClass,
)
from tests.unit.test_tool_brain_active import (  # noqa: F401 - fixtures are imported by name
    A, B, DISPLAY, Clock, Diagnostics, FakeBoards, ScriptedDecider, catalog, move, service, speech,
)

AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
CONV, CORR = "conv-tb", "corr-turn-1"


class MemoryStore:
    async def append_many(self, events):
        return tuple(AppendResult(event.event_id, index + 1, AppendStatus.APPENDED) for index, event in enumerate(events))


class Rig:
    """Le Tool Brain actif, son émetteur réel, et tout ce que l'émetteur a accepté (dans l'ordre)."""

    def __init__(self, catalog, service, decider, *, wall_step_s: float = 0.0, **config) -> None:
        self.clock, self.boards, self.service, self.decider = Clock(), FakeBoards(), service, decider
        self.diagnostics, self.speech = Diagnostics(), None
        self.emitter = ConversationEventEmitter(MemoryStore())
        self.seen = []
        self.emitter.add_listener(self.seen.append)
        self.events = ToolBrainEvents(self.emitter, run_id="r1", wall=self.wall)
        adapters = default_adapters(service, self.boards)
        self.queue = ToolBrainActionQueue(clock=self.clock, supported=lambda server, tool: (server, tool) in adapters)
        self.executor = UiActionExecutor(service, self.boards, self.queue, adapters, gate=lambda: True)

        async def catalog_now():
            return catalog

        self.runtime = ToolBrainRuntime(
            service, self.boards, lambda: self.decider, config=ToolBrainConfig(mode=ToolBrainMode.ACTIVE, **config),
            catalog=catalog_now, speech_source=lambda: self.speech, queue=self.queue, executor=self.executor,
            diagnostics=self.diagnostics, events=self.events, clock=self.clock, wall_clock=self.wall)

    def wall(self) -> datetime:
        return AT + timedelta(seconds=self.clock.now - 1000.0)

    async def decide(self, wake=WakeClass.USER_TURN, **kw):
        kw.setdefault("conversation_id", CONV)
        kw.setdefault("correlation_id", CORR)
        self.runtime.wake(wake, "user.transcript.accepted", **kw)
        assert await self.runtime.step() == DECIDED
        return self.runtime.decisions()[-1]

    def types(self) -> list[str]:
        return [event.event_type.value for event in self.seen]

    def of(self, event_type: T):
        return [event for event in self.seen if event.event_type is event_type]

    def one(self, event_type: T):
        (event,) = self.of(event_type)
        return event

    def clean(self) -> None:
        assert self.emitter.counters.invalid == 0, "an emitted Tool Brain event broke the contract"
        assert self.events.stats()["failed"] == 0


# ------------------------------------------------------------------ chaîne causale


async def test_a_user_turn_leaves_wake_snapshot_decision_queued_started_completed_in_causal_order(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(reason_code="about_to_discuss"),))))
    decision = await rig.decide()
    rig.clock.advance(1.5)
    assert await rig.runtime.pump() == 1
    assert rig.types() == ["tool_brain.wake.requested", "tool_brain.snapshot.captured", "tool_brain.decision.made",
                           "tool_brain.action.queued", "tool_brain.action.started", "tool_brain.action.completed"]
    rig.clean()
    wake, snapshot, made, queued, started, done = rig.seen
    assert {event.producer for event in rig.seen} == {PRODUCER_TOOL_BRAIN} == {"core.tool_brain"}
    assert {event.actor for event in rig.seen} == {ConversationActor.TOOL_BRAIN}
    assert {event.conversation_id for event in rig.seen} == {CONV} and {event.correlation_id for event in rig.seen} == {CORR}
    assert all(event.content is None for event in rig.seen)
    # parent chain: wake -> snapshot -> decision -> queued -> (started | completed)
    assert snapshot.parent_event_id == wake.event_id and made.parent_event_id == snapshot.event_id
    assert queued.parent_event_id == made.event_id
    assert started.parent_event_id == queued.event_id and done.parent_event_id == queued.event_id
    # the action lifecycle is one span keyed by the action id
    action_id = decision.actions[0].queued["action_id"]
    assert action_id == "act-tbd-r1-000001-1" and decision.decision_id == "tbd-r1-000001"
    assert queued.span_id == done.span_id == action_id and queued.started_at < done.ended_at
    assert queued.attributes["action_id"] == action_id and queued.attributes["decision_id"] == decision.decision_id
    assert queued.attributes["tool_name"] == "scene_move" and queued.attributes["arguments_redacted"] is True
    assert queued.attributes["reason"] == "about_to_discuss" and queued.attributes["kind"] == "now"
    assert done.attributes["status"] == "done" and done.attributes["revision"] >= 1
    assert made.attributes["status"] == "completed" and made.attributes["actions"] == 1 and made.attributes["rejected"] == 0
    assert wake.attributes["reason"] == "user_turn" and wake.attributes["source"] == "event"
    assert type(snapshot.attributes["revision"]) is int
    # the instants and the span reconstruct into the documented items
    items = reconstruct_conversation([*rig.seen])
    assert [(item.event_type.value, item.status) for item in items if item.span_id == action_id] == [
        ("tool_brain.action.queued", "completed")]
    rig.clean()


async def test_ids_correlate_the_user_turn_the_speech_chunk_and_the_ui_intent(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(trigger={"type": "speech_chunk", "chunk_id": "k2"}, intent_id="intent-7"),))))
    rig.speech = speech()
    await rig.decide()
    queued = rig.one(T.TOOL_BRAIN_ACTION_QUEUED)
    assert queued.correlation_id == CORR and queued.speech_id == "k2" and queued.attributes["intent_id"] == "intent-7"
    assert queued.attributes["kind"] == "speech_chunk"
    # a speech-bound action is held until its chunk plays, then runs: queued .. started .. completed
    rig.speech = speech(phases="hP", chunks=[{"id": "k2", "i": 1, "ph": "playing"}])
    rig.clock.advance(0.5)
    await rig.runtime.pump()
    assert rig.types()[-2:] == ["tool_brain.action.started", "tool_brain.action.completed"]
    assert rig.one(T.TOOL_BRAIN_ACTION_STARTED).speech_id == "k2"
    rig.clean()


async def test_inspections_are_instants_between_the_snapshot_and_the_decision(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply((InspectionRequest("get_queue_state"),
                                                                InspectionRequest("get_information_on", A))),
                                               ToolBrainReply()))
    await rig.decide()
    assert rig.types() == ["tool_brain.wake.requested", "tool_brain.snapshot.captured", "tool_brain.inspect.requested",
                           "tool_brain.inspect.requested", "tool_brain.decision.made"]
    first, second = rig.of(T.TOOL_BRAIN_INSPECT_REQUESTED)
    assert (first.attributes["tool_name"], second.attributes["tool_name"]) == ("get_queue_state", "get_information_on")
    assert first.event_id != second.event_id and first.attributes["status"] == "ok"
    assert first.parent_event_id == rig.one(T.TOOL_BRAIN_SNAPSHOT_CAPTURED).event_id
    rig.clean()


# ------------------------------------------------------------------ issues d'une action


async def test_a_cancel_asked_by_the_decider_closes_the_span_as_cancelled(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(
        ToolBrainReply(actions=(move(trigger={"type": "event", "name": "later"}),)),
        ToolBrainReply(queue_ops=(QueueOp("cancel", "act-tbd-r1-000001-1"),))))
    await rig.decide()
    rig.clock.advance(2)
    await rig.decide(WakeClass.UI_CHANGE, urgent=True)
    closed = rig.one(T.TOOL_BRAIN_ACTION_CANCELLED)
    assert closed.span_id == "act-tbd-r1-000001-1" and closed.attributes["code"] == "cancelled_by_brain"
    assert closed.attributes["status"] == "cancelled"
    assert closed.trace_ref is None  # no journal line exists for a plain cancel: no dangling drill-down
    assert [item.status for item in reconstruct_conversation(rig.seen) if item.span_id == closed.span_id] == ["cancelled"]
    rig.clean()


async def test_an_expired_wait_is_a_cancelled_close_with_its_code(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(trigger={"type": "event", "name": "later"}),))))
    await rig.decide()
    rig.clock.advance(1000)  # beyond the bounded life of any waiting action
    await rig.runtime.pump()
    closed = rig.one(T.TOOL_BRAIN_ACTION_CANCELLED)
    assert closed.attributes["status"] == "expired" and closed.attributes["code"] == "action_expired"
    rig.clean()


async def test_a_reschedule_is_an_instant_inside_the_bar(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(
        ToolBrainReply(actions=(move(trigger={"type": "event", "name": "later"}),)),
        ToolBrainReply(queue_ops=(QueueOp("reschedule", "act-tbd-r1-000001-1", trigger={"type": "delay", "seconds": 5}),))))
    await rig.decide()
    rig.clock.advance(2)
    await rig.decide(WakeClass.UI_CHANGE, urgent=True)
    moved = rig.one(T.TOOL_BRAIN_ACTION_RESCHEDULED)
    assert moved.span_id is None and moved.attributes["kind"] == "delay"
    assert moved.parent_event_id == rig.one(T.TOOL_BRAIN_ACTION_QUEUED).event_id
    assert not rig.of(T.TOOL_BRAIN_ACTION_CANCELLED)  # still waiting: the span is open
    assert [item.status for item in reconstruct_conversation(rig.seen) if item.span_id == "act-tbd-r1-000001-1"] == ["open"]
    rig.clean()


async def test_a_world_that_changed_invalidates_the_action_and_asks_for_a_replan(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(),)), ToolBrainReply()))
    await rig.decide()
    await service.apply(SimpleNamespace_archive(A))  # the target disappears between the decision and the execution
    rig.clock.advance(1)
    await rig.runtime.pump()
    closed = rig.one(T.TOOL_BRAIN_ACTION_INVALIDATED)
    assert closed.span_id == "act-tbd-r1-000001-1" and closed.attributes["status"] == "invalidated"
    assert closed.attributes["code"] in {"object_archived", "unknown_object", "stale_scene_epoch"}
    assert closed.trace_ref is not None and closed.trace_ref.journal_kind == "tool_brain.action.invalidated"
    replan = rig.one(T.TOOL_BRAIN_REPLAN_REQUESTED)
    assert replan.parent_event_id == closed.event_id and replan.attributes["status"] == "requested"
    assert replan.attributes["action_id"] == closed.span_id
    # the journal line of the invalidation carries the event id: the detail panel joins on it
    line = next(data for kind, _level, data in rig.diagnostics.rows if kind == "tool_brain.action.invalidated")
    assert line["conversation_event_id"] == closed.event_id
    rig.clean()


async def test_an_owner_failure_closes_the_span_as_failed_with_a_safe_error_class(catalog, service, monkeypatch):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(),))))
    await rig.decide()

    async def boom(*args, **kwargs):
        raise RuntimeError("secret text that must never be copied")

    monkeypatch.setattr(service, "apply_if", boom)
    await rig.runtime.pump()
    failed = rig.one(T.TOOL_BRAIN_ACTION_FAILED)
    assert failed.attributes["status"] == "failed" and failed.attributes["error_class"] == "RuntimeError"
    assert "secret" not in json.dumps(encode_conversation_event(failed))
    rig.clean()


async def test_a_flush_by_the_ownership_arbiter_cancels_every_waiting_action(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(trigger={"type": "event", "name": "later"}), move(B, trigger={"type": "event", "name": "later"})))))
    await rig.decide()
    assert rig.runtime.flush_actions("ownership_jarvis_direct") == 2
    closes = rig.of(T.TOOL_BRAIN_ACTION_CANCELLED)
    assert len(closes) == 2 and {close.attributes["code"] for close in closes} == {"ownership_jarvis_direct"}
    rig.clean()


# ------------------------------------------------------------------ décisions qui n'agissent pas


async def test_a_failed_or_unavailable_decider_is_a_decision_event_with_its_code(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply()))
    rig.decider = None
    rig.runtime.wake(WakeClass.USER_TURN, "x", conversation_id=CONV, correlation_id=CORR)
    await rig.runtime.step()
    made = rig.one(T.TOOL_BRAIN_DECISION_MADE)
    assert made.attributes["status"] == "unavailable" and made.attributes["code"]
    assert rig.types()[0] == "tool_brain.wake.requested"
    rig.clean()


async def test_a_safety_tick_without_change_leaves_no_event_but_a_changed_world_does(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply()))
    await rig.decide()
    before = len(rig.seen)
    rig.clock.advance(60)
    rig.runtime.wake(WakeClass.TICK, "safety_tick")
    rig.clock.advance(1)  # past the calm window of an ordinary wake
    assert await rig.runtime.step() == "unchanged"
    assert len(rig.seen) == before  # a quiet tick must not fill the lane
    await service.apply(SimpleNamespace_archive(B))
    rig.clock.advance(60)
    rig.runtime.wake(WakeClass.TICK, "safety_tick")
    rig.clock.advance(1)
    assert await rig.runtime.step() == DECIDED
    wake = rig.of(T.TOOL_BRAIN_WAKE_REQUESTED)[-1]
    assert wake.attributes["source"] == "tick" and wake.conversation_id == CONV  # attached to the last conversation seen
    rig.clean()


async def test_a_wake_before_any_conversation_is_counted_not_invented(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply()))
    rig.runtime.wake(WakeClass.UI_CHANGE, "scene_revision")
    rig.clock.advance(1)
    assert await rig.runtime.step() == DECIDED
    assert rig.seen == [] and rig.events.stats()["no_conversation"] >= 3


# ------------------------------------------------------------------ propriété de l'écran


def test_an_ownership_fallback_is_a_visible_instant_with_its_reason():
    emitter = ConversationEventEmitter(MemoryStore())
    seen = []
    emitter.add_listener(seen.append)
    events = ToolBrainEvents(emitter, run_id="r1", wall=lambda: AT)
    events.note_conversation(CONV)
    assert events.ownership("jarvis_direct", previous="tool_brain", reason="decider_failing", fallback=True,
                            mode="active")
    assert events.ownership("tool_brain", previous="jarvis_direct", reason="active_healthy", fallback=False,
                            mode="active")
    fallback, delegated = seen
    assert fallback.attributes["owner"] == "jarvis_direct" and fallback.attributes["fallback"] is True
    assert fallback.attributes["status"] == "fallback" and fallback.attributes["reason"] == "decider_failing"
    assert delegated.attributes["status"] == "delegated" and delegated.event_id != fallback.event_id
    assert emitter.counters.invalid == 0


# ------------------------------------------------------------------ garanties d'observation


async def test_without_events_nothing_changes_for_the_runtime_and_its_ids(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(),))))
    bare_queue = ToolBrainActionQueue(clock=rig.clock)
    bare = ToolBrainRuntime(service, rig.boards, lambda: rig.decider, config=ToolBrainConfig(mode=ToolBrainMode.SHADOW),
                            catalog=lambda: _async(catalog), clock=rig.clock)
    bare.wake(WakeClass.USER_TURN, "x", conversation_id=CONV)
    assert await bare.step() == DECIDED
    assert bare.decisions()[-1].decision_id == "tbd-000001" and bare_queue.stats()["pending"] == 0
    assert rig.seen == []


async def test_a_broken_emitter_never_breaks_the_decision_or_the_execution(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(),))))

    class Broken:
        def record(self, *args, **kwargs):
            raise RuntimeError("emitter down")

        def derive_event_id(self, *args, **kwargs):
            raise RuntimeError("emitter down")

    rig.events._sink = Broken()
    decision = await rig.decide()
    assert decision.actions[0].queued["outcome"] == "queued"
    assert await rig.runtime.pump() == 1 and (await service.snapshot()).get_object(A).geometry.x == 5
    assert rig.events.stats()["failed"] >= 4 and rig.events.stats()["recorded"] == 0


async def test_an_action_keeps_its_conversation_when_another_one_starts_before_it_ends(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(trigger={"type": "event", "name": "later"}),))))
    await rig.decide(conversation_id="conv-one")
    rig.events.note_conversation("conv-two")  # a later conversation became "the last one seen"
    rig.runtime.flush_actions("ownership_jarvis_direct")
    queued, closed = rig.one(T.TOOL_BRAIN_ACTION_QUEUED), rig.one(T.TOOL_BRAIN_ACTION_CANCELLED)
    assert queued.conversation_id == closed.conversation_id == "conv-one"  # the span pairs inside one conversation


async def test_two_processes_in_one_conversation_never_collide_on_ids(catalog, service):
    ids = []
    for run in ("aaaaaa", "bbbbbb"):
        rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(trigger={"type": "event", "name": "x"}),))))
        rig.events.run_id = run
        await rig.decide()
        ids.append({event.event_id for event in rig.seen} | {event.span_id for event in rig.seen if event.span_id})
    assert not ids[0] & ids[1]


# ------------------------------------------------------------------ contrat pur


def test_every_terminal_status_of_the_queue_has_exactly_one_closing_type():
    from jarvis.runtime.tool_brain_queue import TERMINAL

    assert set(CLOSE_TYPE) == set(TERMINAL)
    assert all(SPAN_OPENER[close] is T.TOOL_BRAIN_ACTION_QUEUED for close in CLOSE_TYPE.values())


def test_tool_brain_events_stay_core_owned_and_survive_the_codec_round_trip():
    emitter = ConversationEventEmitter(MemoryStore())
    seen = []
    emitter.add_listener(seen.append)
    events = ToolBrainEvents(emitter, run_id="r1", wall=lambda: AT)
    events.wake("twk-r1-1", wake_class="user_turn", source="event", conversation_id=CONV, correlation_id=CORR)
    assert len(seen) == 1 and is_core_owned(seen[0])  # `core.tool_brain` is never ingestable
    assert decode_conversation_event(encode_conversation_event(seen[0])) == seen[0]


@pytest.mark.parametrize("kind", [QUEUED, STARTED, FINISHED, "bogus"])
def test_the_queue_observer_ignores_what_it_does_not_know(kind):
    emitter = ConversationEventEmitter(MemoryStore())
    events = ToolBrainEvents(emitter, run_id="r1", wall=lambda: AT)
    view = SimpleNamespace(
        record=SimpleNamespace(action_id="a1", tool="scene_move", decision_id=None, intent_id=None, priority="normal",
                               trigger=Trigger(), correlation_id=None, conversation_id=CONV, reason_code=""),
        status="pending", detail=None, code=None, reschedules=0)
    result = events.queue_change(kind, view)
    assert (result is None) == (kind in ("bogus", FINISHED))  # `finished` of a non-terminal status maps to nothing
    assert emitter.counters.invalid == 0


# ------------------------------------------------------------------ aides


def SimpleNamespace_archive(object_id):
    from jarvis.domain.scene import SceneActor, SceneCommand, SceneOp

    return SceneCommand(op=SceneOp.ARCHIVE, actor=SceneActor.USER, object_id=object_id)


async def _async(value):
    return value


# ------------------------------------------------------------------ journal, recherche, export, transcription


async def test_the_events_survive_the_real_store_and_every_read_path_finds_them(catalog, service, tmp_path):
    from jarvis.domain.conversation_event_export import (
        EXPORT_FORMAT, encode_export_line, export_header, export_trailer, read_export, reconstruct_export,
        transcript_from_export,
    )
    from jarvis.domain.conversation_event_search import SearchQuery
    from jarvis.domain.conversation_event_store import ConversationEventExtent, StoredConversationEvent
    from jarvis.domain.conversation_transcript import TranscriptMode, render_transcript
    from tests.fakes.conversation_events import open_store

    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(trigger={"type": "speech_chunk", "chunk_id": "k2"}),))))
    rig.speech = speech()
    await rig.decide()
    rig.speech = speech(phases="hP", chunks=[{"id": "k2", "i": 1, "ph": "playing"}])
    rig.clock.advance(0.5)
    await rig.runtime.pump()
    state, store = await open_store(tmp_path / "state.sqlite3")
    try:
        results = await store.append_many(list(rig.seen))
        assert [item.status.value for item in results] == ["appended"] * len(rig.seen)
        # lookup by the ids the Tool Brain correlates on
        by_turn = await store.list_events_by_id("correlation_id", CORR, conversation_id=CONV)
        assert {item.event.event_type for item in by_turn.events} == {event.event_type for event in rig.seen}
        by_chunk = await store.list_events_by_id("speech_id", "k2", conversation_id=CONV)
        assert {item.event.event_type for item in by_chunk.events} == {
            T.TOOL_BRAIN_ACTION_QUEUED, T.TOOL_BRAIN_ACTION_STARTED, T.TOOL_BRAIN_ACTION_COMPLETED}
        # search: the actor/type tokens, the action id (span id) and the status token
        action_id = rig.one(T.TOOL_BRAIN_ACTION_QUEUED).span_id
        for term, minimum in (("tool_brain", len(rig.seen)), ("action.completed", 1), (action_id, 2), ("done", 1)):
            page = await store.search_events(SearchQuery.parse(term), conversation_id=CONV)
            assert len(page.hits) >= minimum, term
        stored = [item for item in (await store.list_conversation_events(CONV)).events]
        assert [item.event for item in stored] == list(rig.seen)
        # export -> re-import -> same reconstruction and the same transcript
        extent = ConversationEventExtent(len(stored), stored[0].sequence, stored[-1].sequence)
        lines = [encode_export_line(export_header(CONV, exported_at=AT, extent=extent))]
        lines += [encode_export_line({"sequence": item.sequence, "recorded_at": "2026-10-07T09:00:00.000Z",
                                      "event": encode_conversation_event(item.event)}) for item in stored]
        lines.append(encode_export_line(export_trailer(events=len(stored), skipped_rows=0)))
        result = read_export(lines)
        assert result.complete and not result.invalid_lines and [i.event for i in result.events] == list(rig.seen)
        assert reconstruct_export(result) == reconstruct_conversation(list(rig.seen))
        detailed = transcript_from_export(result, mode=TranscriptMode.DETAILED)
        assert detailed == render_transcript(list(rig.seen), conversation_id=CONV, mode=TranscriptMode.DETAILED)
        assert "Tool Brain · action : terminé" in detailed and "outil scene_move" in detailed
        assert "Tool Brain · réveil" in detailed and "Tool Brain · décision" in detailed
        assert "Tool Brain" not in transcript_from_export(result, mode=TranscriptMode.PLAIN)  # diagnostics stay out of plain
        assert EXPORT_FORMAT
    finally:
        await state.close()


def test_the_tool_brain_never_wakes_itself_through_the_events_it_writes():
    from jarvis.runtime.tool_brain_wiring import EVENT_WAKES

    assert not [event_type for event_type in EVENT_WAKES if event_type.value.startswith("tool_brain.")]
