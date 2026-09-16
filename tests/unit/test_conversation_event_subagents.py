"""Sub-agent spans recorded by `AgentTaskTracker` in the Control Center (Slice 03b).

The stream sequences reuse the shapes of `test_agent_tasks.py` (real Claude
`stream-json` events). What must hold:

- one span per sub-agent under a stable source id (`conversation_key`), although
  `AgentTask.id` switches from `tool_use_id` to `task_id`, and across a merge;
- attribution to a conversation only from Core's explicit scope, confirmed by the
  `result` that consumed exactly the scoped message; anything else records
  nothing, counted and journaled;
- the parent is Core's `brain.work.started` only when correlation and work ids
  were both given;
- every event with a `trace_ref` joins exactly one journal line.
"""

from __future__ import annotations

import json

from aiohttp import web
import pytest

from jarvis.domain.conversation_events import (
    ConversationEventType as T,
    derive_conversation_event_id,
    encode_conversation_event,
    reconstruct_conversation,
)
from jarvis.runtime.subagent_conversation import SubagentConversationScope, subagent_close_type
from jarvis.runtime.claude_local import ClaudeLocalAgent
from jarvis.runtime.control_center import ControlCenter
from jarvis.runtime.conversation_event_forwarder import PRODUCER_AGENT_TASKS
from jarvis.runtime.journal import read_jsonl_tail
from tests.fakes.conversation_events import assert_each_trace_ref_joins_one_line, queued, recording_forwarder
from tests.unit.test_agent_tasks import (
    SESSION,
    Clock,
    agent_call,
    async_launched,
    child_text,
    feed,
    notification,
    progress,
    task_started,
)

SCOPE = SubagentConversationScope("conv-1", "corr-1", "brain-turn:corr-1")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def agent(tmp_path, clock):
    agent = ClaudeLocalAgent(runtime_root=tmp_path, cwd=tmp_path, command="claude")
    agent.subtasks.clock = clock
    agent.subtasks.conversation_events = recording_forwarder()
    return agent


def events_of(agent):  # noqa: ANN001
    return queued(agent.subtasks.conversation_events)


def lines(tmp_path):  # noqa: ANN001
    return read_jsonl_tail(tmp_path / "trace.jsonl", limit=1000)


def ask(agent, uuid="msg-1", scope=SCOPE):  # noqa: ANN001
    """What `ClaudeLocalAgent.ask` does before writing the message, without a process."""
    agent.subtasks.begin_conversation_turn(scope, message_uuid=uuid)
    agent.subtasks.turn_started()


def result(*uuids, origin=None):  # noqa: ANN001
    event = {"type": "result", "subtype": "success", "result": "C'est lancé.", "session_id": SESSION}
    if origin is not None:
        event["origin"] = origin
    else:
        event["user_message_uuids"] = list(uuids)
    return event


def brain_work_parent(scope=SCOPE) -> str:  # noqa: ANN001
    return derive_conversation_event_id(producer="core.brain_service", event_type=T.BRAIN_WORK_STARTED,
                                        conversation_id=scope.conversation_id,
                                        source_ids=(scope.correlation_id, scope.work_id))


def test_a_background_subagent_keeps_one_span_while_its_id_moves_from_tool_use_to_task_id(agent, clock, tmp_path):
    ask(agent)
    feed(agent, agent_call("toolu_A", "Persiste le réglage", model="claude-sonnet-5"))
    assert events_of(agent) == []  # provisional until the result proves the turn was this message
    feed(agent, async_launched("toolu_A", "a1"), task_started("a1", "toolu_A", "Persiste le réglage"))
    assert agent.subtasks.tasks()[0].id == "a1"  # the public id changed
    feed(agent, result("msg-1"))

    [started] = events_of(agent)
    assert started.event_type is T.SUBAGENT_STARTED and started.task_id == started.span_id == "toolu_A"
    clock.advance(95)
    feed(agent, progress("a1", "toolu_A", "Lit le code", tokens=900, tool_uses=4),
         notification("a1", "toolu_A", "completed", "Réglage persistant."))

    started, finished = events_of(agent)
    assert finished.event_type is T.SUBAGENT_FINISHED and finished.task_id == finished.span_id == "toolu_A"
    for event in (started, finished):
        assert event.producer == PRODUCER_AGENT_TASKS and event.conversation_id == "conv-1"
        assert (event.correlation_id, event.work_id) == ("corr-1", "brain-turn:corr-1")
        assert event.parent_event_id == brain_work_parent()
    assert started.content == "Persiste le réglage" and finished.content is None
    attributes = dict(finished.attributes)
    assert (attributes["status"], attributes["duration_ms"], attributes["tool_uses"]) == ("completed", 95_000, 4)
    assert "Réglage persistant" not in json.dumps([encode_conversation_event(e) for e in (started, finished)])
    [item] = reconstruct_conversation([started, finished])
    assert item.status == "finished" and (item.ended_at - item.started_at).total_seconds() == 95
    assert_each_trace_ref_joins_one_line(events_of(agent), lines(tmp_path))


def test_a_subagent_without_explicit_conversation_records_nothing_and_says_so(agent, tmp_path):
    agent.subtasks.turn_started()  # a panel message: no Core scope
    feed(agent, agent_call("toolu_P", "Tâche du panneau", model="claude-sonnet-5"),
         async_launched("toolu_P", "p1"), result("panel-msg"), notification("p1", "toolu_P", "completed"))

    assert events_of(agent) == []
    unattributed = [line for line in lines(tmp_path) if line["kind"] == "agent.subagent.conversation_unattributed"]
    assert [(line["data"]["reason"], line["data"]["task_id"]) for line in unattributed] == [
        ("no_conversation_scope", "toolu_P")]
    assert agent.subtasks.conversation_counts == {"no_conversation_scope": 1}
    # the journal lines keep their shape: no dangling event id
    assert all("conversation_event_id" not in line["data"] for line in lines(tmp_path)
               if line["kind"].startswith("agent.subagent.started"))


def test_a_spontaneous_turn_ending_first_does_not_lend_its_subagents_to_the_question(agent, tmp_path):
    ask(agent)
    # The CLI's own turn (background completion) runs before our message is consumed.
    feed(agent, agent_call("toolu_S", "Relais spontané", model="claude-sonnet-5"),
         async_launched("toolu_S", "s1"), result(origin={"kind": "task-notification"}))
    feed(agent, agent_call("toolu_Q", "Pour la question", model="claude-sonnet-5"),
         async_launched("toolu_Q", "q1"), result("msg-1"))

    assert [(event.event_type, event.task_id) for event in events_of(agent)] == [(T.SUBAGENT_STARTED, "toolu_Q")]
    assert agent.subtasks.conversation_counts == {"other_turn": 1, "attributed": 1}
    assert_each_trace_ref_joins_one_line(events_of(agent), lines(tmp_path))


@pytest.mark.parametrize("scenario", ["merged_result", "busy_at_send", "foreign_input", "unverifiable_cli"])
def test_an_ambiguous_turn_records_no_subagent(agent, scenario, tmp_path):
    if scenario == "busy_at_send":
        agent.subtasks.turn_started()  # another turn is already running
    ask(agent)
    if scenario == "foreign_input":
        agent.subtasks.note_unscoped_input()
    feed(agent, agent_call("toolu_X", "Ambigu", model="claude-sonnet-5"), async_launched("toolu_X", "x1"))
    if scenario == "merged_result":
        feed(agent, result("msg-1", "panel-msg"))
    elif scenario == "unverifiable_cli":
        feed(agent, {"type": "result", "subtype": "success", "result": "ok", "session_id": SESSION})
    else:
        feed(agent, result("msg-1"))
    feed(agent, notification("x1", "toolu_X", "completed"))

    assert events_of(agent) == []
    assert "attributed" not in agent.subtasks.conversation_counts
    assert sum(agent.subtasks.conversation_counts.values()) == 1
    if scenario in ("busy_at_send", "foreign_input"):
        # Known ambiguous before launch: not even a provisional id in the journal line.
        started = [line for line in lines(tmp_path) if line["kind"] == "agent.subagent.started"]
        assert started and all("conversation_event_id" not in line["data"] for line in started)


@pytest.mark.parametrize(("status", "expected"), [
    ("completed", T.SUBAGENT_FINISHED), ("killed", T.SUBAGENT_STOPPED), ("stopped", T.SUBAGENT_STOPPED),
    ("interrupted", T.SUBAGENT_STOPPED), ("failed", T.SUBAGENT_FAILED), ("cancelled", T.SUBAGENT_FAILED),
    ("brand_new_status", T.SUBAGENT_FAILED),
])
def test_terminal_statuses_map_to_the_contract_and_keep_the_raw_status(agent, status, expected):
    assert subagent_close_type(status) is expected
    ask(agent)
    feed(agent, agent_call("toolu_T", "Statut", model="claude-sonnet-5"), async_launched("toolu_T", "t1"),
         result("msg-1"), notification("t1", "toolu_T", status))
    close = events_of(agent)[-1]
    assert close.event_type is expected and dict(close.attributes)["status"] == status
    assert reconstruct_conversation(events_of(agent))[0].status != "open"


def test_stopping_the_brain_closes_confirmed_spans_and_forgets_provisional_ones(agent, tmp_path):
    ask(agent)
    feed(agent, agent_call("toolu_1", "Confirmé", model="claude-sonnet-5"), async_launched("toolu_1", "c1"),
         result("msg-1"))
    ask(agent, uuid="msg-2", scope=SubagentConversationScope("conv-1", "corr-2", "brain-turn:corr-2"))
    feed(agent, agent_call("toolu_2", "Provisoire", model="claude-sonnet-5"))
    agent.subtasks.process_stopped()

    assert [(event.event_type, event.task_id) for event in events_of(agent)] == [
        (T.SUBAGENT_STARTED, "toolu_1"), (T.SUBAGENT_STOPPED, "toolu_1")]
    assert dict(events_of(agent)[-1].attributes)["status"] == "interrupted"
    assert agent.subtasks.conversation_counts["process_stopped"] == 1
    assert_each_trace_ref_joins_one_line(events_of(agent), lines(tmp_path))


def test_a_nested_subagent_inherits_the_conversation_and_points_to_its_parent_span(agent, tmp_path):
    ask(agent)
    feed(agent, agent_call("toolu_P", "Parent", model="claude-sonnet-5"),
         async_launched("toolu_P", "p1"), result("msg-1"))
    feed(agent, child_text("toolu_P", "Je délègue."),
         agent_call("toolu_C", "Enfant", parent="toolu_P", model="claude-haiku-5"),
         notification("toolu_C", "toolu_C", "completed"))

    child = [event for event in events_of(agent) if event.task_id == "toolu_C"]
    assert [event.event_type for event in child] == [T.SUBAGENT_STARTED, T.SUBAGENT_FINISHED]
    parent_start = next(event for event in events_of(agent) if event.task_id == "toolu_P")
    assert {event.parent_event_id for event in child} == {parent_start.event_id}
    assert_each_trace_ref_joins_one_line(events_of(agent), lines(tmp_path))


def test_a_scope_without_work_id_records_the_span_without_guessing_a_parent(agent):
    ask(agent, scope=SubagentConversationScope("conv-1", "corr-1", None))
    feed(agent, agent_call("toolu_N", "Sans travail", model="claude-sonnet-5"), async_launched("toolu_N", "n1"),
         result("msg-1"))
    [started] = events_of(agent)
    assert started.parent_event_id is None and started.work_id is None


def test_two_halves_merged_after_attribution_keep_a_single_span_identity(agent, clock, tmp_path):
    ask(agent)
    feed(agent, agent_call("toolu_M", "Fusion", model="claude-sonnet-5"))
    clock.advance(1)
    # A task_started without tool_use_id creates a second half, then a progress names both.
    feed(agent, task_started("m1", None, "Fusion"), progress("m1", "toolu_M", "Lit", tokens=10, tool_uses=1))
    assert len(agent.subtasks.tasks()) == 1
    feed(agent, result("msg-1"), notification("m1", "toolu_M", "completed"))

    keys = {event.task_id for event in events_of(agent)}
    assert keys == {"toolu_M"}
    assert [event.event_type for event in events_of(agent)] == [T.SUBAGENT_STARTED, T.SUBAGENT_FINISHED]
    assert all(not item.anomalies for item in reconstruct_conversation(events_of(agent)))
    assert_each_trace_ref_joins_one_line(events_of(agent), lines(tmp_path))


def test_scope_payload_is_explicit_or_nothing():
    assert SubagentConversationScope.from_payload(None) is None
    assert SubagentConversationScope.from_payload({"correlation_id": "c"}) is None
    assert SubagentConversationScope.from_payload({"conversation_id": " padded "}) is None
    assert SubagentConversationScope.from_payload({"conversation_id": "conv", "work_id": 7}) == \
        SubagentConversationScope("conv", None, None)


class JsonRequest:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    async def json(self) -> object:
        return self.payload


async def test_the_ask_route_hands_the_explicit_scope_to_the_agent_never_to_the_prompt(tmp_path):
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path)
    seen: dict[str, object] = {}

    async def fake_ask(text: str, *, timeout_s: float, conversation_scope=None) -> dict:  # noqa: ANN001
        seen.update(text=text, scope=conversation_scope)
        return {"ok": True, "text": "fait"}

    control.agent.ask = fake_ask  # type: ignore[assignment]
    response = await control.agent_ask(JsonRequest({
        "text": "salut", "context": {"addressing": "addressed"},
        "conversation": {"conversation_id": "conv-9", "correlation_id": "corr-9", "work_id": "brain-turn:corr-9"}}))

    assert isinstance(response, web.Response)
    assert seen["scope"] == SubagentConversationScope("conv-9", "corr-9", "brain-turn:corr-9")
    assert "corr-9" not in str(seen["text"]) and "conv-9" not in str(seen["text"])


async def test_the_control_center_wires_its_forwarder_into_the_claude_tracker(tmp_path):
    forwarder = recording_forwarder()
    control = ControlCenter(runtime_root=tmp_path, project_root=tmp_path, conversation_events=forwarder)
    assert control.agent.subtasks.conversation_events is forwarder


async def test_claude_ask_with_a_scope_attributes_the_subagents_of_its_own_result(agent, tmp_path):
    import asyncio

    from tests.unit.test_work_ingress import _TalkingProcess

    process = _TalkingProcess()
    agent.process = process
    reader = asyncio.create_task(agent._read_stdout())
    try:
        pending = asyncio.create_task(agent.ask("Rassemble les vols.", timeout_s=5, conversation_scope=SCOPE))
        while agent._pending_uuid is None:
            await asyncio.sleep(0)
        uuid = agent._pending_uuid
        process.stdout.push(agent_call("toolu_R", "Rassemble", model="claude-sonnet-5"),
                            async_launched("toolu_R", "r1"), result(uuid))
        answer = await asyncio.wait_for(pending, timeout=2)
        assert answer["ok"] is True
        assert [(event.event_type, event.task_id) for event in events_of(agent)] == [(T.SUBAGENT_STARTED, "toolu_R")]

        # A panel message sent while a scoped question waits makes that question ambiguous.
        second = asyncio.create_task(agent.ask("Et la suite ?", timeout_s=5, conversation_scope=SCOPE))
        while agent._pending_uuid in (None, uuid):
            await asyncio.sleep(0)
        await agent.send("Message du panneau")
        process.stdout.push(agent_call("toolu_Z", "Ambigu", model="claude-sonnet-5"), result(agent._pending_uuid))
        await asyncio.wait_for(second, timeout=2)
        assert [event.task_id for event in events_of(agent)] == ["toolu_R"]
        assert_each_trace_ref_joins_one_line(events_of(agent), lines(tmp_path))
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


def test_a_recording_bug_never_breaks_the_tracker_or_the_agent_stop(agent, tmp_path):
    class Exploding:
        def record(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise RuntimeError("recorder bug")

        def derive_event_id(self, *args, **kwargs):  # noqa: ANN002,ANN003
            return None

    agent.subtasks.conversation_events = Exploding()
    ask(agent)
    feed(agent, agent_call("toolu_E", "Robuste", model="claude-sonnet-5"), async_launched("toolu_E", "e1"),
         result("msg-1"))
    agent.subtasks.process_stopped()  # must not raise
    assert agent.subtasks.tasks()[0].status == "interrupted"
    failures = [line for line in lines(tmp_path) if line["kind"] == "agent.subagent.conversation_event_failed"]
    assert len(failures) == 1 and agent.subtasks.conversation_counts["producer_failed"] == 2


def test_a_cli_that_stops_naming_consumed_messages_is_reported_once_with_its_version(agent, tmp_path):
    """CLI ≥ 2.1.270 always carries `user_message_uuids`; a regression must be visible, sub-agent or not."""
    feed(agent, {"type": "system", "subtype": "init", "model": "claude-opus-5", "session_id": SESSION,
                 "claude_code_version": "2.1.999"})
    unverifiable = {"type": "result", "subtype": "success", "result": "ok", "session_id": SESSION}
    for uuid in ("msg-1", "msg-2"):
        ask(agent, uuid=uuid)  # no sub-agent launched at all
        feed(agent, unverifiable)
    warnings = [line for line in lines(tmp_path) if line["kind"] == "agent.subagent.attribution_unverifiable"]
    assert len(warnings) == 1 and warnings[0]["level"] == "warning"
    assert warnings[0]["data"]["cli_version"] == "2.1.999"
    assert agent.subtasks.conversations.unverifiable_results == 2


def test_results_of_unscoped_turns_never_raise_the_unverifiable_warning(agent, tmp_path):
    feed(agent, {"type": "result", "subtype": "success", "result": "ok", "session_id": SESSION})
    assert not [line for line in lines(tmp_path) if line["kind"] == "agent.subagent.attribution_unverifiable"]
