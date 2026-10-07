"""Tool Brain en mode `active` (handoff jarvis-tool-brain-ui-orchestrator, S6). Contrat : §14.

Runtime + file + exécuteur sur une **vraie** scène (`SceneService` mémoire), décideur factice, horloge factice. Ce qui doit
tenir :

- `shadow` n'exécute jamais (ni file ni exécuteur possibles) ; `active` exige les deux ;
- une décision `would_apply` entre dans la file, `pump()` l'exécute quand elle est due, par le propriétaire ;
- une action liée à la parole ne part que sur le morceau vivant, et jamais après une interruption ;
- une invalidation réveille le décideur aussitôt, avec l'état frais et la cause, puis la boucle de replan est bornée ;
- opérations de file demandées par le décideur (cancel, reprioritize, reschedule, replace) tracées dans la décision ;
- l'autorité Board/Session qui change vide la file ; une décision dépassée n'enfile rien.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from jarvis.domain.scene import (
    SceneActor, SceneCommand, SceneGeometry, SceneObjectFields, SceneObjectKind, SceneOp, ScenePayload,
)
from jarvis.domain.scene_selection import SceneSelection
from jarvis.domain.workspace_board import Board
from jarvis.core.scene_service import SceneService
from jarvis.ports.tool_brain import ProposedAction, QueueOp, ToolBrainReply, reply_from_payload, DeciderError
from jarvis.runtime.mcp_catalog import build_catalog
from jarvis.runtime.tool_brain_executor import UiActionExecutor, default_adapters
from jarvis.runtime.tool_brain_perception import SpeechSection
from jarvis.runtime.tool_brain_queue import (
    CANCELLED, DONE, INVALIDATED, QUEUED, ActionRecord, ToolBrainActionQueue, Trigger,
)
from jarvis.runtime.tool_brain_runtime import (
    DECIDED, SUPERSEDED, WOULD_APPLY, ToolBrainConfig, ToolBrainMode, ToolBrainRuntime, WakeClass,
)
from tests.unit.test_scene_service import MemoryRepository

AT = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
DISPLAY = "jarvis-display"
A, B, LOOSE = "brain-note-a", "brain-note-b", "brain-note-loose"


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(build_catalog())


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeBoards:
    def __init__(self) -> None:
        self.active = "default"

    async def list(self, *, include_archived=False):
        return (Board(board_id="default", title="Principal", created_at=AT, updated_at=AT),
                Board(board_id="board_aaa", title="Projet A", created_at=AT, updated_at=AT))

    async def active_board_id(self):
        return self.active

    async def switch(self, board_id, *, origin="protocol"):  # pragma: no cover - not used here
        raise AssertionError("not expected")


class ScriptedDecider:
    name = "fake"

    def __init__(self, *replies) -> None:
        self.replies, self.requests = list(replies), []
        self.gate: asyncio.Event | None = None

    async def decide(self, request, *, timeout_s):
        self.requests.append(request)
        if self.gate is not None:
            await self.gate.wait()
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


class Diagnostics:
    def __init__(self) -> None:
        self.rows = []

    def emit(self, kind, message, *, level="info", data=None):
        self.rows.append((kind, level, dict(data or {})))


def note(object_id, *, geometry=True):
    return SceneCommand(op=SceneOp.UPSERT_OBJECT, actor=SceneActor.BRAIN, object_id=object_id,
                        fields=SceneObjectFields(kind=SceneObjectKind.ARTIFACT, category="note",
                                                 payload=ScenePayload(title=object_id),
                                                 geometry=SceneGeometry(0, 0, 10, 10) if geometry else None))


def move(object_id=A, dx=5, **extra) -> ProposedAction:
    return ProposedAction(DISPLAY, "scene_move", {"object_ids": [object_id], "dx": dx, "dy": 0}, "show it", **extra)


class Rig:
    def __init__(self, catalog, service, decider, *, mode=ToolBrainMode.ACTIVE, **config) -> None:
        self.clock, self.boards, self.service = Clock(), FakeBoards(), service
        self.decider, self.diagnostics = decider, Diagnostics()
        self.speech = None
        self.intents = []
        self.queue = self.executor = None
        if mode is ToolBrainMode.ACTIVE:
            adapters = default_adapters(service, self.boards)
            self.queue = ToolBrainActionQueue(clock=self.clock, supported=lambda server, tool: (server, tool) in adapters)
            self.executor = UiActionExecutor(service, self.boards, self.queue, adapters,
                                             gate=lambda: self.runtime.mode is ToolBrainMode.ACTIVE)

        async def catalog_now():
            return catalog

        self.runtime = ToolBrainRuntime(
            service, self.boards, lambda: self.decider, config=ToolBrainConfig(mode=mode, min_interval_s=1.0, **config),
            catalog=catalog_now, speech_source=lambda: self.speech,
            intents_source=lambda conversation, correlation: list(self.intents), queue=self.queue,
            executor=self.executor, diagnostics=self.diagnostics, clock=self.clock, wall_clock=lambda: AT)

    async def x_of(self, object_id=A) -> float:
        return (await self.service.snapshot()).get_object(object_id).geometry.x

    async def decide(self, wake=WakeClass.USER_TURN, **kw):
        self.runtime.wake(wake, "test", **kw)
        assert await self.runtime.step() == DECIDED
        return self.runtime.decisions()[-1]


@pytest.fixture
async def service():
    scene = SceneService(MemoryRepository())
    await scene.start()
    for object_id in (A, B):
        await scene.apply(note(object_id))
    await scene.apply(note(LOOSE, geometry=False))
    yield scene
    await scene.close()


def speech(*, state="playing", phases="Pp", chunks=None, obsolete=()):
    chunks = chunks if chunks is not None else [{"id": "k1", "i": 0, "ph": "playing"}, {"id": "k2", "i": 1, "ph": "pending"}]
    return SpeechSection("wired", {"chains": [{"chain": "r1", "corr": "c1", "n": len(phases), "state": state,
                                               "phases": phases, "chunks": chunks}],
                                   "obsolete_chunk_ids": list(obsolete)})


# ------------------------------------------------------------------ la porte de mode


async def test_shadow_never_executes_and_cannot_be_given_an_executor(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(),))), mode=ToolBrainMode.SHADOW)
    decision = await rig.decide()
    assert decision.actions[0].verdict == WOULD_APPLY and decision.actions[0].queued is None
    assert await rig.runtime.pump() == 0 and await rig.x_of() == 0 and "queue" not in rig.runtime.status()
    adapters = default_adapters(service, rig.boards)
    queue = ToolBrainActionQueue(clock=rig.clock)
    executor = UiActionExecutor(service, rig.boards, queue, adapters, gate=lambda: True)
    with pytest.raises(ValueError):  # a shadow runtime refuses a queue/executor outright
        ToolBrainRuntime(service, rig.boards, lambda: None, config=ToolBrainConfig(mode=ToolBrainMode.SHADOW),
                         queue=queue, executor=executor)
    with pytest.raises(ValueError):  # half-wired active is refused too
        ToolBrainRuntime(service, rig.boards, lambda: None, config=ToolBrainConfig(mode=ToolBrainMode.ACTIVE),
                         queue=queue)


async def test_a_gate_closed_after_construction_still_executes_nothing(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(),))))
    rig.runtime._config = ToolBrainConfig(mode=ToolBrainMode.SHADOW)  # the mode seam flips back: the gate follows
    await rig.decide()
    assert await rig.runtime.pump() == 0 and await rig.x_of() == 0
    assert rig.queue.pending_count() == 1  # still queued, never run


# ------------------------------------------------------------------ plan -> file -> exécution


async def test_active_queues_a_would_apply_action_and_pump_executes_it_through_the_owner(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(reason_code="about_to_discuss"),))))
    decision = await rig.decide()
    (verdict,) = decision.actions
    assert verdict.queued == {"outcome": "queued", "action_id": "act-tbd-000001-1", "code": None}
    assert verdict.to_dict()["queue"]["action_id"] == "act-tbd-000001-1"
    assert rig.queue.get("act-tbd-000001-1").status == QUEUED and await rig.x_of() == 0  # nothing runs at decision time
    assert await rig.runtime.pump() == 1
    view = rig.queue.get("act-tbd-000001-1")
    assert view.status == DONE and await rig.x_of() == 5
    assert view.record.planned_from_snapshot == decision.perception_digest and view.record.reason_code == "about_to_discuss"
    assert rig.runtime.status()["counters"]["actions_executed"] == 1 and rig.runtime.status()["queue"]["done"] == 1
    assert await rig.runtime.pump() == 0 and await rig.x_of() == 5  # pump again: nothing replays


async def test_a_rejected_action_never_enters_the_queue(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move("brain-made-up-id"),))))
    decision = await rig.decide()
    assert decision.actions[0].verdict == "rejected" and decision.actions[0].queued is None
    assert rig.queue.pending_count() == 0 and await rig.runtime.pump() == 0


async def test_duplicate_proposals_and_a_full_queue_are_admission_results_not_errors(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(), move(), move(B)))))
    decision = await rig.decide()
    assert [item.queued["outcome"] for item in decision.actions] == ["queued", "duplicate", "queued"]
    assert decision.actions[1].queued["action_id"] == "act-tbd-000001-1" and rig.queue.pending_count() == 2


async def test_the_decision_sees_the_queue_in_its_perception_and_through_the_inspection_read(catalog, service):
    from jarvis.ports.tool_brain import InspectionRequest

    rig = Rig(catalog, service, ScriptedDecider(
        ToolBrainReply(actions=(move(trigger={"type": "event", "name": "later"}),)),
        ToolBrainReply((InspectionRequest("get_queue_state"),)), ToolBrainReply()))
    await rig.decide()
    rig.clock.advance(2)
    await rig.decide(WakeClass.UI_CHANGE, urgent=True)
    first, second = rig.decider.requests[0], rig.decider.requests[1]
    assert first.perception["queue"]["status"] == "wired" and first.perception["queue"]["count"] == 0
    assert second.perception["queue"]["count"] == 1 and second.perception["queue"]["items"][0]["status"] == "pending"
    answer = rig.decider.requests[2].inspections[0]
    assert answer["kind"] == "queue" and answer["status"] == "wired" and answer["items"][0]["trigger"]["name"] == "later"


# ------------------------------------------------------------------ parole


async def test_a_speech_bound_action_fires_on_its_chunk_and_never_after_an_interruption(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(trigger={"type": "speech_chunk", "chunk_id": "k2"}), move(B, trigger={"type": "speech_chunk", "chunk_id": "k2"}),
        ))))
    rig.speech = speech()
    decision = await rig.decide()
    assert all(item.queued["outcome"] == "queued" for item in decision.actions)
    assert await rig.runtime.pump() == 0 and await rig.x_of() == 0  # k2 is still pending: nothing moves
    rig.speech = speech(phases="hP", chunks=[{"id": "k2", "i": 1, "ph": "playing"}])
    assert await rig.runtime.pump() == 2 and await rig.x_of() == 5 and await rig.x_of(B) == 5

    rig.clock.advance(2)
    again = ScriptedDecider(ToolBrainReply(actions=(move(dx=1, trigger={"type": "speech_chunk", "chunk_id": "k4"}),)))
    rig.decider = again
    rig.speech = speech(phases="hhpp", chunks=[{"id": "k4", "i": 3, "ph": "pending"}])
    await rig.decide()
    rig.speech = speech(state="interrupted", phases="hhio", chunks=[{"id": "k4", "i": 3, "ph": "obsolete"}], obsolete=["k4"])
    assert await rig.runtime.pump() == 0
    (pending,) = [v for v in rig.queue.views() if v.record.trigger.chunk_id == "k4"]
    assert (pending.status, pending.code) == (CANCELLED, "speech_obsolete")
    rig.speech = speech(phases="hhhP", chunks=[{"id": "k4", "i": 3, "ph": "playing"}])  # even if it looks alive again
    assert await rig.runtime.pump() == 0 and await rig.x_of() == 5


async def test_an_intent_bound_action_follows_the_intent_row_and_the_speech(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(intent_id="ui1", trigger={"type": "intent", "intent_id": "ui1"}),))))
    rig.intents = [{"intent_id": "ui1", "kind": "reveal", "refs": [{"kind": "object", "id": A}], "subject": "",
                    "timing": "with_speech", "paragraph": 1, "correlation_id": "c1"}]
    rig.speech = speech()
    await rig.decide(conversation_id="conv-1", correlation_id="c1")
    assert await rig.runtime.pump() == 0
    rig.speech = speech(phases="hP", chunks=[{"id": "k2", "i": 1, "ph": "playing"}])
    assert await rig.runtime.pump() == 1 and await rig.x_of() == 5


async def test_a_delay_action_runs_on_the_fake_clock_and_an_event_action_on_its_fact(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(trigger={"type": "delay", "seconds": 10}), move(B, trigger={"type": "event", "name": "scene_revision"})))))
    await rig.decide()
    assert await rig.runtime.pump() == 0
    rig.runtime.note_event("scene_revision")
    assert await rig.runtime.pump() == 1 and await rig.x_of(B) == 5 and await rig.x_of() == 0
    rig.clock.advance(10.5)
    assert await rig.runtime.pump() == 1 and await rig.x_of() == 5


async def test_actions_run_in_priority_then_arrival_order(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(A, 1, priority="low"), move(A, 10, priority="high"), move(A, 100)))))
    await rig.decide()
    order = []
    original = rig.executor.execute

    async def spy(action_id):
        order.append(rig.queue.get(action_id).record.arguments["dx"])
        return await original(action_id)

    rig.executor.execute = spy
    assert await rig.runtime.pump() == 3 and order == [10, 100, 1] and await rig.x_of() == 111


# ------------------------------------------------------------------ invalidation -> replan


async def test_an_invalidation_wakes_the_decider_at_once_with_the_cause_and_fresh_state(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(
        ToolBrainReply(actions=(move(),)), ToolBrainReply(actions=(move(B),))))
    await rig.decide()
    await service.apply(SceneCommand(op=SceneOp.ARCHIVE_SELECTION, actor=SceneActor.USER,
                                     selection=SceneSelection(ids=(A,))))  # the world moved under the queue
    assert await rig.runtime.pump() == 1
    assert rig.queue.get("act-tbd-000001-1").status == INVALIDATED and await rig.x_of(B) == 0
    pending = rig.runtime.status()["pending"]
    assert pending["urgent"] and pending["classes"] == {"action_result": 1}
    assert pending["invalidated"] == [{"action_id": "act-tbd-000001-1", "tool": "scene_move", "code": "object_archived"}]

    rig.clock.advance(1.0)  # the minimum interval between decisions still holds, nothing else waits
    assert await rig.runtime.step() == DECIDED
    replan = rig.decider.requests[-1]
    assert replan.trigger["invalidated"][0]["code"] == "object_archived"
    assert all(item["id"] != A for item in replan.perception["scene"]["objects"])  # the fresh state, without it
    assert await rig.runtime.pump() == 1 and await rig.x_of(B) == 5
    assert rig.runtime.status()["counters"]["replans"] == 1


async def test_the_replan_loop_is_bounded_when_the_decider_keeps_proposing_an_action_the_owner_refuses(catalog, service):
    # The loose note exists (so validation passes) but has no place: the *owner* refuses it every time.
    replies = [ToolBrainReply(actions=(move(LOOSE, dx=index + 1),)) for index in range(8)]
    rig = Rig(catalog, service, ScriptedDecider(*replies))
    await rig.decide()
    for _ in range(6):
        await rig.runtime.pump()
        rig.clock.advance(1.5)
        if await rig.runtime.step() != DECIDED:
            break
    counters = rig.runtime.status()["counters"]
    assert counters["replans"] == 3 and counters["replans_suppressed"] >= 1
    assert ("tool_brain.replan_suppressed", "warning") in [(kind, level) for kind, level, _ in rig.diagnostics.rows]
    assert rig.runtime.status()["pending"] is None  # no urgent wake left behind: the loop stopped, and said so
    assert await rig.x_of() == 0


async def test_a_successful_execution_resets_the_replan_streak(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(move(LOOSE),)), ToolBrainReply(actions=(move(),))))
    await rig.decide()
    await rig.runtime.pump()
    assert rig.runtime._replan_streak == 1
    rig.clock.advance(1.5)
    await rig.runtime.step()
    await rig.runtime.pump()
    assert rig.runtime._replan_streak == 0 and await rig.x_of() == 5


# ------------------------------------------------------------------ opérations de file demandées par le décideur


async def test_the_decider_can_cancel_reprioritize_reschedule_and_replace_what_it_queued(catalog, service):
    trigger = {"type": "event", "name": "later"}
    rig = Rig(catalog, service, ScriptedDecider(
        ToolBrainReply(actions=(move(trigger=trigger), move(B, trigger=trigger), move(B, 2, trigger=trigger))),
        ToolBrainReply(actions=(move(A, 50, trigger={"type": "delay", "seconds": 3}, replaces=("act-tbd-000001-1",)),),
                       queue_ops=(QueueOp("cancel", "act-tbd-000001-2"), QueueOp("reprioritize", "act-tbd-000001-3", "high"),
                                  QueueOp("reschedule", "act-tbd-000001-3", trigger={"type": "delay", "seconds": 2}),
                                  QueueOp("cancel", "ghost"), QueueOp("reprioritize", "act-tbd-000001-3", "urgent"),
                                  QueueOp("reschedule", "act-tbd-000001-3", trigger={"type": "later"})))))
    await rig.decide()
    rig.clock.advance(2)
    decision = await rig.decide(WakeClass.UI_CHANGE, urgent=True)
    assert [(op["op"], op["result"]) for op in decision.queue_ops] == [
        ("cancel", "cancelled"), ("reprioritize", "reprioritized"), ("reschedule", "rescheduled"),
        ("cancel", "unknown_action"), ("reprioritize", "invalid_priority"), ("reschedule", "invalid_trigger")]
    assert decision.to_dict()["queue_ops"][0] == {"op": "cancel", "action_id": "act-tbd-000001-2", "result": "cancelled"}
    assert rig.queue.get("act-tbd-000001-1").status == "superseded"
    assert rig.queue.get("act-tbd-000002-1").record.supersedes == ("act-tbd-000001-1",)
    assert rig.queue.get("act-tbd-000001-2").status == CANCELLED
    third = rig.queue.get("act-tbd-000001-3")
    assert third.record.priority == "high" and third.record.trigger.delay_s == 2.0 and third.reschedules == 1
    assert rig.runtime.status()["counters"]["queue_ops"] == 6


def test_the_reply_codec_carries_trigger_priority_replaces_and_queue_ops_strictly():
    reply = reply_from_payload({"actions": [{"server": DISPLAY, "tool": "scene_move", "arguments": {}, "priority": "high",
                                             "trigger": {"type": "speech_chunk", "chunk_id": "k1"},
                                             "replaces": ["act-1"], "reason_code": "about_to_discuss"}],
                                "queue_ops": [{"op": "cancel", "action_id": "act-2"},
                                              {"op": "reschedule", "action_id": "act-3", "trigger": {"type": "now"}}]})
    (action,) = reply.actions
    assert (action.priority, action.replaces, action.reason_code) == ("high", ("act-1",), "about_to_discuss")
    assert action.trigger == {"type": "speech_chunk", "chunk_id": "k1"}
    assert [(op.op, op.action_id) for op in reply.queue_ops] == [("cancel", "act-2"), ("reschedule", "act-3")]
    for bad in ({"queue_ops": [{"op": "explode", "action_id": "x"}]}, {"queue_ops": [{"op": "cancel"}]},
                {"queue_ops": [{"op": "cancel", "action_id": "x", "extra": 1}]}, {"queue_ops": "cancel"},
                {"queue_ops": [{"op": "cancel", "action_id": "x"}] * 7},
                {"actions": [{"server": "s", "tool": "t", "trigger": "now"}]},
                {"actions": [{"server": "s", "tool": "t", "priority": 3}]},
                {"actions": [{"server": "s", "tool": "t", "replaces": "act-1"}]}):
        with pytest.raises(DeciderError):
            reply_from_payload(bad)


# ------------------------------------------------------------------ autorité, décision dépassée, boucle réelle


async def test_an_authority_change_cancels_everything_pending_and_is_counted(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply(actions=(
        move(trigger={"type": "event", "name": "later"}), move(B, trigger={"type": "event", "name": "later"})))))
    await rig.decide()
    assert rig.runtime.note_authority_change("board.switched") == 2
    assert {view.code for view in rig.queue.views()} == {"authority_changed"}
    rig.runtime.note_event("later")
    assert await rig.runtime.pump() == 0 and await rig.x_of() == 0
    assert rig.runtime.status()["counters"]["authority_changes"] == 1
    assert ("tool_brain.queue.authority_changed", "warning") in [(kind, level) for kind, level, _ in rig.diagnostics.rows]


async def test_a_superseded_decision_enqueues_nothing(catalog, service):
    decider = ScriptedDecider(ToolBrainReply(actions=(move(),)))
    decider.gate = asyncio.Event()
    rig = Rig(catalog, service, decider)
    rig.runtime.wake(WakeClass.USER_TURN, "first")
    task = asyncio.ensure_future(rig.runtime.step())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    rig.runtime.wake(WakeClass.UI_INTENT, "newer")  # urgent: the in-flight answer is stale
    await task
    assert rig.runtime.decisions()[-1].outcome == SUPERSEDED and rig.queue.pending_count() == 0


async def test_the_real_loop_runs_a_due_action_when_its_fact_arrives_and_close_empties_the_queue(catalog, service):
    rig = Rig(catalog, service, ScriptedDecider(ToolBrainReply()))
    rig.queue.add(ActionRecord(
        "act-direct", DISPLAY, "scene_move", {"object_ids": [A], "dx": 3, "dy": 0},
        trigger=Trigger.from_payload(
            {"type": "event", "name": "mouth.speech.started"})))
    rig.queue.add(ActionRecord(
        "act-left", DISPLAY, "scene_move", {"object_ids": [B], "dx": 1, "dy": 0},
        trigger=Trigger.from_payload(
            {"type": "event", "name": "never"})))
    rig.runtime.start()
    try:
        await asyncio.sleep(0.05)
        assert await rig.x_of() == 0
        rig.runtime.note_event("mouth.speech.started")
        for _ in range(50):
            await asyncio.sleep(0.02)
            if await rig.x_of() == 3:
                break
        assert await rig.x_of() == 3 and rig.queue.get("act-direct").status == DONE
    finally:
        await rig.runtime.close()
    assert rig.queue.get("act-left").code == "shutdown"  # nothing survives the stop
