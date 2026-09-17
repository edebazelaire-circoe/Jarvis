"""Tool spans and rejected-turn failures recorded by `RealtimeConversationBridge` (Slice 03b).

Tool journal lines hold raw `arguments` / `result`: the events carry only the
tool name, a status token and a duration, and join those lines by
`conversation_event_id` alone.
"""

from __future__ import annotations

import asyncio
import json

from jarvis.domain.conversation_events import (
    ConversationEventType as T,
    encode_conversation_event,
    reconstruct_conversation,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.conversation_event_forwarder import PRODUCER_REALTIME_AUDIO
from jarvis.runtime.realtime_audio import RealtimeConversationBridge
from tests.fakes.conversation_events import assert_each_trace_ref_joins_one_line, queued, recording_forwarder
from tests.unit.test_v2_brain_migration import (
    CLAUDE_TOOL,
    TIMEOUT_S,
    BrainCoreDouble,
    QueueSession,
    RecordingJournal,
    SilentAudio,
)


def bridge_with_events(core, session, journal, *, continuous=True):  # noqa: ANN001
    forwarder = recording_forwarder()
    bridge = RealtimeConversationBridge(
        core=core, session=session, conversation_id="conv-1", audio=SilentAudio(), on_addressed=lambda: None,
        on_mute=lambda: None, auto_turn=True, continuous=continuous, journal=journal,
        conversation_events=forwarder,
    )
    return bridge, forwarder


async def run_pushes(bridge, session, *pushes):  # noqa: ANN001
    running = asyncio.create_task(bridge.run())
    for message_type, payload in pushes:
        await session.push(message_type, **payload)
    await session.stop()
    await asyncio.wait_for(running, timeout=TIMEOUT_S)


async def test_a_tool_call_is_one_redacted_span_joined_to_its_two_journal_lines():
    core, session, journal = BrainCoreDouble(), QueueSession(), RecordingJournal()
    bridge, forwarder = bridge_with_events(core, session, journal)
    await run_pushes(bridge, session, ("realtime.tool_call", {
        "call_id": "call-1", "name": "reminder_create", "arguments": {"message": "PRIVATE argument"}}))

    events = queued(forwarder)
    assert [event.event_type for event in events] == [T.TOOL_CALL_STARTED, T.TOOL_CALL_FINISHED]
    started, finished = events
    assert {event.producer for event in events} == {PRODUCER_REALTIME_AUDIO}
    assert started.span_id == finished.span_id == "call-1"
    assert finished.started_at == started.started_at
    attributes = dict(finished.attributes)
    assert attributes["tool_name"] == "reminder_create" and attributes["arguments_redacted"] is True
    assert attributes["status"] == "refused" and isinstance(attributes["duration_ms"], int)
    assert set(attributes) <= {"tool_name", "arguments_redacted", "status", "duration_ms", "error_class"}
    # Nothing of the arguments or of the result leaves in the events.
    wire = json.dumps([encode_conversation_event(event) for event in events])
    assert "PRIVATE" not in wire and "surface_tool_forbidden" not in wire
    for event in events:
        assert event.content is None and event.trace_ref.join_keys == ()
    assert_each_trace_ref_joins_one_line(events, journal.events)
    [item] = reconstruct_conversation(events)
    assert item.status == "finished" and item.ended_at is not None


async def test_a_duplicate_tool_announcement_records_nothing_more():
    core, session, journal = BrainCoreDouble(), QueueSession(), RecordingJournal()
    bridge, forwarder = bridge_with_events(core, session, journal)
    call = ("realtime.tool_call", {"call_id": "call-1", "name": CLAUDE_TOOL, "arguments": {"request": "x"}})
    await run_pushes(bridge, session, call, call)
    assert [event.event_type for event in queued(forwarder)] == [T.TOOL_CALL_STARTED, T.TOOL_CALL_FINISHED]
    assert_each_trace_ref_joins_one_line(queued(forwarder), journal.events)


async def test_a_tool_that_raises_still_closes_its_span_and_the_error_propagates_unchanged():
    class ExplodingCore(BrainCoreDouble):
        async def call_tool(self, name, arguments, *, conversation_id):  # noqa: ANN001
            raise RuntimeError("PRIVATE tool failure")

    core, session, journal = ExplodingCore(), QueueSession(), RecordingJournal()
    bridge, forwarder = bridge_with_events(core, session, journal, continuous=False)
    running = asyncio.create_task(bridge.run())
    await session.push("realtime.tool_call", call_id="call-9", name="reminder_create", arguments={})
    await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), timeout=TIMEOUT_S)
    assert isinstance(running.exception(), RuntimeError)  # business behaviour unchanged: the error goes on

    started, finished = queued(forwarder)
    assert finished.event_type is T.TOOL_CALL_FINISHED and finished.trace_ref is None  # no tool.result line
    assert dict(finished.attributes)["status"] == "failed"
    assert dict(finished.attributes)["error_class"] == "RuntimeError"
    assert "PRIVATE" not in repr(encode_conversation_event(finished))
    assert_each_trace_ref_joins_one_line([started, finished], journal.events)


async def test_a_tool_call_without_call_id_records_nothing():
    core, session, journal = BrainCoreDouble(), QueueSession(), RecordingJournal()
    bridge, forwarder = bridge_with_events(core, session, journal)
    await run_pushes(bridge, session, ("realtime.tool_call", {"call_id": "", "name": CLAUDE_TOOL, "arguments": {}}))
    assert queued(forwarder) == [] and journal.of("tool.result")


async def test_a_turn_core_refuses_is_a_system_failure_without_text_or_raw_error():
    core = BrainCoreDouble(reject=CoreProtocolError(404, "not_found", "PRIVATE conversation detail"))
    session, journal = QueueSession(), RecordingJournal()
    bridge, forwarder = bridge_with_events(core, session, journal)
    await run_pushes(bridge, session, ("realtime.transcript", {"text": "Jarvis, relis mes mails.", "item_id": "item-1"}))

    [failure] = queued(forwarder)
    assert failure.event_type is T.SYSTEM_FAILURE and failure.correlation_id == "realtime:conv-1:item-1"
    assert dict(failure.attributes) == {"code": "not_found", "reason": "brain_turn_rejected",
                                        "error_class": "CoreProtocolError", "status": 404}
    assert failure.content is None
    wire = repr(encode_conversation_event(failure))
    assert "PRIVATE" not in wire and "relis mes mails" not in wire
    assert_each_trace_ref_joins_one_line([failure], journal.events)


async def test_a_deferred_turn_during_core_shutdown_is_not_a_failure_event():
    core = BrainCoreDouble(reject=CoreProtocolError(503, "core_stopping", "arrêt"))
    session, journal = QueueSession(), RecordingJournal()
    bridge, forwarder = bridge_with_events(core, session, journal)
    await run_pushes(bridge, session, ("realtime.transcript", {"text": "Jarvis, relis mes mails.", "item_id": "item-1"}))
    assert queued(forwarder) == [] and len(journal.of("voice.brain_turn_deferred")) == 1


async def test_a_double_fault_in_recording_never_masks_the_tool_error():
    class ExplodingCore(BrainCoreDouble):
        async def call_tool(self, name, arguments, *, conversation_id):  # noqa: ANN001
            raise RuntimeError("tool failure")

    class Exploding:
        def record(self, *args, **kwargs):  # noqa: ANN002,ANN003
            raise ValueError("recorder bug")

    class FailingJournal(RecordingJournal):
        def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
            if kind == "voice.conversation_events.producer_failed":
                raise OSError("disk full")
            super().emit(kind, message, level=level, data=data)

    core, session, journal = ExplodingCore(), QueueSession(), FailingJournal()
    bridge, _ = bridge_with_events(core, session, journal, continuous=False)
    bridge.conversation_events = Exploding()
    running = asyncio.create_task(bridge.run())
    await session.push("realtime.tool_call", call_id="call-3", name="reminder_create", arguments={})
    await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), timeout=TIMEOUT_S)
    assert isinstance(running.exception(), RuntimeError) and str(running.exception()) == "tool failure"
