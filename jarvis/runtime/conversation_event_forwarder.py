"""Conversation Events of the Voice and Control Center processes, forwarded to Core (Slice 03b).

Binding contract: `docs/conversation-events.md`, sections "Producers and
ingestion" and "Forwarder". Core owns the store; these processes never open the
state DB. Their producers (`SpeechScheduler`, `RealtimeConversationBridge`,
`AgentTaskTracker`) call `record()`, which has the same signature as the Core
emitter (`jarvis.ports.v2.ConversationEventRecorder`).

    producer ──record()──► bounded deque ──own task, batches ≤ 32──► POST /v1/conversation-events
     (sync, no I/O)          (drop newest)     (linger, backoff)         (Core, FULL-sync commit)

Guarantees:

- `record()` is synchronous, never awaits, never does I/O on the normal path and
  never raises into the producer: it builds and validates the event
  (`build_conversation_event`, same code as Core) and appends it to a bounded
  in-memory deque. It returns the event id to write into the producer's
  RuntimeJournal line, or None when nothing was queued;
- a fact recorded twice (same event id among the last `recent_capacity` ids) is
  queued once: the repeat returns None, so exactly one journal line carries the id;
- **overflow drops the newest event** (causal prefix kept), counted, one
  journal warning per overflow episode;
- one task sends batches of at most `MAX_APPEND_BATCH` after a `flush_interval_s`
  linger (each ingestion POST is one FULL-sync commit on Core's shared state
  lock: batching bounds that cost to one commit per interval);
- Core unreachable, restarting (503) or with a rotated token (401, the token
  file is re-read) keeps the batch and retries with an exponential backoff
  (`retry_min_s` to `retry_max_s`), so memory stays bounded by `capacity` and
  there is no retry storm. Retrying is safe: same ids, same `occurred_at`, the
  store answers `duplicate`;
- Core refusing a batch (400/413/other 4xx, or a JSON answer that does not
  match the batch) drops that batch; an undecodable body is retried: counted (`dropped_rejected`), one journal error
  per refusal series;
- `aclose()` refuses new events, cancels the loop, tries one last send bounded
  by `close_timeout_s`, then counts what is left as `dropped_shutdown` and
  journals the final counters.

Counter identity once closed: `enqueued = appended + duplicates + conflicts +
dropped_rejected + dropped_shutdown`. Loss is bounded and always counted: a hard
kill loses at most the queue (≤ `capacity` events, typically the last
`flush_interval_s` of activity); a Core outage longer than the queue can absorb
drops the newest events.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import islice
from typing import Any

from jarvis.core.conversation_event_emitter import build_conversation_event
from jarvis.domain.conversation_event_ingest import ConversationEventAppendResponseError
from jarvis.domain.conversation_event_store import MAX_APPEND_BATCH, AppendResult, AppendStatus
from jarvis.domain.conversation_events import (
    ConversationEvent,
    ConversationEventError,
    MAX_CONTENT_CHARS,
    ConversationEventType,
    derive_conversation_event_id,
)
from jarvis.protocol.client import CoreProtocolError
from jarvis.runtime.core_forwarder import CoreBatchForwarder, CoreBatchRejected, CoreLoopbackTransport
from jarvis.runtime.journal import RuntimeJournal

#: Producer ids of the out-of-process producers (part of every event id: never rename).
PRODUCER_SPEECH_SCHEDULER = "voice.speech_scheduler"
PRODUCER_REALTIME_AUDIO = "voice.realtime_audio"
PRODUCER_AGENT_TASKS = "control_center.agent_tasks"

DEFAULT_CAPACITY = 1024
DEFAULT_RECENT_CAPACITY = 4096
DEFAULT_FLUSH_INTERVAL_S = 0.5

FORWARDER_UNAVAILABLE_KIND = "conversation_events.forwarder_unavailable"
FORWARDER_RESTORED_KIND = "conversation_events.forwarder_restored"
FORWARDER_REJECTED_KIND = "conversation_events.forwarder_rejected"
FORWARDER_STOPPED_KIND = "conversation_events.forwarder_stopped"
EVENT_DROPPED_KIND = "conversation_events.event_dropped"
EVENT_INVALID_KIND = "conversation_events.event_invalid"


class ConversationEventsRejected(CoreBatchRejected):
    """Core refused a Conversation Event batch: replaying it identical cannot succeed."""


class CoreConversationEventTransport(CoreLoopbackTransport):
    """`POST /v1/conversation-events` over loopback, session token re-read after a 401."""

    async def post(self, events: Sequence[ConversationEvent]) -> tuple[AppendResult, ...]:
        client = self._connect()
        try:
            return await client.append_conversation_events(events)
        except CoreProtocolError as exc:
            if exc.status == 401:
                # Core restarted with a new token: re-read on the next attempt.
                await self.close()
                raise
            if 400 <= exc.status < 500 and exc.status not in (408, 429):
                raise ConversationEventsRejected(f"{exc.status} {exc.code}") from exc
            raise
        except (ConversationEventError, ConversationEventAppendResponseError) as exc:
            # An event the codec refuses, or a JSON answer that does not match the
            # batch: the same batch would fail the same way. Any other ValueError
            # (`json.JSONDecodeError`, `UnicodeDecodeError`: a garbled body while
            # Core restarts) propagates and is retried like an unavailability.
            raise ConversationEventsRejected(type(exc).__name__) from exc


@dataclass(slots=True)
class ConversationEventForwarderCounters:
    enqueued: int = 0
    appended: int = 0
    duplicates: int = 0
    conflicts: int = 0
    #: Contract failure at `record()`: never queued.
    invalid: int = 0
    #: Same event id recorded again while still remembered: queued once.
    repeated: int = 0
    dropped_queue_full: int = 0
    dropped_closed: int = 0
    dropped_rejected: int = 0
    dropped_shutdown: int = 0
    diagnostic_failures: int = 0


class ConversationEventForwarder(CoreBatchForwarder):
    """Bounded, non-blocking recorder of Conversation Events, drained to Core in batches."""

    TASK_NAME = "jarvis-conversation-events"
    UNAVAILABLE_KIND = FORWARDER_UNAVAILABLE_KIND
    UNAVAILABLE_MESSAGE = "Core unreachable: conversation events wait in memory (bounded)"
    RESTORED_KIND = FORWARDER_RESTORED_KIND
    RESTORED_MESSAGE = "Core reachable again: conversation events are sent"
    REJECTED_KIND = FORWARDER_REJECTED_KIND
    REJECTED_MESSAGE = "Core refused a conversation event batch: batch dropped"

    def __init__(
        self,
        *,
        transport: Any,
        journal: RuntimeJournal | None = None,
        capacity: int = DEFAULT_CAPACITY,
        recent_capacity: int = DEFAULT_RECENT_CAPACITY,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        retry_min_s: float = 1.0,
        retry_max_s: float = 30.0,
        close_timeout_s: float = 2.0,
    ) -> None:
        if type(capacity) is not int or capacity < 1 or type(recent_capacity) is not int or recent_capacity < 1:
            raise ValueError("invalid conversation event forwarder bounds")
        super().__init__(
            transport=transport, journal=journal, flush_interval_s=flush_interval_s, retry_min_s=retry_min_s,
            retry_max_s=retry_max_s, close_timeout_s=close_timeout_s, idle_interval_s=None,
        )
        self.capacity = capacity
        self.recent_capacity = recent_capacity
        self.counters = ConversationEventForwarderCounters()
        self._queue: deque[ConversationEvent] = deque()
        self._recent: OrderedDict[str, None] = OrderedDict()
        self._closed = False
        self._drop_reported = False
        self._invalid_reported: set[tuple[str, str]] = set()

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def closed(self) -> bool:
        return self._closed

    # -- producers (hot path) --------------------------------------------------

    def derive_event_id(self, event_type: ConversationEventType, *, producer: str, conversation_id: str,
                        source_ids: tuple[str, ...]) -> str | None:
        """Id of a fact (own or another producer's, e.g. a Core parent). Never raises."""
        try:
            return derive_conversation_event_id(producer=producer, event_type=event_type,
                                                conversation_id=conversation_id, source_ids=source_ids)
        except (TypeError, ValueError):
            # intentional: an invalid id cannot name an event; the caller records no link.
            return None

    def record(self, event_type: ConversationEventType, *, producer: str, conversation_id: str,
               source_ids: tuple[str, ...], occurred_at: datetime, **fields: Any) -> str | None:
        """Build, validate and queue one fact. Returns its id, or None when nothing was queued."""
        try:
            event = build_conversation_event(event_type, producer=producer, conversation_id=conversation_id,
                                             source_ids=source_ids, occurred_at=occurred_at, **fields)
        except (TypeError, ValueError) as exc:
            # Legal capture: an invalid event is an observability defect, never a
            # failure of the speech, tool call or sub-agent that produced it.
            self.counters.invalid += 1
            self._note_invalid(event_type, producer, exc)
            return None
        if event.event_id in self._recent:
            self.counters.repeated += 1
            return None
        if self._closed:
            self.counters.dropped_closed += 1
            return None
        if len(self._queue) >= self.capacity:
            self.counters.dropped_queue_full += 1
            self._note_dropped(event)
            return None
        self._recent[event.event_id] = None
        while len(self._recent) > self.recent_capacity:
            self._recent.popitem(last=False)
        self._queue.append(event)
        self.counters.enqueued += 1
        self._wake.set()
        return event.event_id

    # -- sending ---------------------------------------------------------------

    async def flush(self) -> bool:
        """Send everything queued; False when Core is unreachable (the batch stays queued)."""
        while self._queue:
            batch = tuple(islice(self._queue, MAX_APPEND_BATCH))
            try:
                results = await self.transport.post(batch)
            except asyncio.CancelledError:
                raise  # nothing popped: the batch stays queued for the bounded close
            except CoreBatchRejected as exc:
                self._pop(len(batch))
                self.counters.dropped_rejected += len(batch)
                self._report_rejected(exc)
                continue
            except Exception as exc:  # noqa: BLE001 - Core stopped, 503, token, network
                self._report_unavailable(exc)
                return False
            self._pop(len(batch))
            self._note_accepted()
            for result in results:
                if result.status is AppendStatus.APPENDED:
                    self.counters.appended += 1
                elif result.status is AppendStatus.DUPLICATE:
                    self.counters.duplicates += 1
                else:
                    self.counters.conflicts += 1
        self._drop_reported = False
        return True

    def _pop(self, count: int) -> None:
        for _ in range(count):
            self._queue.popleft()

    async def aclose(self) -> None:
        self._closed = True
        await super().aclose()

    def _after_close(self) -> None:
        left = len(self._queue)
        self._queue.clear()
        self.counters.dropped_shutdown += left
        if left:
            self._report(EVENT_DROPPED_KIND, "conversation events not sent before shutdown", "warning",
                         extra={"reason": "shutdown", "dropped": left})
        self._report(FORWARDER_STOPPED_KIND, "conversation event forwarder stopped", "info",
                     extra=asdict(self.counters))

    # -- diagnostics -----------------------------------------------------------

    def _report_data(self) -> dict[str, Any]:
        c = self.counters
        return {"pending": len(self._queue), "capacity": self.capacity, "dropped_queue_full": c.dropped_queue_full,
                "dropped_rejected": c.dropped_rejected}

    def _note_dropped(self, event: ConversationEvent) -> None:
        if self._drop_reported:
            return
        self._drop_reported = True
        self._report(EVENT_DROPPED_KIND, "conversation event dropped: forwarder queue full", "warning",
                     extra={"reason": "queue_full", "event_type": event.event_type.value,
                            "producer": event.producer})

    def _note_invalid(self, event_type: object, producer: object, exc: Exception) -> None:
        name = getattr(event_type, "value", str(event_type))
        key = (name, str(producer))
        if key in self._invalid_reported:
            return
        self._invalid_reported.add(key)
        # The codec message names the field and the rule, never the value.
        detail = str(exc)[:300] if isinstance(exc, ConversationEventError) else type(exc).__name__
        self._report(EVENT_INVALID_KIND, "conversation event rejected by the contract", "warning",
                     extra={"event_type": name, "producer": str(producer)[:64], "error_class": type(exc).__name__,
                            "detail": detail})

    def _on_report_failure(self) -> None:
        self.counters.diagnostic_failures += 1


# -- producer helpers: copy only values the contract accepts, never raise ----------

def optional_id(value: object) -> str | None:
    """`value` when it is a valid opaque id (printable, trimmed, ≤ 256, valid UTF-8), else None."""
    if (not isinstance(value, str) or not value or len(value) > 256 or value != value.strip()
            or not value.isprintable()):
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def public_text(value: object) -> str | None:
    """Public text within the content bound, else None (a longer text is omitted, never truncated)."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_CONTENT_CHARS:
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value
