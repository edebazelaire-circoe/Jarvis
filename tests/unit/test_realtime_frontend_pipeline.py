"""Task05 composition with production normalization, dispatcher and Core ledger.

Wire and client transport are controlled; no test claims actual device drain.
"""
from __future__ import annotations

import asyncio
import base64
import uuid

import pytest

from jarvis.adapters.jsonl_history import JsonlHistoryStore
from jarvis.adapters.sqlite_state import SQLiteStateRepository
from jarvis.core.v2_services import ConversationService
from jarvis.core.voice_ledger import VoiceLedgerService
from jarvis.domain.voice_frontend import FrontendState
from jarvis.domain.v2 import SpeechRequest
from jarvis.adapters.openai_realtime import OUTPUT_ID_METADATA_KEY, SPEECH_ID_METADATA_KEY
from jarvis.runtime.realtime_frontend_session import RealtimeFrontendSession
from tests.unit.test_realtime_frontend_adapter import started


class LedgerClient:
    """Test transport only; every command enters the production Core owner."""
    def __init__(self, ledger):
        self.ledger = ledger
        self.batches = []
        self.fail = False

    async def bind_voice_session(self, conversation_id, session_id):
        return await self.ledger.bind_session(conversation_id, session_id)

    async def submit_voice_observations(self, conversation_id, session_id, events):
        if self.fail:
            raise ConnectionError("offline")
        self.batches.append(events)
        return await self.ledger.ingest(conversation_id, session_id, events)

    async def voice_snapshot(self, conversation_id):
        if self.fail:
            raise ConnectionError("offline")
        return await self.ledger.snapshot(conversation_id)

    async def register_voice_speech(self, conversation_id, correlation, intended_text):
        return await self.ledger.register_speech(conversation_id, correlation, intended_text)


@pytest.fixture
async def pipeline(tmp_path):
    state = SQLiteStateRepository(tmp_path / "state.db")
    await state.initialize()
    history = JsonlHistoryStore(tmp_path / "history")
    conversations = ConversationService(state, history)
    conversation = await conversations.create()
    ledger = VoiceLedgerService(conversations)
    client = LedgerClient(ledger)
    frontend, wire = await started()
    facade = RealtimeFrontendSession(frontend, "session")
    await facade.attach_core(client, conversation.id)
    received = asyncio.Queue()
    async def consume():
        async for event in facade.events():
            received.put_nowait(event)
    reader = asyncio.create_task(consume())
    yield facade, wire, client, conversation.id, received, history
    try:
        client.fail = False
        await facade.close()
        results = await asyncio.gather(reader, return_exceptions=True)
        assert results == [None] or (len(results) == 1 and str(results[0]) == "voice_observation_failed")
    finally:
        await state.close()


async def until(queue, kind):
    while True:
        event = await asyncio.wait_for(queue.get(), 1)
        if event.message_type == kind:
            return event


async def test_generated_transcript_and_device_lower_bound_never_become_heard(pipeline):
    facade, wire, client, conversation, events, history = pipeline
    wire.push(type="response.created", response={"id": "r"})
    wire.push(type="response.output_audio.delta", response_id="r", item_id="audio",
              delta=base64.b64encode(bytes(4800)).decode())
    wire.push(type="response.output_audio_transcript.done", response_id="r", item_id="audio", transcript="Generated words")
    audio = await until(events, "realtime.audio")
    # Mirrors SoundDevice's conservative written-minus-latency evidence. This
    # is deliberately not an injected whole-transcript confirmation.
    facade.observe_playback(audio.payload, played_ms=60, written_ms=100)
    wire.push(type="response.done", response={"id": "r", "status": "completed"})
    done = await until(events, "realtime.response_done")
    facade.observe_playback(done.payload, played_ms=60, written_ms=100, terminal=True)
    await facade._dispatcher.flush()
    snapshot = (await client.voice_snapshot(conversation))["snapshot"]
    speech = snapshot["speeches"][0]
    assert speech["generated"][0]["text"] == "Generated words"
    assert speech["confirmed_text"] is None and speech["played_ms"] == 60
    assert speech["state"] == "unknown"
    assert (await client.ledger.context(conversation))["recent_turns"] == []
    assert not await history.read(conversation_id=conversation)
    all_events = [event for batch in client.batches for event in batch]
    assert all(event["payload"]["kind"] != "assistant.audio_chunk" for event in all_events)
    assert "pcm" not in repr(all_events)


async def input_final(wire, events, item, previous=None):
    wire.push(type="input_audio_buffer.committed", item_id=item, previous_item_id=previous)
    wire.push(type="conversation.item.input_audio_transcription.delta", item_id=item, delta="provisional")
    wire.push(type="conversation.item.input_audio_transcription.completed", item_id=item, transcript=f"Accepted {item}")
    await until(events, "realtime.transcript")


async def test_many_rejected_inputs_do_not_fill_core_then_accepted_order_skips_rejected(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    for index in range(80):
        item = f"ambient-{index}"
        await input_final(wire, events, item)
        facade.discard_transcript(item)
    await facade._dispatcher.flush()
    assert (await client.voice_snapshot(conversation))["snapshot"]["users"] == []
    await input_final(wire, events, "a")
    facade.admit_transcript("a")
    await input_final(wire, events, "b", "a")
    facade.discard_transcript("b")
    await input_final(wire, events, "c", "b")
    facade.admit_transcript("c")
    await facade._dispatcher.flush()
    snapshot = (await client.voice_snapshot(conversation))["snapshot"]
    turn = lambda item: str(uuid.uuid5(uuid.NAMESPACE_URL, f"session/input/{item}"))
    assert snapshot["active_turn_id"] == turn("c")
    assert snapshot["turns"][-1]["previous_turn_id"] == turn("a")
    # Original provider adjacency remains on the admitted Open observation.
    opened = [event for batch in client.batches for event in batch if event["payload"]["kind"] == "user.turn_opened"][-1]
    assert opened["correlation"]["previous_provider_input_id"] == "b"


async def test_provider_finals_arrive_b_before_a_without_rewinding_active_turn(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    wire.push(type="input_audio_buffer.committed", item_id="a", previous_item_id=None)
    wire.push(type="input_audio_buffer.committed", item_id="b", previous_item_id="a")
    wire.push(type="conversation.item.input_audio_transcription.completed", item_id="b", transcript="B")
    await until(events, "realtime.transcript")
    facade.admit_transcript("b")
    wire.push(type="conversation.item.input_audio_transcription.completed", item_id="a", transcript="A")
    await until(events, "realtime.transcript")
    facade.admit_transcript("a")
    await facade._dispatcher.flush()
    snapshot = (await client.voice_snapshot(conversation))["snapshot"]
    assert snapshot["active_turn_id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, "session/input/b"))


async def test_failed_observation_transport_reconciles_only_after_real_close(pipeline):
    facade, wire, client, conversation, events, _ = pipeline
    await facade._dispatcher.flush()
    client.fail = True
    wire.push(type="response.created", response={"id": "r"})
    await until(events, "realtime.output_started")
    with pytest.raises(RuntimeError, match="voice_observation_failed"):
        await facade._dispatcher.flush()
    with pytest.raises(ConnectionError):
        await facade.close()
    assert wire.closed
    client.fail = False
    await facade.close()
    snapshot = (await client.voice_snapshot(conversation))["snapshot"]
    assert snapshot["lifecycle"] == FrontendState.STOPPED.value
    rebound = await client.bind_voice_session(conversation, "next-session")
    assert rebound["result"]["disposition"] == "applied"


async def test_spoken_request_preserves_source_turn_and_opaque_backend_work(pipeline):
    facade, wire, client, conversation, events, history = pipeline
    await input_final(wire, events, "input")
    facade.admit_transcript("input", source_correlation_id="brain-correlation")
    request = SpeechRequest(conversation, "Exact requested words", correlation_id="brain-correlation", work_id="brain-work")
    output = await facade.speak(request)
    wire.push(type="response.created", response={"id": "provider-response", "metadata": {
        OUTPUT_ID_METADATA_KEY: output, SPEECH_ID_METADATA_KEY: request.id}})
    wire.push(type="response.output_audio_transcript.done", response_id="provider-response", item_id="audio", transcript="Divergent generated words")
    await until(events, "realtime.assistant_transcript")
    await facade._dispatcher.flush()
    snapshot = (await client.voice_snapshot(conversation))["snapshot"]
    speech = snapshot["speeches"][0]
    assert speech["intended_text"] == "Exact requested words"
    assert speech["generated"][0]["text"] == "Divergent generated words"
    assert speech["correlation"]["turn_id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, "session/input/input"))
    assert speech["correlation"]["source_correlation_id"] == "brain-correlation"
    assert speech["correlation"]["backend_work_id"] == "brain-work"
    assert speech["correlation"]["task_id"] is None and snapshot["tasks"] == []
    assert not await history.read(conversation_id=conversation)


async def test_legacy_undelivered_rescue_cannot_write_assistant_history_on_canonical_path(pipeline):
    from tests.unit.test_v2_brain_migration import BrainCoreDouble, make_bridge
    facade, *_ = pipeline
    core = BrainCoreDouble()
    bridge = make_bridge(core, facade, continuous=False)
    bridge._undelivered_answer = "Available backend result, never played"
    await bridge._rescue_undelivered_answer()
    assert core.appended == []
