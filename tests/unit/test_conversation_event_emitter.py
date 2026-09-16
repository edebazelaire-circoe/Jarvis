"""Core Conversation Event emitter: non-blocking, bounded, never raises (Slice 03a)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from jarvis.core.conversation_event_emitter import (
    APPEND_FAILED_KIND,
    APPEND_RECOVERED_KIND,
    EMITTER_STARTED_KIND,
    EMITTER_STOPPED_KIND,
    EVENT_DROPPED_KIND,
    EVENT_INVALID_KIND,
    ConversationEventEmitter,
    journal_ref,
    safe_error_class,
)
from jarvis.domain.conversation_event_store import AppendResult, AppendStatus, ConversationEventStoreError
from jarvis.domain.conversation_events import ConversationEventType as T
from jarvis.domain.conversation_events import TRACE_EVENT_ID_KEY, derive_conversation_event_id
from tests.fakes.conversation_events import (
    BASE, RecordingDiagnostics, make_event, open_store, wait_emitter_settled as wait_settled,
)


class GatedStore:
    """Store double whose appends block until the test opens the gate."""

    def __init__(self, *, fail: int = 0) -> None:
        self.gate = asyncio.Event()
        self.batches: list[tuple[str, ...]] = []
        self.calls = 0
        self.fail = fail

    async def append_many(self, events):
        self.calls += 1
        await self.gate.wait()
        if self.fail:
            self.fail -= 1
            try:
                raise OSError("disk I/O error")
            except OSError as exc:
                raise ConversationEventStoreError("conversation event append failed: OSError") from exc
        self.batches.append(tuple(event.event_id for event in events))
        return tuple(AppendResult(event.event_id, index + 1, AppendStatus.APPENDED) for index, event in enumerate(events))


def user_event(source: str, **fields):
    return make_event(T.USER_TRANSCRIPT_ACCEPTED, source, **fields)


async def test_emit_never_awaits_the_store_even_when_it_is_stuck():
    store = GatedStore()
    diagnostics = RecordingDiagnostics()
    emitter = ConversationEventEmitter(store, diagnostics=diagnostics, batch_linger_s=0)
    for index in range(40):
        assert emitter.emit(user_event(f"u{index}")) is True  # synchronous: returns without the store
    await asyncio.sleep(0.01)
    assert store.calls == 1 and store.batches == []  # first batch is in flight, blocked
    store.gate.set()
    await wait_settled(emitter)
    assert [len(batch) for batch in store.batches] == [32, 8]  # MAX_APPEND_BATCH per append
    assert emitter.counters.appended == 40
    assert diagnostics.kinds() == [EMITTER_STARTED_KIND]
    await emitter.stop()


async def test_overflow_drops_the_newest_event_and_reports_once_per_episode():
    store = GatedStore()
    diagnostics = RecordingDiagnostics()
    emitter = ConversationEventEmitter(store, diagnostics=diagnostics, capacity=2, batch_linger_s=0)
    first, second, third, fourth = (user_event(name) for name in ("a", "b", "c", "d"))
    assert emitter.emit(first) and emitter.emit(second)
    await asyncio.sleep(0)  # drain takes `first` and `second` in one batch, blocked on the gate
    assert emitter.emit(third) and emitter.emit(user_event("e"))
    assert emitter.emit(fourth) is False  # full: the newest is dropped, queued order is kept
    assert emitter.emit(user_event("f")) is False
    drops = [entry for entry in diagnostics.entries if entry[0] == EVENT_DROPPED_KIND]
    assert len(drops) == 1 and drops[0][2] == "warning"
    assert drops[0][3]["reason"] == "queue_full" and drops[0][3]["event_type"] == "user.transcript.accepted"
    assert "text" not in repr(drops[0][3])  # never the content
    store.gate.set()
    await wait_settled(emitter)
    assert store.batches == [(first.event_id, second.event_id), (third.event_id, user_event("e").event_id)]
    assert emitter.counters.dropped_queue_full == 2
    # the episode ended when the queue emptied: a new overflow is reported again
    store.gate.clear()
    for name in ("g", "h", "i"):
        emitter.emit(user_event(name))
    await asyncio.sleep(0)
    for name in ("j", "k", "l"):
        emitter.emit(user_event(name))
    assert len([e for e in diagnostics.entries if e[0] == EVENT_DROPPED_KIND]) == 2
    store.gate.set()
    await emitter.stop()


async def test_linger_coalesces_a_producer_burst_into_one_commit():
    store = GatedStore()
    store.gate.set()
    emitter = ConversationEventEmitter(store, diagnostics=RecordingDiagnostics(), batch_linger_s=0.05)
    first = user_event("a")
    emitter.emit(first)
    await asyncio.sleep(0.01)  # drain woke on `first` and is lingering: nothing appended yet
    assert store.calls == 0
    burst = [user_event(f"b{index}") for index in range(5)]
    for event in burst:
        emitter.emit(event)
    await wait_settled(emitter)
    assert store.batches == [tuple(event.event_id for event in (first, *burst))]
    await emitter.stop()


async def test_stop_during_the_linger_still_stores_the_pending_events(tmp_path):
    state, store = await open_store(tmp_path / "state.sqlite3")
    emitter = ConversationEventEmitter(store, diagnostics=RecordingDiagnostics(), batch_linger_s=0.2)
    try:
        emitter.emit(user_event("a"))
        await asyncio.sleep(0)
        await emitter.stop()
        page = await store.list_conversation_events("conv-a")
        assert [item.event.event_id for item in page.events] == [user_event("a").event_id]
        assert emitter.counters.dropped_shutdown == 0
    finally:
        await state.close()


async def test_store_failure_drops_the_batch_reports_once_and_recovery_is_logged():
    store = GatedStore(fail=2)
    store.gate.set()
    diagnostics = RecordingDiagnostics()
    emitter = ConversationEventEmitter(store, diagnostics=diagnostics)
    emitter.emit(user_event("a"))
    await wait_settled(emitter)
    emitter.emit(user_event("b"))
    await wait_settled(emitter)
    emitter.emit(user_event("c"))
    await wait_settled(emitter)
    assert emitter.counters.dropped_store_error == 2 and emitter.counters.appended == 1
    kinds = [kind for kind in diagnostics.kinds() if kind != EMITTER_STARTED_KIND]
    assert kinds == [APPEND_FAILED_KIND, APPEND_RECOVERED_KIND]
    failed = diagnostics.entries[1]
    assert failed[2] == "error" and failed[3]["error_class"] == "OSError"
    assert failed[3]["code"] == "conversation_events_append_failed"
    await emitter.stop()


async def test_unexpected_store_exception_never_kills_the_drain_loop():
    class Broken:
        calls = 0

        async def append_many(self, events):
            Broken.calls += 1
            if Broken.calls == 1:
                raise RuntimeError("state repository is not initialized")
            return tuple(AppendResult(e.event_id, 1, AppendStatus.DUPLICATE) for e in events)

    emitter = ConversationEventEmitter(Broken(), diagnostics=RecordingDiagnostics())
    emitter.emit(user_event("a"))
    await wait_settled(emitter)
    emitter.emit(user_event("a"))
    await wait_settled(emitter)
    assert emitter.counters.dropped_store_error == 1 and emitter.counters.duplicates == 1
    await emitter.stop()


async def test_record_builds_span_times_and_rejects_invalid_events_without_raising():
    store = GatedStore()
    store.gate.set()
    diagnostics = RecordingDiagnostics()
    emitter = ConversationEventEmitter(store, diagnostics=diagnostics)
    event_id = emitter.record(T.BRAIN_WORK_STARTED, producer="core.brain_service", conversation_id="conv-a",
                              source_ids=("corr", "work-1"), occurred_at=BASE + timedelta(microseconds=1500),
                              correlation_id="corr", work_id="work-1", span_id="work-1")
    assert event_id == derive_conversation_event_id(producer="core.brain_service", event_type=T.BRAIN_WORK_STARTED,
                                                    conversation_id="conv-a", source_ids=("corr", "work-1"))
    secret = "PRIVATE " * 2000  # above the content bound
    assert emitter.record(T.USER_TRANSCRIPT_ACCEPTED, producer="core.voice_admission", conversation_id="conv-a",
                          source_ids=("turn",), occurred_at=BASE, correlation_id="c", turn_id="turn",
                          content=secret) is None
    assert emitter.record(T.BRAIN_TURN_FAILED, producer="core.brain_service", conversation_id="conv-a",
                          source_ids=("c",), occurred_at=BASE, correlation_id="c",
                          attributes={"error": "boom"}) is None
    assert emitter.record(T.BRAIN_TURN_ACCEPTED, producer="core.brain_service", conversation_id=" bad ",
                          source_ids=("c",), occurred_at=BASE, correlation_id="c", turn_id="t") is None
    await wait_settled(emitter)
    invalid = [entry for entry in diagnostics.entries if entry[0] == EVENT_INVALID_KIND]
    assert len(invalid) == 3 and emitter.counters.invalid == 3
    assert "PRIVATE" not in repr(diagnostics.entries)
    assert store.batches == [(event_id,)]
    await emitter.stop()


async def test_stop_drains_pending_events_then_refuses_new_ones(tmp_path):
    state, store = await open_store(tmp_path / "state.sqlite3")
    diagnostics = RecordingDiagnostics()
    emitter = ConversationEventEmitter(store, diagnostics=diagnostics)
    try:
        events = [user_event(f"u{index}", ms=index) for index in range(50)]
        for event in events:
            emitter.emit(event)
        await emitter.stop()  # returns only once everything queued is committed
        page = await store.list_conversation_events("conv-a", limit=100)
        assert [item.event.event_id for item in page.events] == [event.event_id for event in events]
        assert emitter.emit(user_event("late")) is False
        assert emitter.counters.dropped_stopped == 1
        stopped = [entry for entry in diagnostics.entries if entry[0] == EMITTER_STOPPED_KIND]
        assert stopped[0][3]["appended"] == 50
    finally:
        await state.close()


async def test_stop_timeout_drops_what_the_stuck_store_did_not_take():
    store = GatedStore()
    diagnostics = RecordingDiagnostics()
    emitter = ConversationEventEmitter(store, diagnostics=diagnostics, batch_linger_s=0)
    for index in range(35):
        emitter.emit(user_event(f"u{index}"))
    await asyncio.sleep(0)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await emitter.stop(timeout_s=0.05)
    assert loop.time() - started < 1.0
    assert emitter.counters.dropped_shutdown == 35  # 32 in flight + 3 still queued
    report = [entry for entry in diagnostics.entries if entry[0] == EVENT_DROPPED_KIND][0][3]
    assert report["reason"] == "shutdown_timeout" and report["dropped"] == 3
    assert emitter.pending == 0


async def test_failing_diagnostic_sink_is_counted_not_raised():
    store = GatedStore()
    store.gate.set()
    emitter = ConversationEventEmitter(store, diagnostics=RecordingDiagnostics(fail=True), capacity=1)
    emitter.emit(user_event("a"))
    emitter.emit(user_event("b"))  # overflow diagnostic fails
    assert emitter.record(T.SYSTEM_FAILURE, producer="core.brain_service", conversation_id="conv-a",
                          source_ids=("x",), occurred_at=BASE, content="no") is None
    await emitter.stop()
    assert emitter.counters.diagnostic_failures >= 3


@pytest.mark.parametrize(("value", "expected"), [
    ("RuntimeError", "RuntimeError"), ("brain_backend_not_configured", "brain_backend_not_configured"),
    ("aiohttp.ClientError", "aiohttp.ClientError"), ("Rate limit exceeded for org 42", None),
    ("sk-live-123", None), ("", None), (None, None), ("x" * 65, None),
])
def test_error_class_is_a_token_never_a_message(value, expected):
    assert safe_error_class(value) == expected


def test_journal_ref_adds_the_join_key_only_when_an_event_exists():
    assert journal_ref(None) == {}
    assert journal_ref("cev-" + "a" * 64) == {TRACE_EVENT_ID_KEY: "cev-" + "a" * 64}


async def test_stop_timeout_inside_the_linger_counts_every_pending_event():
    store = GatedStore()
    store.gate.set()
    emitter = ConversationEventEmitter(store, diagnostics=RecordingDiagnostics(), batch_linger_s=5.0)
    for index in range(3):
        emitter.emit(user_event(f"u{index}"))
    await asyncio.sleep(0)  # drain holds u0 and lingers
    await emitter.stop(timeout_s=0.05)
    assert store.calls == 0
    assert emitter.counters.dropped_shutdown == 3 and emitter.pending == 0


def test_derive_event_id_matches_record_and_never_raises():
    from jarvis.core.conversation_event_emitter import NullConversationEventEmitter

    emitter = ConversationEventEmitter(GatedStore())
    expected = derive_conversation_event_id(producer="core.brain_outcomes", event_type=T.BRAIN_MESSAGE_PUBLISHED,
                                            conversation_id="conv-a", source_ids=("corr", "outcome-1"))
    assert emitter.derive_event_id(T.BRAIN_MESSAGE_PUBLISHED, producer="core.brain_outcomes",
                                   conversation_id="conv-a", source_ids=("corr", "outcome-1")) == expected
    assert emitter.derive_event_id(T.BRAIN_MESSAGE_PUBLISHED, producer="core.brain_outcomes",
                                   conversation_id=" bad ", source_ids=("corr",)) is None
    assert NullConversationEventEmitter().derive_event_id(T.BRAIN_MESSAGE_PUBLISHED, producer="x",
                                                          conversation_id="c", source_ids=("s",)) is None


async def test_ingestion_counters_are_separate_from_the_queue_accounting():
    store = GatedStore()
    store.gate.set()
    emitter = ConversationEventEmitter(store, diagnostics=RecordingDiagnostics(), batch_linger_s=0)
    await emitter.append_now([user_event("i1"), user_event("i2")])
    emitter.emit(user_event("q1"))
    await wait_settled(emitter, timeout_s=1.0)
    c = emitter.counters
    assert (c.enqueued, c.appended, c.ingest_appended) == (1, 1, 2)
    await emitter.stop()
    with pytest.raises(ConversationEventStoreError):
        await emitter.append_now([user_event("late")])  # stopped: storage unavailable, never a store call
    assert (c.ingest_failures, store.calls) == (1, 2)
