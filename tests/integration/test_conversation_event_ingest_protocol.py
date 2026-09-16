"""`POST /v1/conversation-events` over the real loopback protocol (Slice 03a).

Chain: `LocalCoreClient.append_conversation_events` -> HTTP -> `LocalProtocolServer`
-> `ConversationEventEmitter.append_now` -> SQLite store.
"""

from __future__ import annotations

import socket

import aiohttp
import pytest

from jarvis.core.conversation_event_emitter import INGEST_REJECTED_KIND
from jarvis.core.v2_app import JarvisCoreApplication
from jarvis.domain.conversation_event_ingest import encode_conversation_event_batch
from jarvis.domain.conversation_event_store import AppendStatus, ConversationEventStoreError
from jarvis.domain.conversation_events import ConversationEventError, ConversationEventType as T, encode_conversation_event
from jarvis.domain.v2 import PROTOCOL_VERSION
from jarvis.protocol.client import CoreProtocolError, LocalCoreClient
from jarvis.protocol.server import LocalProtocolServer
from tests.fakes.conversation_events import RecordingDiagnostics, make_event, wait_emitter_settled

TOKEN = "e" * 48
VOICE = "voice.speech_scheduler"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def core_stack(tmp_path):
    port = free_port()
    diagnostics = RecordingDiagnostics()
    core = JarvisCoreApplication(data_root=tmp_path / "data", diagnostics=diagnostics)
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        yield core, client, port, diagnostics
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def raw_post(port: int, payload, *, token: str = TOKEN, path: str = "/v1/conversation-events") -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{port}{path}", json=payload, headers=headers) as response:
            return response.status, await response.json()


def mouth(source: str, **fields):
    return make_event(T.MOUTH_SPEECH_STARTED, source, producer=VOICE, **fields)


async def test_client_batch_is_stored_with_per_event_status(core_stack):
    core, client, _, _ = core_stack
    started = mouth("s1", content="Bonjour.")
    completed = make_event(T.MOUTH_SPEECH_COMPLETED, "s1-done", producer=VOICE, ms=900, speech_id="speech-s1",
                           span_id="speech-s1", correlation_id="corr-s1")
    results = await client.append_conversation_events([started, completed])
    assert [r.status for r in results] == [AppendStatus.APPENDED, AppendStatus.APPENDED]
    assert results[0].sequence < results[1].sequence

    conflicting = mouth("s1", content="Autre texte.")
    again = await client.append_conversation_events([started, conflicting])
    assert [(r.status, r.sequence) for r in again] == [(AppendStatus.DUPLICATE, results[0].sequence),
                                                        (AppendStatus.CONFLICT, results[0].sequence)]
    page = await core.conversation_events.list_conversation_events("conv-a")
    assert [item.event.content for item in page.events] == ["Bonjour.", None]
    counters = core.conversation_event_emitter.counters
    assert (counters.ingest_appended, counters.ingest_duplicates, counters.ingest_conflicts) == (2, 1, 1)
    # ingestion is acknowledged to its caller: the queue accounting stays untouched and settles
    assert (counters.enqueued, counters.appended, counters.duplicates, counters.conflicts) == (0, 0, 0, 0)
    await wait_emitter_settled(core.conversation_event_emitter, timeout_s=1.0)


async def test_route_requires_the_session_token(core_stack):
    _, _, port, _ = core_stack
    status, body = await raw_post(port, encode_conversation_event_batch([mouth("s1")]), token="x" * 48)
    assert status == 401 and body["error"]["code"] == "unauthorized"


def encoded(event) -> dict:
    return encode_conversation_event(event)


@pytest.mark.parametrize(("payload", "fragment"), [
    ({"schema_version": 1, "events": []}, "1 to 32"),
    ({"schema_version": 1, "events": [encoded(mouth(f"s{i}")) for i in range(33)]}, "1 to 32"),
    ({"schema_version": 2, "events": [encoded(mouth("s1"))]}, "schema_version"),
    ({"events": [encoded(mouth("s1"))]}, "exactly the fields"),
    ({"schema_version": 1, "events": [encoded(mouth("s1"))], "extra": True}, "exactly the fields"),
    ({"schema_version": 1, "events": "nope"}, "must be a list"),
    ([1, 2], "JSON object"),
    ({"schema_version": 1, "events": [{**encoded(mouth("s1")), "extra_field": "SECRET_VALUE"}]}, "events[0]: unknown field(s): extra_field"),
    ({"schema_version": 1, "events": [encoded(mouth("s1")), {**encoded(mouth("s2")),
      "attributes": {"reasoning": "SECRET_REASONING_VALUE"}}]}, "events[1]: event.attributes.reasoning: forbidden"),
    ({"schema_version": 1, "events": [{**encoded(mouth("s1")), "content": "x" * 9000}]}, "events[0]: content exceeds"),
    ({"schema_version": 1, "events": [encoded(make_event(T.USER_TRANSCRIPT_ACCEPTED, "u1", producer="voice.realtime_audio",
                                                        content="SECRET_USER_TEXT"))]}, "Core-owned"),
    ({"schema_version": 1, "events": [encoded(make_event(T.MOUTH_SPEECH_STARTED, "m1", producer="core.speech"))]}, "Core-owned"),
    ({"schema_version": 1, "events": [encoded(make_event(T.BRAIN_TURN_ACCEPTED, "b1", producer="voice.x"))]}, "Core-owned"),
])
async def test_invalid_batches_are_rejected_whole_without_echoing_values(core_stack, payload, fragment):
    core, _, port, diagnostics = core_stack
    status, body = await raw_post(port, payload)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert fragment in body["error"]["message"]
    assert "SECRET" not in body["error"]["message"] and "x" * 50 not in body["error"]["message"]
    page = await core.conversation_events.list_conversation_events("conv-a")
    assert page.events == ()  # nothing appended, not even the valid events of the batch
    if isinstance(payload, dict):
        rejected = [entry for entry in diagnostics.entries if entry[0] == INGEST_REJECTED_KIND]
        assert len(rejected) == 1 and "SECRET" not in repr(rejected)


async def test_non_json_body_is_a_400(core_stack):
    _, _, port, _ = core_stack
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Jarvis-Protocol": str(PROTOCOL_VERSION)}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{port}/v1/conversation-events", data=b"{not json",
                                headers=headers) as response:
            assert response.status == 400


async def test_client_validates_before_any_network_call(core_stack):
    _, client, _, _ = core_stack
    with pytest.raises(ConversationEventError):
        await client.append_conversation_events([])
    with pytest.raises(ConversationEventError):
        await client.append_conversation_events([mouth(f"s{i}") for i in range(33)])


async def test_store_failure_is_a_retryable_503(core_stack, monkeypatch):
    core, client, _, diagnostics = core_stack

    async def broken(events):
        raise ConversationEventStoreError("conversation event append failed: OperationalError: database is locked")

    monkeypatch.setattr(core.conversation_events, "append_many", broken)
    with pytest.raises(CoreProtocolError) as error:
        await client.append_conversation_events([mouth("s1")])
    assert (error.value.status, error.value.code) == (503, "conversation_events_unavailable")
    assert core.conversation_event_emitter.counters.ingest_failures == 1
    assert any(entry[0] == "core.conversation_events.append_failed" for entry in diagnostics.entries)
    monkeypatch.undo()
    results = await client.append_conversation_events([mouth("s1")])  # the same batch, retried
    assert [r.status for r in results] == [AppendStatus.APPENDED]


async def test_legacy_user_turn_ingress_records_the_accepted_transcript(core_stack):
    core, client, _, _ = core_stack
    conversation = await client.create_conversation()
    turn = await client.append_turn(conversation["id"], kind="user", content="Allume la lumière.", correlation_id="legacy-1")
    await client.append_turn(conversation["id"], kind="assistant", content="C'est fait.", correlation_id="legacy-1")
    await wait_emitter_settled(core.conversation_event_emitter)
    page = await core.conversation_events.list_conversation_events(conversation["id"])
    assert [(item.event.event_type, item.event.turn_id, item.event.content) for item in page.events] == [
        (T.USER_TRANSCRIPT_ACCEPTED, turn["id"], "Allume la lumière.")]


async def test_the_largest_contract_valid_batch_fits_the_core_body_limit(core_stack):
    import json

    from jarvis.domain.conversation_event_ingest import MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES
    from tests.fakes.conversation_events import worst_case_ingest_batch

    core, client, _, _ = core_stack
    batch = worst_case_ingest_batch()
    wire = len(json.dumps(encode_conversation_event_batch(batch)).encode())  # aiohttp's own encoding
    assert 2**20 < wire < MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES  # above aiohttp's 1 MiB default
    results = await client.append_conversation_events(batch)
    assert [r.status for r in results] == [AppendStatus.APPENDED] * 32
    stored = await core.conversation_events.get_event(batch[-1].event_id)
    assert stored is not None and stored.event == batch[-1]


async def test_a_body_above_the_limit_is_a_413_core_protocol_error(tmp_path, monkeypatch):
    import jarvis.protocol.server as protocol_server

    monkeypatch.setattr(protocol_server, "MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES", 64 * 1024)
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        with pytest.raises(CoreProtocolError) as error:  # text/plain 413 from aiohttp, not a ContentTypeError
            await client.append_conversation_events([mouth("big", content="x" * 8000) for _ in range(1)] +
                                                    [mouth(f"b{i}", content="y" * 8000) for i in range(9)])
        assert error.value.status == 413
        assert (await core.conversation_events.list_conversation_events("conv-a")).events == ()
    finally:
        await client.close()
        await server.stop()
        await core.stop()


async def test_ingestion_after_core_stop_is_a_retryable_503(tmp_path):
    port = free_port()
    core = JarvisCoreApplication(data_root=tmp_path / "data")
    await core.start()
    server = LocalProtocolServer(core, host="127.0.0.1", port=port, token=TOKEN)
    await server.start()
    client = LocalCoreClient(host="127.0.0.1", port=port, token=TOKEN)
    try:
        await core.stop()
        with pytest.raises(CoreProtocolError) as error:
            await client.append_conversation_events([mouth("late")])
        assert (error.value.status, error.value.code) == (503, "conversation_events_unavailable")
        # the repository closed underneath a live emitter: same 503, never a 500
        core.conversation_event_emitter._stopping = False
        with pytest.raises(CoreProtocolError) as error:
            await client.append_conversation_events([mouth("late")])
        assert (error.value.status, error.value.code) == (503, "conversation_events_unavailable")
    finally:
        await client.close()
        await server.stop()
