"""DiagnosticBundle capture service: bounded evidence readers, then the pure builder, then the store.

Binding contract: `docs/testlab.md` ("DiagnosticBundle", "Capture service").
This is the I/O side; `bundle_builder.py` stays pure. Readers never load an
unbounded file and record every bound they hit in the bundle `coverage`:

- Conversation Events through the `ConversationEventStore` port
  (`StoreEventSource`), a Core state database opened strictly read-only
  (`StateDatabaseEventSource`: sqlite `mode=ro` URI plus `PRAGMA query_only`,
  reusing `SQLiteConversationEventStore` decoding through its `run_serialized`
  seam), or a `jarvis.conversation-events.export` file (`ExportEventSource`,
  `read_export`);
- `RuntimeJournal` lines through `read_session_trace`: a forward reader bounded
  in bytes, lines, line size and selected lines, positioned by time bisection
  when the window is known, or on the file tail otherwise. Each kept line is
  **projected** before it reaches the builder: the drill-down projection
  `project_trace_entry` (allowlisted, value-checked `data`, no message) plus the
  closed set of extra scalar keys the bundle needs (`TRACE_EXTRA_*`);
- voice session metric reports (`VoiceSessionMetricRecorder` files) and the
  `trace_summary.summarize` aggregate, reused as they are.

A source that is missing or fails to read never fails the capture: it becomes a
coverage status with a reason code and a `warning` diagnostic. The expected path
emits `testlab_bundle_captured` (info) with counts only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, TypeVar

from jarvis.adapters.sqlite_conversation_events import SQLiteConversationEventStore
from jarvis.domain.conversation_event_export import ExportFormatError, read_export
from jarvis.domain.conversation_event_store import (
    MAX_EVENT_PAGE_LIMIT,
    ConversationEventPage,
    ConversationEventStoreError,
    StoredConversationEvent,
)
from jarvis.domain.conversation_events import to_event_time
from jarvis.ports.v2 import ConversationEventStore, DiagnosticSink
from jarvis.runtime.conversation_event_trace import SECRET_PREFIXES, project_trace_entry
from jarvis.runtime import trace_summary
from jarvis.runtime.trace_summary import summarize
from jarvis.testlab._diagnostics import SafeDiagnostics
from jarvis.testlab.bundle import SECTION_LIMITS, DiagnosticBundle, SourceStatus, is_code_token, is_opaque_id
from jarvis.testlab.bundle_builder import (
    NOT_REQUESTED_EVENTS,
    NOT_REQUESTED_REPORTS,
    NOT_REQUESTED_TRACE,
    BundleOptions,
    CaptureContext,
    EventEvidence,
    ReportEvidence,
    SessionSelector,
    TraceEvidence,
    TraceLine,
    VoiceSessionReport,
    build_diagnostic_bundle,
    is_mapped_journal_kind,
)
from jarvis.testlab.runs import CodeIdentity
from jarvis.testlab.store import BundlePutResult, BundleStore
from jarvis.testlab.validation import MAX_JSON_INT, fail

T = TypeVar("T")

# ------------------------------------------------------------- projection

#: Extra journal `data` keys the bundle keeps beyond the drill-down allowlist, by value rule.
TRACE_EXTRA_NUMBER_KEYS = frozenset({"elapsed_ms", "queue_wait_ms", "stop_latency_ms", "budget_ms",
                                     "duration_seconds", "input_tokens", "output_tokens"})
TRACE_EXTRA_TOKEN_KEYS = frozenset({"measure", "authority", "trigger", "addressing", "arch", "delivery",
                                    "delivery_boundary"})
TRACE_EXTRA_ID_KEYS = frozenset({"segment_id", "interrupted_speech_id"})
TRACE_EXTRA_BOOL_KEYS = frozenset({"device_stopped", "near_playback", "cleanup_pending", "still_active"})
TRACE_EXTRA_HEX_KEYS = frozenset({"configuration_id"})
#: Lists of at most 16 opaque ids.
TRACE_EXTRA_ID_LIST_KEYS = frozenset({"work_ids"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID_FORBIDDEN = re.compile(r"[@/\\=+\s]")


def _safe_extra(key: str, value: object) -> bool:
    if isinstance(value, str) and value.lower().startswith(SECRET_PREFIXES):
        return False
    if key in TRACE_EXTRA_NUMBER_KEYS:
        return type(value) in (int, float) and math.isfinite(value) and abs(value) <= MAX_JSON_INT
    if key in TRACE_EXTRA_TOKEN_KEYS:
        return is_code_token(value)
    if key in TRACE_EXTRA_ID_KEYS:
        return is_opaque_id(value) and not _ID_FORBIDDEN.search(value)  # type: ignore[arg-type]
    if key in TRACE_EXTRA_BOOL_KEYS:
        return type(value) is bool
    if key in TRACE_EXTRA_ID_LIST_KEYS:
        return (isinstance(value, list) and len(value) <= 16
                and all(_safe_extra("interrupted_speech_id", item) for item in value))
    return key in TRACE_EXTRA_HEX_KEYS and isinstance(value, str) and _HEX64.fullmatch(value) is not None


def project_bundle_trace_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """`project_trace_entry` plus the bundle's extra scalar keys. Never a message, never free text."""
    projected = project_trace_entry(entry)
    raw = entry.get("data") if isinstance(entry.get("data"), Mapping) else {}
    data = dict(projected["data"])
    for key, value in raw.items():  # type: ignore[union-attr]
        if isinstance(key, str) and key not in data and _safe_extra(key, value):
            data[key] = tuple(value) if isinstance(value, list) else value
    return {"ts": projected["ts"], "kind": projected["kind"], "level": projected["level"], "data": data}


def parse_trace_time(value: object) -> datetime | None:
    """A journal `ts` (ISO 8601 with offset) as a UTC millisecond time; None when absent, naive or invalid."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return to_event_time(parsed)


# ------------------------------------------------------------ trace reader

#: Journal kinds `trace_summary.summarize` reads (kept for the `aggregates.trace_summary` reuse).
TRACE_SUMMARY_KINDS = frozenset({
    trace_summary.OWNER_CANDIDATE, trace_summary.OWNER_CONFIRMED, trace_summary.OWNER_REJECTED,
    trace_summary.OWNER_UNAVAILABLE, trace_summary.OWNER_OVERRUN, trace_summary.OWNER_REPLAY,
    trace_summary.BARGE_IN_OWNER_CONFIRMED, trace_summary.BARGE_IN_PROVIDER_ADVISORY, trace_summary.BARGE_IN_AUTHORITY,
    trace_summary.INPUT_NON_OWNER_DROPPED, trace_summary.AUTHORIZATION_REFUSED, trace_summary.AUTHORIZATION_INVALID,
    trace_summary.BRAIN_WORK_CONTEXT, trace_summary.WORK_ATTENTION, trace_summary.WORK_UPDATED,
})
#: Raw provider stream: never selected, whatever a table says.
RAW_PROVIDER_STREAM_KIND = "agent.event"
_BOM = b"\xef\xbb\xbf"


def is_selected_kind(kind: str) -> bool:
    """Selection budget: only kinds the builder maps (`MAPPED_JOURNAL_KINDS`, `voice.latency.*`) or the summary reads."""
    return kind != RAW_PROVIDER_STREAM_KIND and (kind in TRACE_SUMMARY_KINDS or is_mapped_journal_kind(kind))
_KIND = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_TS_HEAD = re.compile(rb'"ts"\s*:\s*"([^"]{10,40})"')
_BISECT_STOP_BYTES = 64 * 1024
_BISECT_PROBE_LINES = 64


@dataclass(frozen=True, slots=True)
class TraceReadLimits:
    #: Bytes read from the start position (64 MiB, the drill-down budget).
    max_bytes: int = 64 * 1024 * 1024
    max_lines: int = 500_000
    #: Longer lines are skipped and counted (`oversized_lines`).
    max_line_bytes: int = 256 * 1024
    max_selected_lines: int = SECTION_LIMITS["trace_lines"]
    max_selected_bytes: int = 16 * 1024 * 1024
    #: Cross-process interleaving allowance around a known window (journal lines are
    #: appended in time order per process, interleaved by milliseconds across processes).
    tolerance: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_lines", "max_line_bytes", "max_selected_lines", "max_selected_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise fail(f"{name} must be a positive integer")
        if self.max_selected_lines > SECTION_LIMITS["trace_lines"]:
            raise fail(f"max_selected_lines must be at most {SECTION_LIMITS['trace_lines']}")


@dataclass(frozen=True, slots=True)
class TraceReadResult:
    evidence: TraceEvidence
    #: Raw text of the selected lines, only for `trace_summary.summarize` (scalars); never persisted.
    raw_lines: tuple[str, ...] = ()
    bytes_read: int = 0


def _head_time(line: bytes) -> datetime | None:
    match = _TS_HEAD.search(line, 0, 96)
    if match is None:
        return None
    try:
        return parse_trace_time(match.group(1).decode("ascii"))
    except UnicodeDecodeError:
        return None


def _seek_time(handle, size: int, target: datetime, max_line_bytes: int) -> int:
    """Byte offset of a line start at or before the first line timed >= `target` (bisection on line heads)."""
    low, high = 0, size
    while high - low > _BISECT_STOP_BYTES:
        middle = (low + high) // 2
        handle.seek(middle)
        handle.readline(max_line_bytes + 1)  # the partial line at `middle`
        found = None
        for _ in range(_BISECT_PROBE_LINES):
            if handle.tell() >= high:
                break
            line = handle.readline(max_line_bytes + 1)
            if not line:
                break
            found = _head_time(line)
            if found is not None:
                break
        if found is None or found >= target:
            high = middle
        else:
            low = middle
    if low == 0:
        return 0
    handle.seek(low)
    handle.readline(max_line_bytes + 1)
    while True:  # finish an oversized partial line
        position = handle.tell()
        handle.seek(position - 1)
        if handle.read(1) == b"\n":
            return position
        if not handle.readline(max_line_bytes + 1):
            return handle.tell()


class _Extent:
    """Timed lines between the first and the last line carrying the selected id (id-only selection)."""

    def __init__(self) -> None:
        self.timed = 0
        self.first: int | None = None
        self.last: int | None = None

    def anchor(self) -> None:
        if self.first is None:
            self.first = self.timed
        self.last = self.timed

    def count(self) -> int:
        return 0 if self.first is None or self.last is None else self.last - self.first + 1


def read_session_trace(path: Path, selector: SessionSelector, *, start: datetime | None = None,
                       end: datetime | None = None, limits: TraceReadLimits = TraceReadLimits()) -> TraceReadResult:
    """Select and project the journal lines of one session, bounded; the result carries its own coverage.

    Selection: a line inside [start, end] (when known) of a selected kind
    (`is_selected_kind`), not carrying another conversation or session id than
    the selector's. With a selector id, a line carrying that id is `matched`;
    lines without any id are kept only inside the extent of matched lines. Without
    a known window the reader scans the last `max_bytes` of the file
    (`start_truncated` when older bytes exist).

    Damage is counted over the physical scan range (from the scan start, or in
    window mode from the first line timed at or after the window start minus the
    tolerance, to the stop point): torn or non-JSON lines, lines without a valid
    `ts`, oversized lines. A final line without newline is never decoded
    (`torn_tail`). A UTF-8 BOM at the file start is skipped; carriage returns
    inside a line separate records.
    """
    try:
        handle = open(path, "rb")
    except FileNotFoundError:
        return TraceReadResult(TraceEvidence(SourceStatus.MISSING, reason="trace_file_missing"))
    except OSError:
        return TraceReadResult(TraceEvidence(SourceStatus.UNAVAILABLE, reason="trace_unreadable"))
    with handle:
        try:
            return _read_trace(handle, selector, start, end, limits)
        except OSError:
            return TraceReadResult(TraceEvidence(SourceStatus.UNAVAILABLE, reason="trace_unreadable"))


def _read_trace(handle, selector: SessionSelector, start: datetime | None, end: datetime | None,
                limits: TraceReadLimits) -> TraceReadResult:
    size = os.fstat(handle.fileno()).st_size
    has_ids = selector.conversation_id is not None or selector.session_id is not None
    if start is not None:
        position = _seek_time(handle, size, start - limits.tolerance, limits.max_line_bytes)
        start_truncated = False
    else:
        position = max(0, size - limits.max_bytes)
        if position:
            handle.seek(position - 1)
            handle.readline(limits.max_line_bytes + 1)
            position = handle.tell()
        start_truncated = position > 0
    handle.seek(position)
    counting = start is None
    counts = {"corrupt": 0, "untimed": 0, "oversized": 0}
    physical = {"decoded": 0, "corrupt": 0, "untimed": 0, "timed": 0}
    extent = _Extent()
    in_window = 0
    candidates: list[tuple[int, datetime, dict[str, Any], bool, str]] = []
    selected_bytes = scanned_lines = bytes_read = 0
    truncated, stopped_by, torn_tail, stop = False, "file_end", False, False
    last_direct = -1

    def damage(name: str) -> None:
        physical[name] += 1
        if counting:
            counts[name] += 1

    while position < size and not stop:
        if bytes_read >= limits.max_bytes:
            truncated, stopped_by = True, "max_bytes"
            break
        offset = position
        raw = handle.readline(limits.max_line_bytes + 1)
        if not raw:
            break
        position += len(raw)
        bytes_read += len(raw)
        if len(raw) > limits.max_line_bytes:
            while not raw.endswith(b"\n"):  # skip the rest of the oversized line
                raw = handle.readline(limits.max_line_bytes + 1)
                if not raw:
                    break
                position += len(raw)
                bytes_read += len(raw)
            if counting:
                counts["oversized"] += 1
            continue
        last_line = not raw.endswith(b"\n")
        if last_line:
            # No newline up to the end of the file. A carriage-return-separated file ends its
            # records with `\r`; whatever follows the last separator is still being written
            # (or torn) and is never decoded.
            cut = raw.rfind(b"\r")
            torn_tail = cut + 1 < len(raw)
            if cut < 0:
                break
            body = raw[:cut]
        else:
            body = raw[:-1]
        base = offset
        if offset == 0 and body.startswith(_BOM):
            body, base = body[len(_BOM):], offset + len(_BOM)
        for part in body.split(b"\r"):
            part_offset, base = base, base + len(part) + 1
            if not part.strip():
                continue
            scanned_lines += 1
            if scanned_lines > limits.max_lines:
                truncated, stopped_by, stop = True, "max_lines", True
                break
            try:
                text = part.decode("utf-8")
                entry = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                damage("corrupt")
                continue
            if not isinstance(entry, dict):
                damage("corrupt")
                continue
            physical["decoded"] += 1
            ts = parse_trace_time(entry.get("ts"))
            if ts is None:
                damage("untimed")
                continue
            physical["timed"] += 1
            if not counting:
                if ts < start - limits.tolerance:  # type: ignore[operator]
                    continue
                counting = True
            if end is not None and ts > end + limits.tolerance:
                stopped_by, stop = "window_end", True
                break
            if (start is not None and ts < start) or (end is not None and ts > end):
                continue
            if start is not None:
                in_window += 1
            else:
                extent.timed += 1
            kind = entry.get("kind")
            if not isinstance(kind, str) or not _KIND.fullmatch(kind) or not is_selected_kind(kind):
                continue
            data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
            conversation, session = data.get("conversation_id"), data.get("session_id")
            direct = ((selector.conversation_id is not None and conversation == selector.conversation_id)
                      or (selector.session_id is not None and session == selector.session_id))
            foreign = ((selector.conversation_id is not None and isinstance(conversation, str)
                        and conversation != selector.conversation_id)
                       or (selector.session_id is not None and isinstance(session, str)
                           and session != selector.session_id))
            if not has_ids:
                direct = True
            elif foreign and not direct:
                continue
            if has_ids and start is None and last_direct < 0 and not direct:
                continue  # before the extent of the selected id
            if has_ids and start is None and direct:
                extent.anchor()
            projected = project_bundle_trace_entry(entry)
            if len(candidates) >= limits.max_selected_lines or selected_bytes + len(part) > limits.max_selected_bytes:
                truncated, stopped_by, stop = True, "max_selected", True
                break
            selected_bytes += len(part)
            candidates.append((part_offset, ts, projected, direct, text))
            if direct:
                last_direct = len(candidates) - 1
        if last_line:
            break
    if has_ids and start is None:
        candidates = candidates[:last_direct + 1]
    lines = tuple(TraceLine(offset=offset, ts=ts, kind=projected["kind"], level=projected["level"],
                            data=projected["data"], matched=direct)
                  for offset, ts, projected, direct, _ in candidates)
    reason = None
    if physical["decoded"] == 0 and physical["corrupt"] > 0:
        status, reason = SourceStatus.UNAVAILABLE, "no_decodable_lines"
        counts["corrupt"] = physical["corrupt"]
    elif physical["decoded"] > 0 and physical["timed"] == 0:
        status, reason = SourceStatus.UNAVAILABLE, "no_timed_lines"
        counts["corrupt"], counts["untimed"] = physical["corrupt"], physical["untimed"]
    elif truncated or start_truncated:
        status = SourceStatus.TRUNCATED
    else:
        status = SourceStatus.AVAILABLE if lines else SourceStatus.EMPTY
    evidence = TraceEvidence(status, lines=lines, lines_in_window=in_window if start is not None else extent.count(),
                             corrupt_lines=counts["corrupt"], oversized_lines=counts["oversized"],
                             untimed_lines=counts["untimed"], truncated=truncated, start_truncated=start_truncated,
                             torn_tail=torn_tail, window_open=end is not None and stopped_by == "file_end",
                             stopped_by=stopped_by, reason=reason)
    return TraceReadResult(evidence, tuple(text for *_, text in candidates), bytes_read)


# ------------------------------------------------------ conversation events

@dataclass(frozen=True, slots=True)
class EventReadLimits:
    max_events: int = SECTION_LIMITS["conversation_events"]
    page_limit: int = MAX_EVENT_PAGE_LIMIT
    #: At most this many conversations are read for a session selector.
    max_conversations: int = 8
    #: Largest export file read (bytes).
    max_export_bytes: int = 64 * 1024 * 1024
    #: Margin added around the events' extent to select journal lines.
    trace_margin: timedelta = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class StoreEventSource:
    """Read through the `ConversationEventStore` port (Core's store, or any adapter of it)."""

    store: ConversationEventStore


@dataclass(frozen=True, slots=True)
class StateDatabaseEventSource:
    """Read a Core state database file strictly read-only (never migrated, never written)."""

    path: Path


@dataclass(frozen=True, slots=True)
class ExportEventSource:
    """Read a `jarvis.conversation-events.export` JSONL file."""

    path: Path


EventSource = StoreEventSource | StateDatabaseEventSource | ExportEventSource


class ReadOnlyStateDatabase:
    """The `run_serialized` seam of `SQLiteStateRepository`, over a read-only connection.

    Each call opens `file:<db>?mode=ro` (URI) with `PRAGMA query_only=ON` in a
    worker thread and closes it afterwards, so the running Jarvis keeps sole
    ownership of the file. Lets `SQLiteConversationEventStore` decode rows with
    its own codec checks without a writable repository.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _call(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        connection = self._connect()
        try:
            return fn(connection)
        finally:
            connection.close()

    async def run_serialized(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        return await asyncio.to_thread(self._call, fn)

    async def has_table(self, name: str) -> bool:
        row = await self.run_serialized(lambda connection: connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())
        return row is not None


def _within(stored: StoredConversationEvent, start: datetime | None, end: datetime | None) -> bool:
    at = stored.event.occurred_at
    return (start is None or at >= start) and (end is None or at <= end)


async def _pages(read: Callable[[int], Any], limits: EventReadLimits, budget: int) -> tuple[list[StoredConversationEvent],
                                                                                          int, bool]:
    events: list[StoredConversationEvent] = []
    skipped, cursor = 0, 0
    while True:
        page: ConversationEventPage = await read(cursor)
        events.extend(page.events)
        skipped += page.skipped_rows
        cursor = page.next_cursor
        if len(events) > budget:
            return events[:budget], skipped, True
        if not page.has_more:
            return events, skipped, False


async def _read_store(store: ConversationEventStore, selector: SessionSelector,
                      limits: EventReadLimits) -> tuple[list[StoredConversationEvent], int, bool]:
    start, end = selector.start, selector.end
    if selector.conversation_id is not None:
        events, skipped, truncated = await _pages(lambda cursor: store.list_conversation_events(
            selector.conversation_id, after_sequence=cursor, limit=limits.page_limit), limits, limits.max_events)
        events = [item for item in events if _within(item, start, end)
                  and (selector.session_id is None or item.event.session_id in (None, selector.session_id))]
        return events, skipped, truncated
    if selector.session_id is not None:
        tagged, skipped, truncated = await _pages(lambda cursor: store.list_events_by_id(
            "session_id", selector.session_id, after_sequence=cursor, limit=limits.page_limit), limits,
            limits.max_events)
        if not tagged:
            return [], skipped, truncated
        low = min(item.event.occurred_at for item in tagged)
        high = max(item.event.occurred_at for item in tagged)
        conversations = sorted({item.event.conversation_id for item in tagged})
        truncated = truncated or len(conversations) > limits.max_conversations
        events = {item.event.event_id: item for item in tagged}
        for conversation_id in conversations[:limits.max_conversations]:
            more, more_skipped, more_truncated = await _pages(lambda cursor, cid=conversation_id:
                                                              store.list_conversation_events(
                                                                  cid, after_sequence=cursor, limit=limits.page_limit),
                                                              limits, limits.max_events)
            skipped += more_skipped
            truncated = truncated or more_truncated
            for item in more:
                if item.event.session_id is None and low <= item.event.occurred_at <= high:
                    events.setdefault(item.event.event_id, item)
        selected = [item for item in events.values() if _within(item, start, end)]
        return selected[:limits.max_events], skipped, truncated or len(selected) > limits.max_events
    return await _pages(lambda cursor: store.list_events_in_time_range(
        start, end + timedelta(milliseconds=1), after_sequence=cursor, limit=limits.page_limit), limits,
        limits.max_events)


async def read_session_events(source: EventSource, selector: SessionSelector, *,
                              limits: EventReadLimits = EventReadLimits()) -> EventEvidence:
    """Conversation Events of the selected session, bounded; failures become a coverage status."""
    if isinstance(source, ExportEventSource):
        return await asyncio.to_thread(_read_export_source, source.path, selector, limits)
    if isinstance(source, StateDatabaseEventSource):
        if not Path(source.path).is_file():
            return EventEvidence(SourceStatus.MISSING, origin="store", reason="state_database_missing")
        database = ReadOnlyStateDatabase(source.path)
        try:
            if not await database.has_table("conversation_events"):
                return EventEvidence(SourceStatus.UNAVAILABLE, origin="store", reason="conversation_events_table_absent")
        except sqlite3.Error:
            return EventEvidence(SourceStatus.UNAVAILABLE, origin="store", reason="state_database_unreadable")
        store: ConversationEventStore = SQLiteConversationEventStore(database)  # type: ignore[arg-type]
    elif isinstance(source, StoreEventSource):
        store = source.store
    else:
        raise fail("event source must be a StoreEventSource, StateDatabaseEventSource or ExportEventSource")
    try:
        events, skipped, truncated = await _read_store(store, selector, limits)
    except ConversationEventStoreError:
        return EventEvidence(SourceStatus.UNAVAILABLE, origin="store", reason="store_read_failed")
    return _event_evidence("store", events, skipped, truncated, None)


def _event_evidence(origin: str, events: list[StoredConversationEvent], skipped: int, truncated: bool,
                    complete: bool | None) -> EventEvidence:
    if truncated:
        status = SourceStatus.TRUNCATED
    else:
        status = SourceStatus.AVAILABLE if events else SourceStatus.EMPTY
    return EventEvidence(status, origin=origin, events=tuple(events), skipped_rows=skipped, export_complete=complete,
                         truncated=truncated)


def _read_export_source(path: Path, selector: SessionSelector, limits: EventReadLimits) -> EventEvidence:
    try:
        size = Path(path).stat().st_size
    except FileNotFoundError:
        return EventEvidence(SourceStatus.MISSING, origin="export", reason="export_file_missing")
    except OSError:
        return EventEvidence(SourceStatus.UNAVAILABLE, origin="export", reason="export_unreadable")
    if size > limits.max_export_bytes:
        return EventEvidence(SourceStatus.UNAVAILABLE, origin="export", reason="export_too_large")
    try:
        with open(path, "rb") as handle:
            result = read_export(handle)
    except ExportFormatError:
        return EventEvidence(SourceStatus.UNAVAILABLE, origin="export", reason="export_invalid")
    except OSError:
        return EventEvidence(SourceStatus.UNAVAILABLE, origin="export", reason="export_unreadable")
    events = [item for item in result.events if _within(item, selector.start, selector.end)
              and (selector.conversation_id is None or item.event.conversation_id == selector.conversation_id)
              and (selector.session_id is None or item.event.session_id in (None, selector.session_id))]
    truncated = len(events) > limits.max_events
    return _event_evidence("export", events[:limits.max_events], result.skipped_rows, truncated, result.complete)


# ---------------------------------------------------- voice session reports

VOICE_REPORT_SCHEMA = "jarvis.voice_benchmark.session"
MAX_REPORT_FILES = 2048
MAX_REPORT_BYTES = 1024 * 1024


class _Undecodable(Exception):
    """A report file that is not JSON: it cannot be matched to a session, so it is counted as unreadable."""


def _report_projection(raw: bytes, wanted: frozenset[str]) -> VoiceSessionReport | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise _Undecodable from None
    if (not isinstance(payload, dict) or payload.get("schema") != VOICE_REPORT_SCHEMA
            or payload.get("schema_version") != 1 or payload.get("session_id") not in wanted):
        return None

    def token(value: object) -> str | None:
        return value if is_code_token(value) else None

    def hex64(value: object) -> str | None:
        return value if isinstance(value, str) and _HEX64.fullmatch(value) else None

    def number(value: object) -> float | int | None:
        return value if type(value) in (int, float) and math.isfinite(value) else None

    latency = []
    metrics = payload.get("latency_metrics") if isinstance(payload.get("latency_metrics"), dict) else {}
    for name in sorted(metrics):
        value = metrics[name]
        if is_code_token(name) and isinstance(value, dict) and type(value.get("count")) is int and value["count"] >= 0:
            latency.append((name, value["count"], number(value.get("min_ms")), number(value.get("max_ms")),
                            number(value.get("mean_ms"))))
    counts_raw = payload.get("event_counts") if isinstance(payload.get("event_counts"), dict) else {}
    counts = tuple((name, counts_raw[name]) for name in sorted(counts_raw)
                   if is_code_token(name) and type(counts_raw[name]) is int and counts_raw[name] >= 0)
    complete = payload.get("trace_evidence_complete")
    return VoiceSessionReport(
        sha256=hashlib.sha256(raw).hexdigest(), session_id=payload["session_id"],
        architecture=token(payload.get("architecture")), configuration_id=hex64(payload.get("configuration_id")),
        session_fingerprint=hex64(payload.get("session_fingerprint")),
        terminal_status=token(payload.get("terminal_status")),
        trace_evidence_complete=complete if type(complete) is bool else None,
        latency=tuple(latency[:32]), counts=counts[:32])


def read_voice_session_reports(directory: Path, session_ids: Iterable[str]) -> ReportEvidence:
    """`VoiceSessionMetricRecorder` reports (`<runtime>/benchmarks/voice-sessions/*.json`) of the given sessions."""
    wanted = frozenset(item for item in session_ids if is_opaque_id(item))
    try:
        names = sorted(entry.name for entry in os.scandir(directory)
                       if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False))
    except FileNotFoundError:
        return ReportEvidence(SourceStatus.MISSING, reason="reports_directory_missing")
    except OSError:
        return ReportEvidence(SourceStatus.UNAVAILABLE, reason="reports_directory_unreadable")
    truncated = len(names) > MAX_REPORT_FILES
    reports: list[VoiceSessionReport] = []
    unreadable = 0
    if wanted:
        for name in names[:MAX_REPORT_FILES]:
            try:
                with open(Path(directory) / name, "rb") as handle:
                    raw = handle.read(MAX_REPORT_BYTES + 1)
            except OSError:
                unreadable += 1
                continue
            if len(raw) > MAX_REPORT_BYTES:
                unreadable += 1
                continue
            try:
                report = _report_projection(raw, wanted)
            except _Undecodable:
                unreadable += 1
                continue
            if report is not None:
                reports.append(report)
    if truncated:
        status = SourceStatus.TRUNCATED
    else:
        status = SourceStatus.AVAILABLE if reports else SourceStatus.EMPTY
    return ReportEvidence(status, reports=tuple(reports),
                          reason="some_reports_unreadable" if unreadable else None)


# ---------------------------------------------------------------- service

@dataclass(frozen=True, slots=True)
class BundleCaptureResult:
    bundle: DiagnosticBundle
    #: None when no store was given.
    put: BundlePutResult | None = None


async def capture_diagnostic_bundle(selector: SessionSelector, *, captured_at: datetime,
                                    trace_path: Path | None = None, event_source: EventSource | None = None,
                                    reports_directory: Path | None = None, code: CodeIdentity | None = None,
                                    config_fingerprint: str | None = None, options: BundleOptions = BundleOptions(),
                                    store: BundleStore | None = None,
                                    trace_limits: TraceReadLimits = TraceReadLimits(),
                                    event_limits: EventReadLimits = EventReadLimits(),
                                    diagnostics: DiagnosticSink | None = None) -> BundleCaptureResult:
    """Read the session's evidence (bounded), build its bundle, and store it when a `BundleStore` is given.

    `captured_at` is injected (never read here). Sources left `None` are
    `not_requested`. The journal window is the selector's, else the Conversation
    Events extent widened by `event_limits.trace_margin`, else the file tail.
    Store errors propagate (`TestLabStoreError`); source failures do not.
    """
    if not isinstance(selector, SessionSelector):
        raise fail("capture_diagnostic_bundle takes a SessionSelector")
    context = CaptureContext(captured_at=captured_at, code=code, config_fingerprint=config_fingerprint)
    diagnose = SafeDiagnostics(diagnostics).emit
    events = (NOT_REQUESTED_EVENTS if event_source is None
              else await read_session_events(event_source, selector, limits=event_limits))
    start, end = selector.start, selector.end
    if start is None and end is None and events.events:
        start = min(item.event.occurred_at for item in events.events) - event_limits.trace_margin
        end = max(item.event.occurred_at for item in events.events) + event_limits.trace_margin
    trace_read = (TraceReadResult(NOT_REQUESTED_TRACE) if trace_path is None
                  else await asyncio.to_thread(read_session_trace, Path(trace_path), selector, start=start, end=end,
                                               limits=trace_limits))
    trace_summary = summarize(trace_read.raw_lines) if trace_read.raw_lines else None
    session_ids = {item.event.session_id for item in events.events if item.event.session_id is not None}
    session_ids.update(line.data["session_id"] for line in trace_read.evidence.lines
                       if line.matched and isinstance(line.data.get("session_id"), str))
    if selector.session_id is not None:
        session_ids.add(selector.session_id)
    reports = (NOT_REQUESTED_REPORTS if reports_directory is None
               else await asyncio.to_thread(read_voice_session_reports, Path(reports_directory), sorted(session_ids)))
    for source, status, reason in (("conversation_events", events.status, events.reason),
                                   ("runtime_journal", trace_read.evidence.status, trace_read.evidence.reason),
                                   ("voice_session_reports", reports.status, reports.reason)):
        if status in (SourceStatus.MISSING, SourceStatus.UNAVAILABLE, SourceStatus.TRUNCATED):
            diagnose("testlab_bundle_source_degraded", "DiagnosticBundle source not fully read",
                     level="warning", source=source, status=status.value, reason=reason)
    bundle = build_diagnostic_bundle(selector, context=context, events=events, trace=trace_read.evidence,
                                     reports=reports, trace_summary=trace_summary, options=options)
    put = await asyncio.to_thread(store.put_bundle, bundle) if store is not None else None
    coverage = bundle.document["coverage"]
    diagnose("testlab_bundle_captured", "DiagnosticBundle captured", bundle_id=bundle.bundle_id,
             stored=None if put is None else put.status.value, events=len(events.events),
             trace_lines=len(trace_read.evidence.lines), findings=len(bundle.findings),
             trace_status=trace_read.evidence.status.value, events_status=events.status.value,
             segments=coverage["segments"]["count"], warnings=list(coverage["warnings"]))
    return BundleCaptureResult(bundle, put)
