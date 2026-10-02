"""SQLite adapter of the Session Context store (handoff session-context-recording, Slice 02).

Port: `jarvis.ports.session_context.ContextRepository`. Contract:
`docs/session-context.md` (Persistence). Table `session_contexts` comes from
migration v5 of `sqlite_state`.

Like `sqlite_workspace_board`, it shares the state DB file, connection, lock
and worker thread of `SQLiteStateRepository` through `run_serialized`; every
multi-row write is one `immediate_transaction`.

Guarantees:

- `data` is the Context's `to_payload()`; every read decodes it with the
  strict domain `from_payload` and cross-checks the key columns. A failing
  row is `ContextStoreError`, never skipped or repaired;
- a row's identity (`jarvis_session_id`, `origin`, `created_at`) never
  changes: the upsert guards it in SQL and refuses with `context_conflict`;
- at most one active Context per Session and one `adopted` per Session are
  enforced by partial unique indexes; a violation is a `SessionContextError`
  with the domain's code, never a raw `IntegrityError`, and the whole
  transaction is rolled back;
- an active Context is never written into a closed Session (`session_closed`);
- any other `sqlite3.Error` is `ContextStoreUnavailable`.

The `put_context` statement is module-level so that a later Session write
(Slice 03: close + dormant Context in one transaction) can reuse it inside its
own `immediate_transaction`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import sqlite3
from typing import Any, TypeVar

from jarvis.adapters.sqlite_session_activity import append_activity
from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.session_activity import ActivityDraft
from jarvis.domain.session_context import (
    ContextOrigin, ContextStatus, SessionContext, SessionContextError, SessionContextErrorCode,
)
from jarvis.domain.workspace_board import SessionStatus
from jarvis.ports.session_context import ContextStoreError, ContextStoreUnavailable

T = TypeVar("T")
_TABLE = "session_contexts"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _context_row(row: sqlite3.Row) -> SessionContext:
    key = row["context_id"]
    try:
        context = SessionContext.from_payload(json.loads(row["data"]))
    except (ValueError, TypeError) as exc:  # JSONDecodeError and SessionContextError are ValueErrors
        raise ContextStoreError(_TABLE, key, f"{type(exc).__name__}: {exc}") from exc
    if (context.context_id != key or context.jarvis_session_id != row["jarvis_session_id"]
            or context.status.value != row["status"] or context.origin.value != row["origin"]):
        raise ContextStoreError(_TABLE, key, "key columns disagree with data")
    return context


def _session_status(conn: sqlite3.Connection, jarvis_session_id: str) -> str | None:
    row = conn.execute("SELECT status FROM jarvis_sessions WHERE jarvis_session_id=?", (jarvis_session_id,)).fetchone()
    return row[0] if row else None


def put_context(conn: sqlite3.Connection, context: SessionContext) -> None:
    """Upsert one Context inside the caller's transaction (sync, shared connection)."""

    status = _session_status(conn, context.jarvis_session_id)
    if status is None:
        raise SessionContextError(
            SessionContextErrorCode.INVALID_CONTEXT,
            f"context {context.context_id}: session {context.jarvis_session_id} does not exist",
        )
    if context.is_active and status != SessionStatus.OPEN.value:
        raise SessionContextError(
            SessionContextErrorCode.SESSION_CLOSED,
            f"context {context.context_id} cannot be active: session {context.jarvis_session_id} is closed",
        )
    try:
        cursor = conn.execute(
            "INSERT INTO session_contexts(context_id,jarvis_session_id,status,origin,created_at,activated_at,"
            "last_active_at,data) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(context_id) DO UPDATE SET "
            "status=excluded.status,activated_at=excluded.activated_at,last_active_at=excluded.last_active_at,"
            "data=excluded.data WHERE session_contexts.jarvis_session_id=excluded.jarvis_session_id "
            "AND session_contexts.origin=excluded.origin AND session_contexts.created_at=excluded.created_at",
            (context.context_id, context.jarvis_session_id, context.status.value, context.origin.value,
             context.created_at.isoformat(), context.activated_at.isoformat(), context.last_active_at.isoformat(),
             _json(context.to_payload())),
        )
    except sqlite3.IntegrityError as exc:
        # Second active (or second adopted) Context in the Session.
        raise SessionContextError(
            SessionContextErrorCode.CONTEXT_CONFLICT,
            f"context {context.context_id} refused by the store: {exc}",
        ) from exc
    if cursor.rowcount == 0:
        raise SessionContextError(
            SessionContextErrorCode.CONTEXT_CONFLICT,
            f"context {context.context_id} exists with another session, origin or creation time",
        )


class SQLiteContextRepository:
    """`ContextRepository` over the shared state DB (schema v5)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise ContextStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    async def get_context(self, context_id: str) -> SessionContext | None:
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM session_contexts WHERE context_id=?", (context_id,)).fetchone())
        return _context_row(row) if row else None

    async def list_contexts(self, jarvis_session_id: str) -> Sequence[SessionContext]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM session_contexts WHERE jarvis_session_id=? ORDER BY created_at, context_id",
            (jarvis_session_id,)).fetchall())
        return tuple(_context_row(row) for row in rows)

    async def active_context(self, jarvis_session_id: str) -> SessionContext | None:
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM session_contexts WHERE jarvis_session_id=? AND status=?",
            (jarvis_session_id, ContextStatus.ACTIVE.value)).fetchone())
        return _context_row(row) if row else None

    async def commit_contexts(self, changed: Sequence[SessionContext], *,
                              activity: Sequence[ActivityDraft] = ()) -> None:
        """One transaction; dormant rows first so the one-active index holds per statement.

        `activity` (Slice 04): the transition's ledger events, same transaction.
        """

        ordered = sorted(changed, key=lambda c: c.is_active)

        def write(conn: sqlite3.Connection) -> None:
            for context in ordered:
                put_context(conn, context)
            append_activity(conn, tuple(activity))

        await self._run(lambda c: immediate_transaction(c, write))

    async def insert_adopted_if_absent(self, context: SessionContext, *,
                                       activity: Sequence[ActivityDraft] = ()) -> bool:
        if context.origin is not ContextOrigin.ADOPTED or not context.is_active:
            raise SessionContextError(
                SessionContextErrorCode.INVALID_CONTEXT, "only an active adopted context can be adopted",
            )

        def insert(conn: sqlite3.Connection) -> bool:
            inserted = False

            def write(c: sqlite3.Connection) -> None:
                nonlocal inserted
                if _session_status(c, context.jarvis_session_id) != SessionStatus.OPEN.value:
                    return
                if c.execute("SELECT 1 FROM session_contexts WHERE jarvis_session_id=? LIMIT 1",
                             (context.jarvis_session_id,)).fetchone() is None:
                    put_context(c, context)
                    append_activity(c, tuple(activity))
                    inserted = True

            immediate_transaction(conn, write)
            return inserted

        return await self._run(insert)

    async def session_is_open(self, jarvis_session_id: str) -> bool:
        return await self._run(lambda c: _session_status(c, jarvis_session_id)) == SessionStatus.OPEN.value
