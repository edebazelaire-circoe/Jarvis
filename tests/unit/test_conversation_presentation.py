import asyncio

import pytest

from jarvis.domain.v2 import ProtocolEnvelope
from jarvis.domain.voice_frontend import VoiceConversationRequest, VoiceCorrelation, VoiceOperation, VoiceOperationStatus, VoiceStopReason
from jarvis.runtime.output_admission import OutputAdmissionState
from tests.fakes.speech_context import context, source
from tests.unit.test_v2_speech_scheduler import (
    CONVERSATION, FakeCore, FakeVoiceSession, RecordingJournal, build_scheduler, wait_for,
)
from tests.unit.test_realtime_frontend_adapter import started, operation


class ConversationSession(FakeVoiceSession):
    def __init__(self):
        super().__init__()
        self.conversations = []
        self.creation_gate = asyncio.Event()
        self.invalidated = []
        self.journal = None
        self.dispatch_seen_at_request = []

    async def request_conversation(self, input_item_ids, *, source, output_id):
        self.dispatch_seen_at_request.append(
            bool(self.journal is not None and self.journal.of("voice.speech.dispatched"))
        )
        self.active_output_id = output_id
        self.conversations.append((input_item_ids, source, output_id))
        await self.creation_gate.wait()
        return output_id

    async def invalidate_unstarted_output(self, output_id):
        self.invalidated.append(output_id)


async def test_future_source_candidate_waits_without_spinning_then_uses_same_output_owner():
    session = ConversationSession()
    journal = RecordingJournal()
    session.journal = journal
    selected = build_scheduler(FakeCore(), session, journal=journal)
    await selected.start()
    try:
        await wait_for(lambda: selected._source_complete)
        assert selected.request_conversation(input_item_ids=("input-B",), source=source("corr-B", epoch=2))
        for _ in range(5):
            await asyncio.sleep(.005)  # Proves the event loop is not starved by pending wakeups.
        assert len(selected._pending) == 1 and not session.conversations
        await selected.handle_core_event(ProtocolEnvelope(message_type="brain.source.changed", payload=context(CONVERSATION, "corr-B", epoch=2)))
        await wait_for(lambda: len(session.conversations) == 1)
        identifiers, origin, output = session.conversations[0]
        assert identifiers == ("input-B",) and origin == source("corr-B", epoch=2)
        dispatched = journal.of("voice.speech.dispatched")
        assert len(dispatched) == 1 and dispatched[0]["data"]["queue_wait_ms"] >= 0
        assert dispatched[0]["data"]["kind"] == "conversation"
        assert session.dispatch_seen_at_request == [True]
        assert selected.output_admission(output).state is OutputAdmissionState.RESERVED
        assert not selected.request_conversation(input_item_ids=("input-B",), source=origin)
        selected.update_speech_context(context(CONVERSATION, "corr-C", epoch=3))
        await wait_for(lambda: output in session.invalidated)
        assert not selected.output_admission(output).begin_write()
        session.creation_gate.set()
        session.active_output_id = None
        await selected.note_output_event(ProtocolEnvelope(message_type="realtime.response_done", payload={"output_id": output, "status": "cancelled"}))
    finally:
        session.creation_gate.set()
        await selected.stop()


async def test_stop_removes_source_waiting_candidate_without_any_send():
    session = ConversationSession()
    selected = build_scheduler(FakeCore(), session)
    await selected.start()
    await wait_for(lambda: selected._source_complete)
    selected.request_conversation(input_item_ids=("future",), source=source("future", epoch=10))
    await asyncio.sleep(.01)
    await selected.stop()
    assert not selected._pending and not session.conversations


async def test_canonical_conversation_uses_exact_references_and_late_creation_is_cancelled():
    frontend, wire = await started()
    gate, sending = asyncio.Event(), asyncio.Event()
    send = wire.send_json
    async def blocked(value):
        await send(value)
        if value["type"] == "response.create":
            sending.set()
            await gate.wait()
    wire.send_json = blocked
    op = VoiceOperation("direct-operation", VoiceCorrelation("session", output_id="reserved", source_correlation_id="source"))
    task = asyncio.create_task(frontend.request_conversation(VoiceConversationRequest(("admitted-A",)), operation=op))
    try:
        await asyncio.wait_for(sending.wait(), 1)
        create = wire.sent[-1]
        assert create["response"]["input"] == [{"type": "item_reference", "id": "admitted-A"}]
        assert "conversation" not in create["response"] and "instructions" not in create["response"]
        assert not any(item["type"] == "conversation.item.create" for item in wire.sent)
        await frontend.invalidate_unstarted_output(operation=op)
        wire.push(type="response.created", response={"id": "response", "metadata": create["response"]["metadata"]})
        await wait_for(lambda: any(item["type"] == "response.cancel" for item in wire.sent))
        assert next(item for item in wire.sent if item["type"] == "response.cancel")["response_id"] == "response"
        gate.set()
        assert (await task).status is VoiceOperationStatus.ACCEPTED
        # Acceptance records a wire send; invalidation remains and cannot authorize audio.
        assert "reserved" in frontend._invalidated_outputs
    finally:
        gate.set()
        await asyncio.gather(task, return_exceptions=True)
        await frontend.stop(VoiceStopReason.USER, operation=operation())
