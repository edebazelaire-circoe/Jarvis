"""Non-blocking Core-side writer of Conversation Events (handoff conversation-observability, Slice 03a).

Binding contract: `docs/conversation-events.md`, sections "Producers and
ingestion" and "Emitter". Core producers (`voice_admission.py`,
`brain_service.py`, `brain_outcomes.py`) call `record()`; the ingestion route
calls `append_now()`.

Guarantees:

- `record()` / `emit()` are synchronous and never await, never raise into the
  caller and never touch storage: they build and validate the event, then put it
  on a bounded in-memory queue (`put_nowait`). A background task, started lazily
  on the running loop, drains the queue in batches of at most `MAX_APPEND_BATCH`
  through `ConversationEventStore.append_many`. After waking on the first
  event it waits `batch_linger_s` (50 ms) before appending: the producer that
  recorded the event (e.g. `BrainOrchestrator.submit`) still has state-DB
  awaits to run, and an immediate commit on the shared repository lock would
  land inside them. Measured on the real stack (40 submits, 200 ms apart):
  without the linger 40/40 submits overlapped an event commit, with it 0/40,
  and commits fell from 280 to 62;
- **overflow drops the newest event** (the one being recorded): what is already
  queued keeps its causal order (a user turn is never dropped to make room for
  the Brain events that follow it). The first drop of an overflow episode emits
  one warning diagnostic; every drop is counted;
- a `ConversationEventStoreError` (or any other storage exception) drops that
  batch: counted, one error diagnostic per failure episode, one info diagnostic
  when appends succeed again. Events are not retried in memory;
- an event that fails the contract (for example a text above the content bound)
  is not recorded: counted and diagnosed with the codec's field-level message,
  never the value;
- `stop()` refuses new events and waits at most `timeout_s` for the queue to
  drain; whatever is left (or still appending) is dropped, counted and diagnosed.

Known limits (documented, not hidden): the queue is memory only, so a hard
process kill loses events recorded in the last instants before their batch
committed (the durable `turns` row stays authoritative for user input); the store
shares the state repository's connection and lock, so an append in progress
serializes with other state writes for the duration of one commit; the linger
widens the not-yet-committed window by `batch_linger_s`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
import re
from typing import Any

from jarvis.domain.conversation_event_store import (
    MAX_APPEND_BATCH, AppendResult, AppendStatus, ConversationEventStoreError,
)
from jarvis.domain.conversation_events import (
    TRACE_EVENT_ID_KEY,
    ConversationEvent,
    ConversationEventType,
    EventShape,
    TraceRef,
    TraceSource,
    derive_conversation_event_id,
    event_actor,
    event_shape,
    event_visibility,
    to_event_time,
)
from jarvis.ports.v2 import ConversationEventStore, DiagnosticSink

#: Producer ids of the in-process Core producers (part of every event id: never rename).
PRODUCER_VOICE_ADMISSION = "core.voice_admission"
PRODUCER_BRAIN_SERVICE = "core.brain_service"
PRODUCER_BRAIN_OUTCOMES = "core.brain_outcomes"

DEFAULT_QUEUE_CAPACITY = 1024
DEFAULT_STOP_TIMEOUT_S = 2.0
DEFAULT_BATCH_LINGER_S = 0.05

EMITTER_STARTED_KIND = "core.conversation_events.emitter_started"
EMITTER_STOPPED_KIND = "core.conversation_events.emitter_stopped"
EVENT_DROPPED_KIND = "core.conversation_events.event_dropped"
EVENT_INVALID_KIND = "core.conversation_events.event_invalid"
APPEND_FAILED_KIND = "core.conversation_events.append_failed"
APPEND_RECOVERED_KIND = "core.conversation_events.append_recovered"
INGEST_REJECTED_KIND = "core.conversation_events.ingest_rejected"

#: An `error_class` attribute must be a code-like token (identifier or dotted
#: class path), never a sentence: a raw provider error can carry private text.
_ERROR_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,63}")


def safe_error_class(value: object) -> str | None:
    """The value when it is a short code-like token, else None (a raw error message is never copied)."""
    if isinstance(value, str) and _ERROR_TOKEN.fullmatch(value.strip()):
        return value.strip()
    return None


def journal_ref(event_id: str | None) -> dict[str, str]:
    """`data` entries that let a RuntimeJournal line join its event (`trace_entry_matches`)."""
    return {TRACE_EVENT_ID_KEY: event_id} if event_id else {}


def journal_trace(kind: str, *join_keys: str) -> TraceRef:
    return TraceRef(TraceSource.RUNTIME_JOURNAL, kind, tuple(join_keys))


@dataclass(slots=True)
class ConversationEventEmitterCounters:
    enqueued: int = 0
    appended: int = 0
    duplicates: int = 0
    conflicts: int = 0
    invalid: int = 0
    dropped_queue_full: int = 0
    dropped_stopped: int = 0
    dropped_store_error: int = 0
    dropped_shutdown: int = 0
    #: Ingestion route (`append_now`): acknowledged synchronously to the caller,
    #: never part of the queue accounting above.
    ingest_appended: int = 0
    ingest_duplicates: int = 0
    ingest_conflicts: int = 0
    ingest_failures: int = 0
    diagnostic_failures: int = 0


class NullConversationEventEmitter:
    """Emitter used when no store is wired (headless unit tests): records nothing."""

    def record(self, event_type: ConversationEventType, **_: Any) -> str | None:
        return None

    def derive_event_id(self, event_type: ConversationEventType, **_: Any) -> str | None:
        return None


class ConversationEventEmitter:
    """Bounded, non-blocking queue in front of the Conversation Event store."""

    def __init__(self, store: ConversationEventStore, *, diagnostics: DiagnosticSink | None = None,
                 capacity: int = DEFAULT_QUEUE_CAPACITY, stop_timeout_s: float = DEFAULT_STOP_TIMEOUT_S,
                 batch_linger_s: float = DEFAULT_BATCH_LINGER_S) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("emitter capacity must be a positive integer")
        self._store = store
        self._diagnostics = diagnostics
        self._queue: asyncio.Queue[ConversationEvent] = asyncio.Queue(maxsize=capacity)
        self._capacity = capacity
        self._stop_timeout_s = stop_timeout_s
        self._batch_linger_s = batch_linger_s
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._drop_reported = False
        self._store_failing = False
        self.counters = ConversationEventEmitterCounters()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # -- producers ------------------------------------------------------------

    def derive_event_id(self, event_type: ConversationEventType, *, producer: str, conversation_id: str,
                        source_ids: tuple[str, ...]) -> str | None:
        """The id `record` would give this fact, for a journal line of an already recorded event. Never raises."""
        try:
            return derive_conversation_event_id(producer=producer, event_type=event_type,
                                                conversation_id=conversation_id, source_ids=source_ids)
        except (TypeError, ValueError):
            # intentional: the matching `record` already diagnosed the invalid ids.
            return None

    def record(self, event_type: ConversationEventType, *, producer: str, conversation_id: str,
               source_ids: tuple[str, ...], occurred_at: datetime, **fields: Any) -> str | None:
        """Build, validate and enqueue one event. Returns its id, or None when it was not recorded.

        `occurred_at` is the fact time (normalized to UTC ms). Span opens get
        `started_at = occurred_at`, closes `ended_at = occurred_at`; pass
        `span_id` (and an optional close `started_at`) in `fields`.
        """
        try:
            event_id = derive_conversation_event_id(producer=producer, event_type=event_type,
                                                    conversation_id=conversation_id, source_ids=source_ids)
            at = to_event_time(occurred_at)
            shape = event_shape(event_type)
            if shape is EventShape.SPAN_OPEN:
                fields["started_at"] = at
            elif shape is EventShape.SPAN_CLOSE:
                fields["ended_at"] = at
                if fields.get("started_at") is not None:
                    fields["started_at"] = to_event_time(fields["started_at"])
            event = ConversationEvent(
                event_id=event_id, event_type=event_type, actor=event_actor(event_type),
                conversation_id=conversation_id, producer=producer, visibility=event_visibility(event_type),
                occurred_at=at, **fields)
        except (TypeError, ValueError) as exc:
            # Legal capture: an invalid event is an observability defect, never
            # a failure of the turn that produced it.
            self.counters.invalid += 1
            self._diagnose(EVENT_INVALID_KIND, "conversation event rejected by the contract", "warning", {
                "event_type": getattr(event_type, "value", None), "producer": producer,
                "error_class": type(exc).__name__, "detail": str(exc)[:300]})
            return None
        return event.event_id if self.emit(event) else None

    def emit(self, event: ConversationEvent) -> bool:
        """Enqueue a validated event without waiting. False when it was dropped."""
        if self._stopping:
            self.counters.dropped_stopped += 1
            self._note_drop("stopped", event)
            return False
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.counters.dropped_queue_full += 1
            self._note_drop("queue_full", event)
            return False
        self.counters.enqueued += 1
        self._ensure_drain()
        return True

    # -- ingestion route ------------------------------------------------------

    async def append_now(self, events: Sequence[ConversationEvent]) -> tuple[AppendResult, ...]:
        """Append a validated batch and return per-event results (ingestion route).

        Raises `ConversationEventStoreError` (not acknowledged, retry the same batch),
        including when the emitter is stopped or the state repository is closed.
        """
        try:
            if self._stopping:
                raise ConversationEventStoreError("conversation event emitter is stopped")
            try:
                results = await self._store.append_many(events)
            except RuntimeError as exc:
                if isinstance(exc, ConversationEventStoreError):
                    raise
                # The closed repository raises RuntimeError("state repository is not
                # initialized"): storage unavailable for the caller, not a server bug.
                raise ConversationEventStoreError("conversation event store unavailable") from exc
        except ConversationEventStoreError as exc:
            self.counters.ingest_failures += 1
            self._diagnose(APPEND_FAILED_KIND, "ingested conversation events not stored", "error", {
                "code": "conversation_events_ingest_failed", "error_class": type(exc.__cause__ or exc).__name__,
                "batch_size": len(events)})
            raise
        self._count(results, ingest=True)
        return results

    def note_ingest_rejected(self, detail: str, *, event_count: int | None) -> None:
        self._diagnose(INGEST_REJECTED_KIND, "conversation event batch rejected", "warning",
                       {"code": "conversation_events_invalid_batch", "detail": detail[:300], "event_count": event_count})

    # -- lifecycle ------------------------------------------------------------

    def _ensure_drain(self) -> None:
        if self._task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # intentional: recorded outside a loop (synchronous test setup);
            # the queue keeps the event and the next emit on a loop drains it.
            return
        self._task = loop.create_task(self._drain(), name="jarvis-conversation-events")
        self._diagnose(EMITTER_STARTED_KIND, "conversation event emitter started", "info",
                       {"capacity": self._capacity})

    async def stop(self, *, timeout_s: float | None = None) -> None:
        """Refuse new events, drain for at most `timeout_s`, then drop and report the rest."""
        if self._stopping:
            return
        self._stopping = True
        timeout = self._stop_timeout_s if timeout_s is None else timeout_s
        task, timed_out = self._task, False
        if task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout)
            except TimeoutError:
                timed_out = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._task = None
        left = 0
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            left += 1
        if left:
            self.counters.dropped_shutdown += left
        if left or timed_out:
            self._diagnose(EVENT_DROPPED_KIND, "conversation events not stored before shutdown", "warning", {
                "reason": "shutdown_timeout" if timed_out else "not_started", "dropped": left,
                "timeout_ms": round(timeout * 1000)})
        self._diagnose(EMITTER_STOPPED_KIND, "conversation event emitter stopped", "info", asdict(self.counters))

    # -- internals ------------------------------------------------------------

    async def _drain(self) -> None:
        while True:
            batch = [await self._queue.get()]
            if self._batch_linger_s > 0:
                # Let the recording producer finish its own state-DB awaits first
                # (see module docstring); cancellation here leaves `batch` unacknowledged.
                try:
                    await asyncio.sleep(self._batch_linger_s)
                except asyncio.CancelledError:
                    self.counters.dropped_shutdown += 1
                    self._queue.task_done()
                    raise
            while len(batch) < MAX_APPEND_BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                results = await self._store.append_many(batch)
            except asyncio.CancelledError:
                self.counters.dropped_shutdown += len(batch)
                raise
            except Exception as exc:
                # Legal capture: storage failure drops this batch (not acknowledged),
                # reported once per failure episode; the drain loop must survive.
                self.counters.dropped_store_error += len(batch)
                if not self._store_failing:
                    self._store_failing = True
                    self._diagnose(APPEND_FAILED_KIND, "conversation events not stored", "error", {
                        "code": "conversation_events_append_failed",
                        "error_class": type(exc.__cause__ or exc).__name__, "batch_size": len(batch),
                        "dropped_store_error": self.counters.dropped_store_error})
            else:
                self._count(results)
                if self._store_failing:
                    self._store_failing = False
                    self._diagnose(APPEND_RECOVERED_KIND, "conversation events stored again", "info",
                                   {"dropped_store_error": self.counters.dropped_store_error})
            finally:
                for _ in batch:
                    self._queue.task_done()
            if self._queue.empty():
                self._drop_reported = False

    def _count(self, results: Sequence[AppendResult], *, ingest: bool = False) -> None:
        c = self.counters
        for result in results:
            if result.status is AppendStatus.APPENDED:
                if ingest:
                    c.ingest_appended += 1
                else:
                    c.appended += 1
            elif result.status is AppendStatus.DUPLICATE:
                if ingest:
                    c.ingest_duplicates += 1
                else:
                    c.duplicates += 1
            elif ingest:
                c.ingest_conflicts += 1
            else:
                c.conflicts += 1

    def _note_drop(self, reason: str, event: ConversationEvent) -> None:
        if self._drop_reported:
            return
        self._drop_reported = True
        self._diagnose(EVENT_DROPPED_KIND, "conversation event dropped", "warning", {
            "reason": reason, "event_type": event.event_type.value, "conversation_id": event.conversation_id,
            "capacity": self._capacity, "dropped_queue_full": self.counters.dropped_queue_full,
            "dropped_stopped": self.counters.dropped_stopped})

    def _diagnose(self, kind: str, message: str, level: str, data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # Legal capture by count: a failing diagnostic sink must never fail a
            # producer or the drain loop; the counter keeps the loss visible.
            self.counters.diagnostic_failures += 1
