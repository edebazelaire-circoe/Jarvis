"""SQLite adapter of the Conversation Event store (Slice 02).

Contract: `docs/conversation-events.md` (Storage). Port:
`jarvis.ports.v2.ConversationEventStore`.

It shares the operational state DB file, connection, lock and worker thread of
`SQLiteStateRepository` (schema v2, `conversation_events` table): no second
database, no second connection model. Lifecycle (initialize, migration, close)
belongs to that repository.

Guarantees:

- `append`/`append_many` return only after `COMMIT` (WAL + `synchronous=FULL`);
  a failure rolls the whole batch back and raises `ConversationEventStoreError`;
- the stored `data` column is the encoded canonical event and is decoded through
  the contract codec on every read; extracted columns are cross-checked, and a
  row that fails either check is skipped, counted and diagnosed, never returned;
- duplicate (identical) and conflicting `event_id` are result statuses
  (`is_duplicate_event` semantics); a conflict keeps the first copy and emits a
  diagnostic without content.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
import json
import re
import sqlite3
from typing import Any, TypeVar

from jarvis.adapters.sqlite_state import SQLiteStateRepository, rollback_after_failure
from jarvis.domain.conversation_event_store import (
    DEFAULT_EVENT_PAGE_LIMIT, DEFAULT_SUMMARY_PAGE_LIMIT, MAX_APPEND_BATCH, MAX_EVENT_PAGE_LIMIT,
    MAX_SUMMARY_PAGE_LIMIT, AppendResult, AppendStatus, ConversationEventPage, ConversationEventRetentionPolicy,
    ConversationEventStoreError, ConversationEventSummary, ConversationEventSummaryPage, RetentionReport,
    RetentionSkipReason, StoredConversationEvent, check_cursor, check_limit, check_lookup,
)
from jarvis.domain.conversation_events import (
    SPAN_OPENER, ConversationEvent, ConversationEventConflictError, ConversationEventError, ConversationEventType,
    decode_conversation_event, encode_conversation_event, format_event_time,
    is_duplicate_event, parse_event_time,
)
from jarvis.domain.v2 import ConversationStatus, utc_now
from jarvis.domain.voice_state import state_id
from jarvis.ports.v2 import ConversationEventArchiver, DiagnosticSink

T = TypeVar("T")

#: Columns copied from the encoded event; each must equal the payload on read.
_EXTRACTED = ("event_id", "conversation_id", "session_id", "event_type", "actor", "visibility", "occurred_at",
              "span_id", "turn_id", "correlation_id", "task_id", "work_id", "speech_id", "outcome_id")
_SELECT = "SELECT sequence, recorded_at, " + ", ".join(_EXTRACTED) + ", data FROM conversation_events"
_INSERT = ("INSERT INTO conversation_events(" + ", ".join(_EXTRACTED) + ", recorded_at, data) VALUES("
           + ",".join("?" * (len(_EXTRACTED) + 2)) + ")")
_SUMMARY = ("count(*), min(sequence), max(sequence), min(occurred_at), max(occurred_at), max(recorded_at)")
#: Unreadable-row diagnostics are emitted once per sequence per store instance
#: (live polling would otherwise repeat them every second); counting never stops.
_MAX_DIAGNOSED_ROWS = 1024

_KIND_CONFLICT = "core.conversation_events.append_conflict"
_KIND_UNREADABLE = "core.conversation_events.row_unreadable"
_KIND_SUMMARY_UNREADABLE = "core.conversation_events.summary_unreadable"
_KIND_RETENTION = "core.conversation_events.retention_applied"
_KIND_ARCHIVE_FAILED = "core.conversation_events.archive_failed"


class _UnreadableRow(Exception):
    def __init__(self, sequence: int, reason: str, detail: str) -> None:
        super().__init__(reason)
        self.sequence, self.reason, self.detail = sequence, reason, detail


def _decode_row(row: sqlite3.Row) -> StoredConversationEvent:
    """Never trust a raw row: codec decode + column cross-check, or `_UnreadableRow`."""
    sequence = row["sequence"]
    try:
        payload = json.loads(row["data"])
        event = decode_conversation_event(payload)
    except json.JSONDecodeError as exc:
        raise _UnreadableRow(sequence, "invalid_json", f"JSONDecodeError at position {exc.pos}") from None
    except ConversationEventError as exc:
        # Contract error messages name fields and rules, never values.
        raise _UnreadableRow(sequence, "invalid_event", str(exc)) from None
    except (TypeError, RecursionError) as exc:
        raise _UnreadableRow(sequence, "invalid_event", type(exc).__name__) from None
    mismatched = [name for name in _EXTRACTED if row[name] != payload[name]]
    if mismatched:
        raise _UnreadableRow(sequence, "column_mismatch", "columns disagree with data: " + ", ".join(mismatched))
    try:
        recorded_at = parse_event_time(row["recorded_at"], "recorded_at")
    except ConversationEventError:
        raise _UnreadableRow(sequence, "invalid_recorded_at", "recorded_at is not a wire time") from None
    return StoredConversationEvent(sequence=sequence, recorded_at=recorded_at, event=event)


def _summary(row: Sequence[Any], conversation_id: str, session_id: str | None) -> ConversationEventSummary:
    """Aggregated columns are raw text: parse strictly, or raise `ConversationEventError`."""
    count, first, last, first_at, last_at, recorded = row
    return ConversationEventSummary(conversation_id, session_id, count, first, last,
                                    parse_event_time(first_at, "first_occurred_at"),
                                    parse_event_time(last_at, "last_occurred_at"),
                                    parse_event_time(recorded, "last_recorded_at"))


class SQLiteConversationEventStore:
    """`ConversationEventStore` over the Core state DB. Owned by `JarvisCoreApplication`."""

    def __init__(self, state: SQLiteStateRepository, *, diagnostics: DiagnosticSink | None = None,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self._state = state
        self._diagnostics = diagnostics
        self._clock = clock
        self._diagnosed_rows: set[int] = set()
        self._diagnosed_summaries: set[tuple[str, str | None]] = set()
        #: Rows skipped by reads since construction (every occurrence).
        self.unreadable_rows = 0
        #: Diagnostics the sink refused; the storage outcome stands regardless.
        self.diagnostic_failures = 0

    # ------------------------------------------------------------ plumbing

    async def _run(self, fn: Callable[[sqlite3.Connection], T], operation: str) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            raise ConversationEventStoreError(f"conversation event {operation} failed: {type(exc).__name__}: {exc}") from exc

    def _diagnose(self, kind: str, message: str, level: str, data: dict[str, Any]) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.emit(kind, message, level=level, data=data)
        except Exception:
            # A broken diagnostic sink cannot undo a committed append or turn a
            # read into a failure; the host inspects `diagnostic_failures`.
            self.diagnostic_failures += 1

    def _report_unreadable(self, rows: Sequence[_UnreadableRow]) -> None:
        for row in rows:
            self.unreadable_rows += 1
            if row.sequence in self._diagnosed_rows or len(self._diagnosed_rows) >= _MAX_DIAGNOSED_ROWS:
                continue
            self._diagnosed_rows.add(row.sequence)
            self._diagnose(_KIND_UNREADABLE, "Stored conversation event skipped: it does not decode", "error",
                           {"sequence": row.sequence, "reason": row.reason, "detail": row.detail})

    def _summaries(self, rows: Sequence[Any], limit: int, conversation_id: str | None, *,
                   cursor_index: int) -> ConversationEventSummaryPage:
        """Build a summary page; a group whose aggregated times do not parse is skipped and diagnosed.

        `rows` are `(key, count, min seq, max seq, min occurred, max occurred, max recorded)`;
        `key` is the conversation id (`conversation_id` None) or the session id. The
        cursor comes from the integer sequence columns, so it advances past skipped groups.
        """
        summaries, skipped = [], 0
        scanned = rows[:limit]
        for row in scanned:
            key = (row[0], None) if conversation_id is None else (conversation_id, row[0])
            try:
                summaries.append(_summary(tuple(row)[1:], *key))
            except ConversationEventError as exc:
                skipped += 1
                if key not in self._diagnosed_summaries and len(self._diagnosed_summaries) < _MAX_DIAGNOSED_ROWS:
                    self._diagnosed_summaries.add(key)
                    self._diagnose(_KIND_SUMMARY_UNREADABLE,
                                   "Conversation event summary skipped: stored times do not parse", "error",
                                   {"conversation_id": key[0], "session_id": key[1],
                                    "first_sequence": row[2], "last_sequence": row[3], "detail": str(exc)})
        next_cursor = scanned[-1][cursor_index] if scanned else None
        return ConversationEventSummaryPage(tuple(summaries), next_cursor, len(rows) > limit, skipped)

    @staticmethod
    def _page(where: str, params: tuple[Any, ...], after_sequence: int,
              limit: int) -> Callable[[sqlite3.Connection], tuple[ConversationEventPage, list[_UnreadableRow]]]:
        check_cursor(after_sequence)
        check_limit(limit, MAX_EVENT_PAGE_LIMIT)

        def read(conn: sqlite3.Connection):
            rows = conn.execute(f"{_SELECT} WHERE {where} AND sequence > ? ORDER BY sequence LIMIT ?",
                                (*params, after_sequence, limit + 1)).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            events, unreadable = [], []
            for row in rows:
                try:
                    events.append(_decode_row(row))
                except _UnreadableRow as exc:
                    unreadable.append(exc)
            next_cursor = rows[-1]["sequence"] if rows else after_sequence
            return ConversationEventPage(tuple(events), next_cursor, has_more, len(unreadable)), unreadable
        return read

    async def _read_page(self, where: str, params: tuple[Any, ...], after_sequence: int, limit: int,
                         operation: str) -> ConversationEventPage:
        page, unreadable = await self._run(self._page(where, params, after_sequence, limit), operation)
        self._report_unreadable(unreadable)
        return page

    # -------------------------------------------------------------- append

    async def append(self, event: ConversationEvent) -> AppendResult:
        return (await self.append_many((event,)))[0]

    async def append_many(self, events: Sequence[ConversationEvent]) -> tuple[AppendResult, ...]:
        """Append in one transaction: all rows commit together or none does."""
        events = tuple(events)
        if len(events) > MAX_APPEND_BATCH:
            raise ValueError(f"append batch exceeds {MAX_APPEND_BATCH} events")
        if not events:
            return ()
        # Validate everything before touching storage: `encode` re-decodes, so an
        # invalid or non-event value raises `ConversationEventError` here.
        encoded = [encode_conversation_event(event) for event in events]
        recorded_at = format_event_time(self._clock())

        def write(conn: sqlite3.Connection):
            results: list[AppendResult] = []
            conflicts: list[tuple[ConversationEvent, int, str]] = []
            unreadable: list[_UnreadableRow] = []
            conn.execute("BEGIN IMMEDIATE")
            try:
                for event, payload in zip(events, encoded):
                    row = conn.execute(f"{_SELECT} WHERE event_id=?", (event.event_id,)).fetchone()
                    if row is None:
                        cursor = conn.execute(_INSERT, (*(payload[name] for name in _EXTRACTED), recorded_at,
                                                        json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                                                                   sort_keys=True)))
                        results.append(AppendResult(event.event_id, cursor.lastrowid, AppendStatus.APPENDED))
                        continue
                    sequence = row["sequence"]
                    try:
                        stored = _decode_row(row).event
                        is_duplicate_event(stored, event)
                        results.append(AppendResult(event.event_id, sequence, AppendStatus.DUPLICATE))
                    except ConversationEventConflictError:
                        conflicts.append((event, sequence, "payload_differs"))
                        results.append(AppendResult(event.event_id, sequence, AppendStatus.CONFLICT))
                    except _UnreadableRow as exc:
                        unreadable.append(exc)
                        conflicts.append((event, sequence, "stored_copy_unreadable"))
                        results.append(AppendResult(event.event_id, sequence, AppendStatus.CONFLICT))
                conn.execute("COMMIT")
            except BaseException as exc:
                rollback_after_failure(conn, exc)
                raise
            return tuple(results), conflicts, unreadable

        results, conflicts, unreadable = await self._run(write, "append")
        self._report_unreadable(unreadable)
        for event, sequence, reason in conflicts:
            self._diagnose(_KIND_CONFLICT, "Conversation event id already stored with another payload; first copy kept",
                           "warning", {"event_id": event.event_id, "stored_sequence": sequence, "reason": reason,
                                       "conversation_id": event.conversation_id,
                                       "event_type": event.event_type.value, "producer": event.producer})
        return results

    # --------------------------------------------------------------- reads

    async def get_event(self, event_id: str) -> StoredConversationEvent | None:
        """None when absent **or** unreadable (the latter is counted and diagnosed)."""
        state_id(event_id, "event_id")

        def read(conn: sqlite3.Connection):
            row = conn.execute(f"{_SELECT} WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                return None, []
            try:
                return _decode_row(row), []
            except _UnreadableRow as exc:
                return None, [exc]

        stored, unreadable = await self._run(read, "lookup")
        self._report_unreadable(unreadable)
        return stored

    async def list_conversation_events(self, conversation_id: str, *, after_sequence: int = 0,
                                       limit: int = DEFAULT_EVENT_PAGE_LIMIT) -> ConversationEventPage:
        state_id(conversation_id, "conversation_id")
        return await self._read_page("conversation_id=?", (conversation_id,), after_sequence, limit, "query")

    async def list_events_in_time_range(self, start: datetime, end: datetime, *, conversation_id: str | None = None,
                                        after_sequence: int = 0,
                                        limit: int = DEFAULT_EVENT_PAGE_LIMIT) -> ConversationEventPage:
        """Events with `start <= occurred_at < end` (producer clock), in sequence order."""
        try:
            low, high = format_event_time(start), format_event_time(end)
        except ConversationEventError as exc:
            raise ValueError(f"time range bounds: {exc}") from None
        if low > high:
            raise ValueError("time range start must not be after end")
        where, params = "occurred_at >= ? AND occurred_at < ?", (low, high)
        if conversation_id is not None:
            state_id(conversation_id, "conversation_id")
            where, params = f"conversation_id=? AND {where}", (conversation_id, *params)
        return await self._read_page(where, params, after_sequence, limit, "query")

    async def list_events_by_id(self, field: str, value: str, *, conversation_id: str | None = None,
                                after_sequence: int = 0, limit: int = DEFAULT_EVENT_PAGE_LIMIT) -> ConversationEventPage:
        check_lookup(field, value)
        # `field` is one of LOOKUP_FIELDS (checked above), never caller text.
        where, params = f"{field}=?", (value,)
        if conversation_id is not None:
            state_id(conversation_id, "conversation_id")
            where, params = f"{where} AND conversation_id=?", (value, conversation_id)
        return await self._read_page(where, params, after_sequence, limit, "query")

    async def list_conversations(self, *, before_sequence: int | None = None,
                                 limit: int = DEFAULT_SUMMARY_PAGE_LIMIT) -> ConversationEventSummaryPage:
        """Most recent store activity first (by last sequence)."""
        if before_sequence is not None:
            check_cursor(before_sequence, "before_sequence")
        check_limit(limit, MAX_SUMMARY_PAGE_LIMIT)

        def read(conn: sqlite3.Connection):
            return conn.execute(
                f"SELECT conversation_id, {_SUMMARY} FROM conversation_events GROUP BY conversation_id "
                "HAVING ? IS NULL OR max(sequence) < ? ORDER BY max(sequence) DESC LIMIT ?",
                (before_sequence, before_sequence, limit + 1)).fetchall()

        return self._summaries(await self._run(read, "listing"), limit, None, cursor_index=3)

    async def list_sessions(self, conversation_id: str, *, after_sequence: int = 0,
                            limit: int = DEFAULT_SUMMARY_PAGE_LIMIT) -> ConversationEventSummaryPage:
        """Sessions of one conversation by first appearance; events without session form a `None` group."""
        state_id(conversation_id, "conversation_id")
        check_cursor(after_sequence)
        check_limit(limit, MAX_SUMMARY_PAGE_LIMIT)

        def read(conn: sqlite3.Connection):
            return conn.execute(
                f"SELECT session_id, {_SUMMARY} FROM conversation_events WHERE conversation_id=? "
                "GROUP BY session_id HAVING min(sequence) > ? ORDER BY min(sequence) LIMIT ?",
                (conversation_id, after_sequence, limit + 1)).fetchall()

        return self._summaries(await self._run(read, "listing"), limit, conversation_id, cursor_index=2)

    # ----------------------------------------------------------- retention

    @staticmethod
    def _retention_candidates(conn: sqlite3.Connection, cutoff: str, conversation_id: str | None = None):
        """Closed conversations that are idle or unreadable, with their blocking flags (see `_CANDIDATES`)."""
        only = "AND e.conversation_id = :only" if conversation_id is not None else ""
        return conn.execute(_CANDIDATES.format(only=only), {
            "closed": ConversationStatus.CLOSED.value, "cutoff": cutoff, "glob": _WIRE_TIME_GLOB,
            "only": conversation_id,
        })

    async def apply_retention(self, policy: ConversationEventRetentionPolicy, *,
                              archive: ConversationEventArchiver | None = None) -> RetentionReport:
        """Prune events of closed idle conversations; a no-op unless `policy.enabled`.

        Blocked conversations (open span, unreadable row) are excluded **before**
        the per-run budget is applied, so they can never starve prunable ones;
        they are only counted. Per selected conversation: optional
        `archive(summary)`, then one transaction that re-evaluates the same SQL
        predicate and deletes up to the selected sequence. Never touches
        `conversations`, `turns` or any other table.
        """
        if not isinstance(policy, ConversationEventRetentionPolicy):
            raise ValueError("retention policy must be ConversationEventRetentionPolicy")
        if not policy.enabled:
            return RetentionReport(enabled=False, cutoff=None)
        cutoff_time = self._clock() - policy.max_age
        cutoff = format_event_time(cutoff_time)

        def select(conn: sqlite3.Connection):
            selected: list[ConversationEventSummary] = []
            open_span = unreadable = 0
            for row in self._retention_candidates(conn, cutoff):
                if row["open_span"]:
                    open_span += 1
                    continue
                try:
                    if row["unreadable"]:
                        raise ConversationEventError("stored row unreadable")
                    summary = _summary(tuple(row)[1:7], row["conversation_id"], None)
                except ConversationEventError:
                    # Unknown type, invalid JSON or a time that does not parse:
                    # the conversation is blocked, never deleted, never budgeted.
                    unreadable += 1
                    continue
                if len(selected) < policy.max_conversations_per_run:
                    selected.append(summary)
            return selected, open_span, unreadable

        pruned: list[tuple[str, int]] = []
        skipped: list[tuple[str, RetentionSkipReason]] = []
        selected, blocked_open_span, blocked_unreadable = await self._run(select, "retention")
        for summary in selected:
            conversation_id = summary.conversation_id
            if archive is not None:
                try:
                    await archive(summary)
                except Exception as exc:
                    self._diagnose(_KIND_ARCHIVE_FAILED, "Conversation event archive failed; events kept", "error",
                                   {"conversation_id": conversation_id, "error_class": type(exc).__name__})
                    skipped.append((conversation_id, RetentionSkipReason.ARCHIVE_FAILED))
                    continue

            def delete(conn: sqlite3.Connection, summary: ConversationEventSummary = summary):
                conn.execute("BEGIN IMMEDIATE")
                try:
                    reason = _recheck(self._retention_candidates(conn, cutoff, summary.conversation_id).fetchone(),
                                      conn, summary)
                    deleted = 0
                    if reason is None:
                        deleted = conn.execute(
                            "DELETE FROM conversation_events WHERE conversation_id=? AND sequence <= ?",
                            (summary.conversation_id, summary.last_sequence)).rowcount
                    conn.execute("COMMIT")
                except BaseException as exc:
                    rollback_after_failure(conn, exc)
                    raise
                return reason, deleted

            reason, deleted = await self._run(delete, "retention")
            if reason is None:
                pruned.append((conversation_id, deleted))
            else:
                skipped.append((conversation_id, reason))
        report = RetentionReport(enabled=True, cutoff=cutoff_time, pruned=tuple(pruned), skipped=tuple(skipped),
                                 blocked_open_span=blocked_open_span, blocked_unreadable=blocked_unreadable)
        self._diagnose(_KIND_RETENTION, "Conversation event retention applied", "info", {
            "cutoff": cutoff, "conversations_pruned": len(pruned), "events_deleted": sum(n for _, n in pruned),
            "skipped": {reason.value: sum(1 for _, r in skipped if r is reason) for reason in RetentionSkipReason
                        if any(r is reason for _, r in skipped)},
            "blocked_open_span": blocked_open_span, "blocked_unreadable": blocked_unreadable,
        })
        return report


def _recheck(row: sqlite3.Row | None, conn: sqlite3.Connection,
             summary: ConversationEventSummary) -> RetentionSkipReason | None:
    """Reason a selected conversation may no longer be pruned, inside the delete transaction."""
    if row is None:
        status = conn.execute("SELECT json_extract(data,'$.status') FROM conversations WHERE id=?",
                              (summary.conversation_id,)).fetchone()
        if status is None or status[0] != ConversationStatus.CLOSED.value:
            return RetentionSkipReason.NOT_CLOSED
        return RetentionSkipReason.NEW_ACTIVITY  # newest recorded_at is no longer before the cutoff
    if row["last_sequence"] != summary.last_sequence:
        return RetentionSkipReason.NEW_ACTIVITY
    if row["open_span"]:
        return RetentionSkipReason.OPEN_SPAN
    if row["unreadable"]:
        return RetentionSkipReason.UNREADABLE
    return None


def _sql_literals(values) -> str:
    """Inline closed enum vocabularies only (shape checked), never caller text."""
    values = tuple(values)
    if not all(re.fullmatch(r"[a-z][a-z0-9_.]*", value) for value in values):
        raise ValueError("retention SQL literal outside the event vocabulary shape")
    return ", ".join(f"'{value}'" for value in values)


_WIRE_TIME_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z"

#: Retention predicate, one SQL definition for selection and for the in-transaction
#: re-check. A closed conversation is a candidate when its newest `recorded_at` is
#: before the cutoff, or when a row is unreadable (so the block is counted). Flags:
#: - `unreadable`: some row has an unknown `event_type`, invalid JSON `data`, or an
#:   `occurred_at`/`recorded_at` that is not a wire time;
#: - `open_span`: some span open event has no close of a matching type for its
#:   `span_id`. A span orphaned by a crash therefore blocks forever (documented
#:   known limit; spans are never auto-closed).
_CANDIDATES = (
    "WITH span_pairs(close_type, open_type) AS (VALUES "
    + ", ".join(f"('{close.value}', '{opener.value}')" for close, opener in SPAN_OPENER.items())
    + """),
    candidates AS (
        SELECT e.conversation_id AS conversation_id, count(*) AS event_count,
               min(e.sequence) AS first_sequence, max(e.sequence) AS last_sequence,
               min(e.occurred_at) AS first_occurred_at, max(e.occurred_at) AS last_occurred_at,
               max(e.recorded_at) AS last_recorded_at,
               max(e.event_type NOT IN ({known}) OR NOT json_valid(e.data)
                   OR e.occurred_at NOT GLOB :glob OR e.recorded_at NOT GLOB :glob) AS unreadable,
               EXISTS (SELECT 1 FROM conversation_events o
                       WHERE o.conversation_id = e.conversation_id AND o.span_id IS NOT NULL
                         AND o.event_type IN ({opens})
                         AND NOT EXISTS (SELECT 1 FROM conversation_events x
                                         JOIN span_pairs p ON p.close_type = x.event_type
                                         WHERE x.conversation_id = o.conversation_id AND x.span_id = o.span_id
                                           AND p.open_type = o.event_type)) AS open_span
        FROM conversation_events e JOIN conversations c ON c.id = e.conversation_id
        WHERE json_extract(c.data, '$.status') = :closed {{only}}
        GROUP BY e.conversation_id
        HAVING max(e.recorded_at) < :cutoff OR unreadable)
    SELECT conversation_id, event_count, first_sequence, last_sequence, first_occurred_at, last_occurred_at,
           last_recorded_at, unreadable, open_span
    FROM candidates ORDER BY last_sequence""".format(
        known=_sql_literals(t.value for t in ConversationEventType),
        opens=_sql_literals(sorted({opener.value for opener in SPAN_OPENER.values()})),
    )
)
