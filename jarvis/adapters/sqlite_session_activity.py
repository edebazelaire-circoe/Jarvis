"""SQLite adapter of the Session activity ledger (handoff session-context-recording, Slice 04).

Port: `jarvis.ports.artifacts.ActivityLedger`. Contract: `docs/artifacts.md`
(Activity ledger). Table `session_activity` comes from migration v6 of
`sqlite_state`; it shares the state DB connection through `run_serialized`.

`append_activity(conn, drafts)` is module-level: every writer that changes a
Session, a Context or an Artifact calls it **inside its own transaction**
(`commit_switch`, `commit_contexts`, `insert_adopted_if_absent`, the artifact
store), so the fact and its event commit or roll back together.

Guarantees: `seq` is SQLite `AUTOINCREMENT` (monotonic per file, never
reused); `data` is the draft's canonical payload, decoded strictly and
cross-checked against the key columns on read (`ArtifactStoreError`, never
skipped); reads are bounded by `ActivityQuery.limit`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, TypeVar

from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.session_activity import ActivityDraft, ActivityError, ActivityEvent, ActivityQuery
from jarvis.ports.artifacts import ArtifactStoreError, ArtifactStoreUnavailable

T = TypeVar("T")
_TABLE = "session_activity"


def utc_key(value: datetime) -> str:
    """Fixed-width UTC text of an aware datetime: lexicographic order is time order."""

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def append_activity(conn: sqlite3.Connection, drafts: Sequence[ActivityDraft]) -> tuple[ActivityEvent, ...]:
    """Insert `drafts` in order inside the caller's transaction; return them with their `seq`."""

    events = []
    for draft in drafts:
        if not isinstance(draft, ActivityDraft):
            raise ActivityError(f"expected an ActivityDraft, got {type(draft).__name__}")
        try:
            cursor = conn.execute(
                "INSERT INTO session_activity(event_id,kind,occurred_at,jarvis_session_id,context_id,data) "
                "VALUES(?,?,?,?,?,?)",
                (draft.event_id, draft.kind.value, utc_key(draft.occurred_at), draft.jarvis_session_id,
                 draft.context_id, dump_json(draft.to_payload())),
            )
        except sqlite3.IntegrityError as exc:
            raise ActivityError(f"event {draft.event_id} already recorded: {exc}") from exc
        events.append(ActivityEvent(seq=int(cursor.lastrowid), draft=draft))
    return tuple(events)


def _event_row(row: sqlite3.Row) -> ActivityEvent:
    seq = row["seq"]
    try:
        payload = json.loads(row["data"])
        if not isinstance(payload, dict):
            raise ValueError("data is not an object")
        event = ActivityEvent.from_payload({**payload, "seq": seq})
    except (ValueError, TypeError) as exc:
        raise ArtifactStoreError(_TABLE, str(seq), f"{type(exc).__name__}: {exc}") from exc
    if (event.event_id != row["event_id"] or event.kind.value != row["kind"]
            or event.jarvis_session_id != row["jarvis_session_id"] or event.context_id != row["context_id"]):
        raise ArtifactStoreError(_TABLE, str(seq), "key columns disagree with data")
    return event


class SQLiteActivityLedger:
    """`ActivityLedger` over the shared state DB (schema v6)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise ArtifactStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    async def append(self, drafts: Sequence[ActivityDraft]) -> tuple[ActivityEvent, ...]:
        drafts = tuple(drafts)
        if not drafts:
            return ()
        written: list[tuple[ActivityEvent, ...]] = []

        def write(conn: sqlite3.Connection) -> None:
            written.append(append_activity(conn, drafts))

        await self._run(lambda c: immediate_transaction(c, write))
        return written[0]

    async def list(self, query: ActivityQuery) -> Sequence[ActivityEvent]:
        if not isinstance(query, ActivityQuery):
            raise ActivityError("expected an ActivityQuery")
        clauses, params = ["seq > ?"], [query.after_seq]
        if query.jarvis_session_id is not None:
            clauses.append("jarvis_session_id = ?")
            params.append(query.jarvis_session_id)
        if query.context_id is not None:
            clauses.append("context_id = ?")
            params.append(query.context_id)
        if query.kinds:
            clauses.append(f"kind IN ({','.join('?' * len(query.kinds))})")
            params.extend(kind.value for kind in query.kinds)
        if query.since is not None:
            clauses.append("occurred_at >= ?")
            params.append(utc_key(query.since))
        if query.until is not None:
            clauses.append("occurred_at < ?")
            params.append(utc_key(query.until))
        sql = f"SELECT * FROM session_activity WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT ?"
        rows = await self._run(lambda c: c.execute(sql, (*params, query.limit)).fetchall())
        return tuple(_event_row(row) for row in rows)

    async def latest_seq(self) -> int:
        row = await self._run(lambda c: c.execute("SELECT MAX(seq) FROM session_activity").fetchone())
        return int(row[0] or 0)
