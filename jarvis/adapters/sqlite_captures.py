"""SQLite adapter of the capture owner's durable state (handoff session-context-recording, Slice 05).

Port: `jarvis.ports.capture.CaptureRepository`. Contract: `docs/capture.md`.
Table `captures` comes from migration v7 of `sqlite_state`; like
`sqlite_artifacts`, the adapter shares the state DB connection, lock and
worker thread through `run_serialized`, and every write is one
`immediate_transaction` that also appends its activity events
(`append_activity`): a capture transition and its `capture.*` event commit or
roll back together.

Guarantees:

- `data` is the record's `to_payload()`; every read decodes it strictly and
  cross-checks the key columns (`CaptureStoreError`, never skipped or
  repaired);
- an insert refuses a second open continuous capture on the same
  channel/device (`already_active`), checked in the transaction and by the
  partial unique index;
- an update is a compare-and-swap on the previous row's exact `data`, after
  the domain guard `check_capture_update` (identity fixed, state machine,
  terminal frozen);
- any other `sqlite3.Error` is `CaptureStoreUnavailable`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import sqlite3
from typing import TypeVar

from jarvis.adapters.sqlite_session_activity import append_activity, dump_json, utc_key
from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.capture import (
    OPEN_STATES, CaptureError, CaptureErrorCode, CaptureMode, CaptureRecord, check_capture_id, check_capture_update,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent
from jarvis.ports.capture import CaptureStoreError, CaptureStoreUnavailable

T = TypeVar("T")
_TABLE = "captures"
MAX_CAPTURE_LIMIT = 256
_OPEN = tuple(sorted(state.value for state in OPEN_STATES))


def _row(row: sqlite3.Row) -> CaptureRecord:
    key = row["capture_id"]
    try:
        record = CaptureRecord.from_payload(json.loads(row["data"]))
    except (ValueError, TypeError) as exc:
        raise CaptureStoreError(_TABLE, key, f"{type(exc).__name__}: {exc}") from exc
    if (record.capture_id != key or record.channel.value != row["channel"] or record.mode.value != row["mode"]
            or record.device != row["device"] or record.state.value != row["state"]
            or record.jarvis_session_id != row["jarvis_session_id"] or record.context_id != row["context_id"]
            or record.artifact_id != row["artifact_id"] or record.error_code != row["error_code"]
            or utc_key(record.created_at) != row["created_at"]):
        raise CaptureStoreError(_TABLE, key, "key columns disagree with data")
    return record


def _check_limit(limit: object) -> int:
    if type(limit) is not int or not 1 <= limit <= MAX_CAPTURE_LIMIT:
        raise CaptureError(CaptureErrorCode.INVALID_CAPTURE, f"limit must be in 1..{MAX_CAPTURE_LIMIT}")
    return limit


class SQLiteCaptureRepository:
    """`CaptureRepository` over the shared state DB (schema v7)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise CaptureStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    async def _transaction(self, write: Callable[[sqlite3.Connection], T]) -> T:
        result: list[T] = []
        await self._run(lambda c: immediate_transaction(c, lambda conn: result.append(write(conn))))
        return result[0]

    async def insert_capture(self, record: CaptureRecord, *,
                             activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        if not isinstance(record, CaptureRecord) or not record.is_open:
            raise CaptureError(CaptureErrorCode.INVALID_CAPTURE, "expected an open CaptureRecord")

        def write(conn: sqlite3.Connection) -> tuple[ActivityEvent, ...]:
            if record.mode is CaptureMode.CONTINUOUS:
                holder = conn.execute(
                    f"SELECT capture_id FROM captures WHERE channel=? AND device=? AND mode=? "
                    f"AND state IN ({','.join('?' * len(_OPEN))})",
                    (record.channel.value, record.device, CaptureMode.CONTINUOUS.value, *_OPEN)).fetchone()
                if holder is not None:
                    raise CaptureError(CaptureErrorCode.ALREADY_ACTIVE,
                                       f"capture {holder[0]} already holds {record.channel.value}/{record.device}",
                                       capture_id=holder[0])
            try:
                conn.execute(
                    "INSERT INTO captures(capture_id,channel,mode,device,state,created_at,updated_at,"
                    "jarvis_session_id,context_id,artifact_id,error_code,data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (record.capture_id, record.channel.value, record.mode.value, record.device, record.state.value,
                     utc_key(record.created_at), utc_key(record.updated_at), record.jarvis_session_id,
                     record.context_id, record.artifact_id, record.error_code, dump_json(record.to_payload())))
            except sqlite3.IntegrityError as exc:
                raise CaptureError(CaptureErrorCode.INVALID_CAPTURE,
                                   f"capture {record.capture_id} refused by the store: {exc}") from exc
            return append_activity(conn, tuple(activity))

        return await self._transaction(write)

    async def update_capture(self, previous: CaptureRecord, updated: CaptureRecord, *,
                             activity: Sequence[ActivityDraft] = ()) -> tuple[ActivityEvent, ...]:
        check_capture_update(previous, updated)

        def write(conn: sqlite3.Connection) -> tuple[ActivityEvent, ...]:
            cursor = conn.execute(
                "UPDATE captures SET state=?, updated_at=?, artifact_id=?, error_code=?, data=? "
                "WHERE capture_id=? AND data=?",
                (updated.state.value, utc_key(updated.updated_at), updated.artifact_id, updated.error_code,
                 dump_json(updated.to_payload()), previous.capture_id, dump_json(previous.to_payload())))
            if cursor.rowcount == 0:
                exists = conn.execute("SELECT 1 FROM captures WHERE capture_id=?",
                                      (previous.capture_id,)).fetchone()
                code = CaptureErrorCode.INVALID_TRANSITION if exists else CaptureErrorCode.CAPTURE_NOT_FOUND
                raise CaptureError(code, f"capture {previous.capture_id} changed since it was read"
                                   if exists else f"capture {previous.capture_id} does not exist",
                                   capture_id=previous.capture_id)
            return append_activity(conn, tuple(activity))

        return await self._transaction(write)

    async def get_capture(self, capture_id: str) -> CaptureRecord | None:
        check_capture_id(capture_id)
        row = await self._run(lambda c: c.execute("SELECT * FROM captures WHERE capture_id=?",
                                                  (capture_id,)).fetchone())
        return _row(row) if row else None

    async def open_captures(self, *, limit: int) -> Sequence[CaptureRecord]:
        limit = _check_limit(limit)
        rows = await self._run(lambda c: c.execute(
            f"SELECT * FROM captures WHERE state IN ({','.join('?' * len(_OPEN))}) "
            "ORDER BY created_at, capture_id LIMIT ?", (*_OPEN, limit)).fetchall())
        return tuple(_row(row) for row in rows)

    async def recent_captures(self, *, limit: int) -> Sequence[CaptureRecord]:
        limit = _check_limit(limit)
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM captures ORDER BY created_at DESC, capture_id DESC LIMIT ?", (limit,)).fetchall())
        return tuple(_row(row) for row in rows)
