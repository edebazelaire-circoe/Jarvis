"""Read side of the Conversation Event log for Core routes (Slice 04).

Binding contract: `docs/conversation-events.md`, section "Query and live API".
Core owns the store; `LocalProtocolServer` answers the `GET /v1/conversation-events...`
routes through this service, and nothing else reads the log.

Guarantees:

- every read goes through the `ConversationEventStore` port (codec decode,
  unreadable rows skipped, counted and diagnosed by the store);
- storage failures, including a closed repository while Core stops, surface as
  `ConversationEventStoreError` (the route answers 503). They are diagnosed once
  per failure episode (`core.conversation_events.query_failed`, error, with the
  operation and `error_class` only) and the recovery once
  (`core.conversation_events.query_recovered`, info), so a UI polling every
  second cannot flood the journal;
- caller errors (bad limit, cursor, id, lookup field) stay `ValueError` (400);
- long-poll (`events(wait_s > 0)`): the reader watches appends **to its
  conversation** (`ConversationEventStore.watch_appends`) before querying, so an
  append committed between the query and the wait wakes it at once, and appends
  to other conversations never do. The request returns as soon as a page holds
  events (after the `visibility` filter), when `wait_s` elapses, when the
  caller's `interrupt` is set (server stopping) or when `disconnected()` reports
  that the HTTP client left (checked every `DISCONNECT_CHECK_S`). Rows scanned
  meanwhile (filtered out, unreadable) advance the returned `next_cursor` and add
  up in `skipped_rows`; a timed-out long-poll returns that advanced cursor, so
  long-poll and plain poll converge on the same cursor.

Slice 06 projections, all built from the same store reads and the same pure
domain functions an offline reader uses:

- `transcript`: pages the conversation into a `TranscriptBuilder` and renders
  it in a worker thread; past the builder's event or text budget it raises
  `TranscriptTooLargeError`;
- `open_export`: freezes the conversation at its last sequence
  (`conversation_extent`), then streams header, event lines and trailer page by
  page (`until_sequence`), never holding the conversation in memory;
- `search`: the store's bounded newest-first scan over safe fields.

Core's hot path first (Slice 06 rework): at most `MAX_CONCURRENT_SEARCHES` = 1
search and `MAX_CONCURRENT_PROJECTIONS` = 2 transcript/export builds run at
once; another request is refused at once with `ConversationEventBusyError`
(route 429 `search_busy` / `projection_busy`), never queued. Projection pages
are small (`PROJECTION_PAGE_LIMIT`) and every page, and every stretch of
`PROJECTION_SLICE_S` of encoding, yields to the loop.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, TypeVar

from jarvis.domain.conversation_event_export import (
    encode_export_line, export_header, export_trailer,
)
from jarvis.domain.conversation_event_query import encode_stored_event, filter_visibility
from jarvis.domain.conversation_event_search import ConversationEventSearchPage, SearchQuery
from jarvis.domain.conversation_event_store import (
    ConversationEventPage, ConversationEventStoreError, ConversationEventSummaryPage,
    StoredConversationEvent,
)
from jarvis.domain.conversation_events import ConversationVisibility
from jarvis.domain.conversation_transcript import TranscriptBuilder, TranscriptMode
from jarvis.domain.v2 import utc_now
from jarvis.ports.v2 import ConversationEventStore, DiagnosticSink

T = TypeVar("T")

QUERY_FAILED_KIND = "core.conversation_events.query_failed"
QUERY_RECOVERED_KIND = "core.conversation_events.query_recovered"
#: How often a waiting long-poll checks that its HTTP client is still connected.
DISCONNECT_CHECK_S = 1.0
#: Concurrent heavy reads allowed; more are refused (429), never queued.
MAX_CONCURRENT_SEARCHES = 1
MAX_CONCURRENT_PROJECTIONS = 2
SEARCH_BUSY = "search_busy"
PROJECTION_BUSY = "projection_busy"
#: Events per store read for transcript and export: each read holds the repository
#: lock while it decodes its rows, so it stays short.
PROJECTION_PAGE_LIMIT = 50
#: Longest stretch of export encoding on the loop before yielding.
PROJECTION_SLICE_S = 0.002


class ConversationEventBusyError(Exception):
    """Too many heavy reads already running; the caller retries later (route answers 429)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Slots:
    """Non-blocking counter: `take()` succeeds or raises `ConversationEventBusyError`."""

    def __init__(self, capacity: int, code: str, message: str) -> None:
        self.capacity, self.code, self.message, self.in_use = capacity, code, message, 0

    def take(self) -> None:
        if self.in_use >= self.capacity:
            raise ConversationEventBusyError(self.code, self.message)
        self.in_use += 1

    def give(self) -> None:
        self.in_use = max(0, self.in_use - 1)


class ConversationEventQueryService:
    def __init__(self, store: ConversationEventStore, *, diagnostics: DiagnosticSink | None = None,
                 clock: Callable[[], float] | None = None, wall_clock: Callable[[], datetime] = utc_now) -> None:
        self._store = store
        self._diagnostics = diagnostics
        self._clock = clock
        self._wall_clock = wall_clock
        self.search_slots = _Slots(MAX_CONCURRENT_SEARCHES, SEARCH_BUSY,
                                   "a conversation search is already running; retry in a moment")
        self.projection_slots = _Slots(MAX_CONCURRENT_PROJECTIONS, PROJECTION_BUSY,
                                       "transcript or export builds already running; retry in a moment")
        self._failing = False
        #: Store failures seen by reads (every occurrence).
        self.failures = 0

    # ------------------------------------------------------------ plumbing

    def _now(self) -> float:
        return self._clock() if self._clock is not None else asyncio.get_running_loop().time()

    def _diagnose(self, kind: str, message: str, level: str, data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:  # noqa: BLE001 - a broken sink never turns a read into a failure (argued: the read outcome stands, the failure count is kept)
            pass

    async def _read(self, operation: str, read: Awaitable[T]) -> T:
        try:
            result = await read
        except ConversationEventStoreError as exc:
            self._fail(operation, exc)
            raise
        except RuntimeError as exc:
            # `SQLiteStateRepository` raises RuntimeError("state repository is not
            # initialized") once Core closed it: storage unavailable, not a bug of the caller.
            self._fail(operation, exc)
            raise ConversationEventStoreError("conversation event store unavailable") from exc
        if self._failing:
            self._failing = False
            self._diagnose(QUERY_RECOVERED_KIND, "conversation event reads succeed again", "info",
                           {"operation": operation})
        return result

    def _fail(self, operation: str, exc: BaseException) -> None:
        self.failures += 1
        if self._failing:
            return
        self._failing = True
        self._diagnose(QUERY_FAILED_KIND, "conversation event read failed; routes answer 503", "error",
                       {"code": "conversation_events_query_failed", "operation": operation,
                        "error_class": type(exc.__cause__ or exc).__name__})

    # --------------------------------------------------------------- reads

    async def conversations(self, *, before_sequence: int | None, limit: int) -> ConversationEventSummaryPage:
        return await self._read("conversations",
                                self._store.list_conversations(before_sequence=before_sequence, limit=limit))

    async def sessions(self, conversation_id: str, *, after_sequence: int, limit: int) -> ConversationEventSummaryPage:
        return await self._read("sessions", self._store.list_sessions(conversation_id, after_sequence=after_sequence,
                                                                      limit=limit))

    async def event(self, event_id: str) -> StoredConversationEvent | None:
        """None when absent or unreadable (the store diagnosed the latter)."""
        return await self._read("event", self._store.get_event(event_id))

    async def lookup(self, field: str, value: str, *, conversation_id: str | None, after_sequence: int, limit: int,
                     visibility: ConversationVisibility | None) -> ConversationEventPage:
        page = await self._read("lookup", self._store.list_events_by_id(
            field, value, conversation_id=conversation_id, after_sequence=after_sequence, limit=limit))
        return filter_visibility(page, visibility)

    async def events(self, conversation_id: str, *, after_sequence: int, limit: int,
                     visibility: ConversationVisibility | None, wait_s: float = 0.0,
                     interrupt: asyncio.Event | None = None,
                     disconnected: Callable[[], bool] | None = None) -> ConversationEventPage:
        """Events after `after_sequence`; with `wait_s > 0`, wait for visible events (long-poll)."""
        if wait_s < 0:
            raise ValueError("wait must not be negative")
        deadline = self._now() + wait_s
        cursor, skipped = after_sequence, 0
        while True:
            with self._store.watch_appends(conversation_id) as appended:
                page = await self._read("events", self._store.list_conversation_events(
                    conversation_id, after_sequence=cursor, limit=limit))
                skipped += page.skipped_rows
                cursor = page.next_cursor
                result = replace(filter_visibility(page, visibility), skipped_rows=skipped)
                if (result.events or self._now() >= deadline or (interrupt is not None and interrupt.is_set())
                        or (disconnected is not None and disconnected())):
                    return result
                if page.has_more:
                    continue  # rows remain past the cursor: keep scanning, do not wait
                if not await self._wait(appended, deadline, interrupt, disconnected):
                    return result

    async def _wait(self, appended: asyncio.Event, deadline: float, interrupt: asyncio.Event | None,
                    disconnected: Callable[[], bool] | None) -> bool:
        """Wait for an append, the deadline or the interrupt (True: query again); False when the client left."""
        while not appended.is_set() and not (interrupt is not None and interrupt.is_set()):
            remaining = deadline - self._now()
            if remaining <= 0:
                break
            await _first_set(appended, interrupt, min(remaining, DISCONNECT_CHECK_S))
            if disconnected is not None and disconnected():
                return False
        return True


    # ----------------------------------------------------- projections (Slice 06)

    async def transcript(self, conversation_id: str, *, mode: TranscriptMode = TranscriptMode.PLAIN,
                         utc_offset_minutes: int = 0) -> str:
        """Readable transcript of every stored event of the conversation (contract: "Readable transcript")."""
        self.projection_slots.take()
        try:
            builder = TranscriptBuilder(conversation_id, mode=mode, utc_offset_minutes=utc_offset_minutes)
            cursor = 0
            while True:
                page = await self._read("transcript", self._store.list_conversation_events(
                    conversation_id, after_sequence=cursor, limit=PROJECTION_PAGE_LIMIT))
                for item in page.events:
                    builder.add(item.event)  # raises TranscriptTooLargeError as soon as a budget is passed
                builder.note_skipped_rows(page.skipped_rows)
                cursor = page.next_cursor
                if not page.has_more:
                    break
                await asyncio.sleep(0)
            return await asyncio.to_thread(builder.render)
        finally:
            self.projection_slots.give()

    async def open_export(self, conversation_id: str) -> "ConversationEventExport":
        """Freeze the conversation's extent now; the returned export streams its lines on demand.

        Takes a projection slot, released when the stream ends or `aclose()` is called.
        """
        self.projection_slots.take()
        try:
            extent = await self._read("export", self._store.conversation_extent(conversation_id))
            header = export_header(conversation_id, exported_at=self._wall_clock(), extent=extent)
        except BaseException:
            self.projection_slots.give()
            raise
        return ConversationEventExport(self, conversation_id, header)

    async def search(self, query: SearchQuery, *, conversation_id: str | None, before_sequence: int | None,
                     limit: int, visibility: ConversationVisibility | None) -> ConversationEventSearchPage:
        self.search_slots.take()
        try:
            return await self._read("search", self._store.search_events(
                query, conversation_id=conversation_id, before_sequence=before_sequence, limit=limit,
                visibility=visibility))
        finally:
            self.search_slots.give()


class ConversationEventExport:
    """A frozen export: header first, then one chunk per store page, then the trailer.

    A storage failure while streaming raises `ConversationEventStoreError` (already
    diagnosed once per episode by the service): no trailer is written, so the
    receiver knows the file is incomplete.
    """

    def __init__(self, service: ConversationEventQueryService, conversation_id: str, header: dict[str, Any]) -> None:
        self.conversation_id = conversation_id
        self.header = header
        self.through_sequence: int = header["through_sequence"]
        self.events = 0
        self.skipped_rows = 0
        self._service = service
        self._released = False

    def release(self) -> None:
        """Give the projection slot back (idempotent). `chunks()` does it when it ends."""
        if not self._released:
            self._released = True
            self._service.projection_slots.give()

    async def chunks(self) -> AsyncIterator[bytes]:
        try:
            yield encode_export_line(self.header)
            cursor = 0
            while cursor < self.through_sequence:
                page = await self._service._read("export", self._service._store.list_conversation_events(
                    self.conversation_id, after_sequence=cursor, limit=PROJECTION_PAGE_LIMIT,
                    until_sequence=self.through_sequence))
                self.events += len(page.events)
                self.skipped_rows += page.skipped_rows
                lines, started = [], time.perf_counter()
                for item in page.events:
                    lines.append(encode_export_line(encode_stored_event(item)))
                    if time.perf_counter() - started >= PROJECTION_SLICE_S:
                        await asyncio.sleep(0)
                        started = time.perf_counter()
                if lines:
                    yield b"".join(lines)
                cursor = page.next_cursor
                if not page.has_more:
                    break
                await asyncio.sleep(0)
            yield encode_export_line(export_trailer(events=self.events, skipped_rows=self.skipped_rows))
        finally:
            self.release()


async def _first_set(signal: asyncio.Event, interrupt: asyncio.Event | None, timeout_s: float) -> None:
    waiters = [asyncio.ensure_future(signal.wait())]
    if interrupt is not None:
        waiters.append(asyncio.ensure_future(interrupt.wait()))
    try:
        await asyncio.wait(waiters, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
