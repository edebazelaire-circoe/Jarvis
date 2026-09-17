"""`ConversationEventForwarder`: bounded, non-blocking, batched delivery to Core (Slice 03b).

Transport doubles only: the real loopback route is exercised in
`tests/integration/test_conversation_event_timeline.py`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from jarvis.domain.conversation_event_ingest import ConversationEventAppendResponseError
from jarvis.domain.conversation_events import ConversationEventError, ConversationEventType as T
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.conversation_event_forwarder import (
    EVENT_DROPPED_KIND,
    EVENT_INVALID_KIND,
    FORWARDER_REJECTED_KIND,
    FORWARDER_RESTORED_KIND,
    FORWARDER_STOPPED_KIND,
    FORWARDER_UNAVAILABLE_KIND,
    ConversationEventForwarder,
    ConversationEventsRejected,
    CoreConversationEventTransport,
)
from tests.fakes.conversation_events import FakeEventTransport, queued

AT = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
PRODUCER = "voice.speech_scheduler"


class Journal:
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[dict] = []
        self.fail = fail

    def emit(self, kind, message, *, level="info", data=None):  # noqa: ANN001
        if self.fail:
            raise OSError("disk full")
        self.entries.append({"kind": kind, "message": message, "level": level, "data": dict(data or {})})

    def kinds(self) -> list[str]:
        return [entry["kind"] for entry in self.entries]


def queued_speech(forwarder, index: int, **fields) -> str | None:
    return forwarder.record(T.MOUTH_SPEECH_QUEUED, producer=PRODUCER, conversation_id="conv-1",
                            source_ids=(f"speech-{index}",), occurred_at=AT, correlation_id="corr-1",
                            speech_id=f"speech-{index}", **fields)


def settled(forwarder) -> bool:
    c = forwarder.counters
    return c.enqueued == (c.appended + c.duplicates + c.conflicts + c.dropped_rejected + c.dropped_shutdown
                          + forwarder.pending_count)


def make(transport=None, journal=None, **options) -> ConversationEventForwarder:
    return ConversationEventForwarder(transport=transport or FakeEventTransport(), journal=journal, **options)


async def until(condition, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "condition never reached"
        await asyncio.sleep(0.005)


# ----------------------------------------------------------------- record()

def test_record_validates_queues_and_returns_the_event_id_without_io():
    transport = FakeEventTransport()
    forwarder = make(transport)
    event_id = queued_speech(forwarder, 1)
    assert event_id is not None and event_id.startswith("cev-")
    assert [event.event_id for event in queued(forwarder)] == [event_id]
    assert transport.batches == [] and forwarder.counters.enqueued == 1


def test_an_invalid_fact_is_counted_and_diagnosed_once_never_raised():
    journal = Journal()
    forwarder = make(journal=journal)
    for _ in range(3):
        assert forwarder.record(T.MOUTH_SPEECH_STARTED, producer=PRODUCER, conversation_id="conv-1",
                                source_ids=("s",), occurred_at=AT, correlation_id="corr-1",
                                speech_id="s") is None  # span_id missing
    assert forwarder.record(T.TOOL_CALL_STARTED, producer=PRODUCER, conversation_id="conv-1", source_ids=("c",),
                            occurred_at="not a time", span_id="c") is None  # type: ignore[arg-type]
    assert forwarder.counters.invalid == 4 and forwarder.pending_count == 0
    invalid = [entry for entry in journal.entries if entry["kind"] == EVENT_INVALID_KIND]
    assert len(invalid) == 2  # once per (event type, producer)
    assert invalid[0]["data"]["detail"] == "span_id is required for mouth.speech.started"


def test_forbidden_payloads_are_refused_at_record_time():
    forwarder = make()
    assert forwarder.record(T.TOOL_CALL_STARTED, producer="voice.realtime_audio", conversation_id="conv-1",
                            source_ids=("call-1",), occurred_at=AT, span_id="call-1",
                            attributes={"arguments": {"query": "PRIVATE"}}) is None
    assert forwarder.counters.invalid == 1


def test_the_same_fact_recorded_twice_is_queued_once_and_only_the_first_call_gets_the_id():
    forwarder = make()
    first = queued_speech(forwarder, 1)
    assert queued_speech(forwarder, 1) is None
    assert forwarder.counters.repeated == 1 and len(queued(forwarder)) == 1 and first is not None


def test_overflow_drops_the_newest_keeps_the_causal_prefix_and_reports_once_per_episode():
    journal = Journal()
    forwarder = make(journal=journal, capacity=3)
    ids = [queued_speech(forwarder, index) for index in range(6)]
    assert ids[3:] == [None, None, None] and all(ids[:3])
    assert [event.speech_id for event in queued(forwarder)] == ["speech-0", "speech-1", "speech-2"]
    assert forwarder.counters.dropped_queue_full == 3
    assert journal.kinds().count(EVENT_DROPPED_KIND) == 1


def test_a_failing_journal_is_counted_never_raised():
    forwarder = make(journal=Journal(fail=True), capacity=1)
    queued_speech(forwarder, 1)
    assert queued_speech(forwarder, 2) is None
    assert forwarder.counters.diagnostic_failures == 1


# ---------------------------------------------------------------- sending

async def test_flush_sends_batches_of_at_most_32_and_counts_results():
    transport = FakeEventTransport()
    forwarder = make(transport)
    for index in range(70):
        queued_speech(forwarder, index)
    assert await forwarder.flush() is True
    assert [len(batch) for batch in transport.batches] == [32, 32, 6]
    assert forwarder.counters.appended == 70 and forwarder.pending_count == 0 and settled(forwarder)


async def test_a_rejected_batch_is_dropped_counted_and_reported_once_per_series():
    transport = FakeEventTransport()
    journal = Journal()
    forwarder = make(transport, journal)
    transport.failures = [ConversationEventsRejected("400 invalid_request"), ConversationEventsRejected("400")]
    queued_speech(forwarder, 1)
    assert await forwarder.flush() is True
    queued_speech(forwarder, 2)
    assert await forwarder.flush() is True
    assert forwarder.counters.dropped_rejected == 2 and transport.batches == []
    assert journal.kinds().count(FORWARDER_REJECTED_KIND) == 1
    queued_speech(forwarder, 3)
    await forwarder.flush()  # accepted: closes the series
    transport.failures = [ConversationEventsRejected("400")]
    queued_speech(forwarder, 4)
    await forwarder.flush()
    assert journal.kinds().count(FORWARDER_REJECTED_KIND) == 2 and settled(forwarder)


async def test_core_unavailable_keeps_the_batch_reports_once_and_recovers_with_the_same_events():
    transport = FakeEventTransport()
    journal = Journal()
    forwarder = make(transport, journal)
    transport.failures = [CoreProtocolError(503, "conversation_events_unavailable", "down"), ConnectionError("refused")]
    event_id = queued_speech(forwarder, 1)
    assert await forwarder.flush() is False
    assert await forwarder.flush() is False
    assert forwarder.pending_count == 1
    assert await forwarder.flush() is True
    assert [event.event_id for event in transport.sent()] == [event_id]
    assert journal.kinds().count(FORWARDER_UNAVAILABLE_KIND) == 1
    assert journal.kinds().count(FORWARDER_RESTORED_KIND) == 1 and settled(forwarder)


async def test_the_send_loop_backs_off_exponentially_instead_of_storming_a_down_core():
    class Down(FakeEventTransport):
        attempts = 0

        async def post(self, events):
            Down.attempts += 1
            raise ConnectionError("refused")

    forwarder = make(Down(), flush_interval_s=0, retry_min_s=0.02, retry_max_s=0.08)
    queued_speech(forwarder, 1)
    forwarder.start()
    await asyncio.sleep(0.5)
    await forwarder.aclose()
    # 0.02 + 0.04 + 0.08 * n: at most ~8 attempts in 0.5 s (a tight loop would make thousands).
    assert 2 <= Down.attempts <= 10
    assert forwarder.counters.dropped_shutdown == 1 and settled(forwarder)


async def test_the_loop_delivers_on_its_own_after_a_linger():
    transport = FakeEventTransport()
    forwarder = make(transport, flush_interval_s=0.01)
    forwarder.start()
    try:
        for index in range(5):
            queued_speech(forwarder, index)
        await until(lambda: forwarder.counters.appended == 5)
        assert len(transport.batches) == 1  # one burst, one POST
    finally:
        await forwarder.aclose()


async def test_close_drains_within_its_bound_then_counts_and_journals_the_rest():
    transport = FakeEventTransport()
    transport.hang = True
    journal = Journal()
    forwarder = make(transport, journal, flush_interval_s=0, close_timeout_s=0.05)
    forwarder.start()
    for index in range(3):
        queued_speech(forwarder, index)
    await asyncio.sleep(0.02)
    await asyncio.wait_for(forwarder.aclose(), timeout=2)
    assert forwarder.counters.dropped_shutdown == 3 and forwarder.pending_count == 0 and transport.closed
    stopped = [entry for entry in journal.entries if entry["kind"] == FORWARDER_STOPPED_KIND]
    assert stopped[0]["data"]["dropped_shutdown"] == 3
    assert queued_speech(forwarder, 9) is None and forwarder.counters.dropped_closed == 1
    assert settled(forwarder)


async def test_close_flushes_what_is_queued_when_core_answers():
    transport = FakeEventTransport()
    forwarder = make(transport, flush_interval_s=10)
    forwarder.start()
    queued_speech(forwarder, 1)
    await forwarder.aclose()
    assert forwarder.counters.appended == 1 and forwarder.counters.dropped_shutdown == 0


# ------------------------------------------------------------- transport

class ScriptedClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.closed = False

    async def append_conversation_events(self, events):
        raise self.error

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(("error", "expected"), [
    (CoreProtocolError(400, "invalid_request", "events[0]: ..."), ConversationEventsRejected),
    (CoreProtocolError(413, "http_error", "too large"), ConversationEventsRejected),
    (ConversationEventAppendResponseError("conversation event append response does not answer every event"),
     ConversationEventsRejected),
    (ConversationEventError("events[0]: span_id is required"), ConversationEventsRejected),
    # A garbled body while Core restarts is a ValueError too, but worth a retry.
    (json.JSONDecodeError("Expecting value", "<html>", 0), json.JSONDecodeError),
    (UnicodeDecodeError("utf-8", bytes([255]), 0, 1, "invalid start byte"), UnicodeDecodeError),
    (CoreProtocolError(503, "conversation_events_unavailable", "down"), CoreProtocolError),
    (CoreProtocolError(429, "busy", "later"), CoreProtocolError),
    (ConnectionError("refused"), ConnectionError),
])
async def test_transport_maps_refusals_to_drops_and_everything_else_to_retries(tmp_path, error, expected):
    token = tmp_path / "token"
    token.write_text("t" * 48, encoding="utf-8")
    transport = CoreConversationEventTransport(host="127.0.0.1", port=1, token_file=token)
    transport._client = ScriptedClient(error)  # type: ignore[assignment]
    with pytest.raises(expected):
        await transport.post(())
    await transport.close()


async def test_a_401_closes_the_session_so_the_rotated_token_is_read_again(tmp_path):
    token = tmp_path / "token"
    token.write_text("old" * 16, encoding="utf-8")
    transport = CoreConversationEventTransport(host="127.0.0.1", port=1, token_file=token)
    client = ScriptedClient(CoreProtocolError(401, "unauthorized", "token"))
    transport._client = client  # type: ignore[assignment]
    with pytest.raises(CoreProtocolError):
        await transport.post(())
    assert client.closed and transport._client is None
    token.write_text("new" * 16, encoding="utf-8")
    assert transport._connect().token == "new" * 16
    await transport.close()


async def test_a_missing_token_file_is_an_unavailability_not_a_crash(tmp_path):
    transport = CoreConversationEventTransport(host="127.0.0.1", port=1, token_file=tmp_path / "absent")
    forwarder = make(transport)
    queued_speech(forwarder, 1)
    assert await forwarder.flush() is False and forwarder.pending_count == 1
    await forwarder.aclose()


async def test_a_garbled_answer_keeps_the_batch_for_the_next_attempt():
    transport = FakeEventTransport()
    forwarder = make(transport)
    transport.failures = [json.JSONDecodeError("Expecting value", "<html>", 0)]
    event_id = queued_speech(forwarder, 1)
    assert await forwarder.flush() is False and forwarder.counters.dropped_rejected == 0
    assert await forwarder.flush() is True
    assert [event.event_id for event in transport.sent()] == [event_id]
