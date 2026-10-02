"""SQLite adapter of the Board-artifact links (handoff board-memory-workspace-inspector, Slice 02, R2).

Port: `jarvis.ports.board_artifact_links.BoardArtifactLinkStore`. Table
`board_artifact_links` comes from migration v8 of `sqlite_state`; like the
other sibling adapters it shares the state DB connection, lock and worker
thread through `run_serialized`, and every write is one
`immediate_transaction` that also appends its activity events.

`link_to_active_board` is the automatic link: `sqlite_artifacts` calls it
inside the artifact insert transaction, so an artifact and its `active_board`
link are written together or not at all. Contract: `docs/artifacts.md` ›
*Board links*.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
import sqlite3
from typing import TypeVar

from jarvis.adapters.sqlite_session_activity import append_activity, utc_key
from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.artifacts import Artifact, ArtifactError, ArtifactErrorCode, check_artifact_id
from jarvis.domain.board_artifact_links import (
    BoardArtifactLink, BoardArtifactLinkOrigin, check_link_board_id, check_link_limit,
)
from jarvis.domain.session_activity import ActivityDraft, ActivityEvent
from jarvis.domain.workspace_board import BoardError, BoardErrorCode
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable

T = TypeVar("T")
_TABLE = "board_artifact_links"


def _link_row(row: sqlite3.Row) -> BoardArtifactLink:
    try:
        return BoardArtifactLink(board_id=row["board_id"], artifact_id=row["artifact_id"],
                                 origin=BoardArtifactLinkOrigin(row["origin"]),
                                 linked_at=datetime.fromisoformat(row["linked_at"]))
    except (ValueError, TypeError) as exc:
        raise BoardStoreError(_TABLE, f"{row['board_id']}/{row['artifact_id']}", f"{type(exc).__name__}: {exc}") from exc


def _insert(conn: sqlite3.Connection, link: BoardArtifactLink) -> bool:
    cursor = conn.execute(
        "INSERT INTO board_artifact_links(board_id,artifact_id,origin,linked_at) VALUES(?,?,?,?) "
        "ON CONFLICT DO NOTHING",
        (link.board_id, link.artifact_id, link.origin.value, utc_key(link.linked_at)))
    return cursor.rowcount == 1


def link_to_active_board(conn: sqlite3.Connection, artifact: Artifact) -> BoardArtifactLink | None:
    """Automatic link of a **new** artifact, inside the caller's transaction.

    Target: `active_board_id` of the open Session, read in this transaction
    (the Board active at capture time). No link when no Session is open, or
    when the artifact names another (closed) Session: its Board at capture
    time is then unknown, and a wrong link is worse than none.
    """

    row = conn.execute("SELECT jarvis_session_id, active_board_id FROM jarvis_sessions WHERE status='open'").fetchone()
    if row is None:
        return None
    if artifact.jarvis_session_id is not None and artifact.jarvis_session_id != row["jarvis_session_id"]:
        return None
    link = BoardArtifactLink(board_id=row["active_board_id"], artifact_id=artifact.artifact_id,
                             origin=BoardArtifactLinkOrigin.ACTIVE_BOARD, linked_at=artifact.created_at)
    _insert(conn, link)
    return link


class SQLiteBoardArtifactLinks:
    """`BoardArtifactLinkStore` over the shared state DB (schema v8)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise BoardStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    async def _transaction(self, write: Callable[[sqlite3.Connection], T]) -> T:
        result: list[T] = []
        await self._run(lambda c: immediate_transaction(c, lambda conn: result.append(write(conn))))
        return result[0]

    # ------------------------------------------------------------ écriture

    async def link(self, board_id: str, artifact_id: str, *, now: datetime,
                   origin: BoardArtifactLinkOrigin = BoardArtifactLinkOrigin.EXPLICIT,
                   activity: Sequence[ActivityDraft] = ()) -> tuple[BoardArtifactLink, bool, tuple[ActivityEvent, ...]]:
        candidate = BoardArtifactLink(board_id=board_id, artifact_id=artifact_id,
                                      origin=BoardArtifactLinkOrigin(origin), linked_at=now)

        def write(conn: sqlite3.Connection) -> tuple[BoardArtifactLink, bool, tuple[ActivityEvent, ...]]:
            if conn.execute("SELECT 1 FROM work_boards WHERE board_id=?", (board_id,)).fetchone() is None:
                raise BoardError(BoardErrorCode.BOARD_NOT_FOUND, f"board {board_id} does not exist")
            if conn.execute("SELECT 1 FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone() is None:
                raise ArtifactError(ArtifactErrorCode.ARTIFACT_NOT_FOUND, f"artifact {artifact_id} does not exist")
            if not _insert(conn, candidate):
                existing = conn.execute("SELECT * FROM board_artifact_links WHERE board_id=? AND artifact_id=?",
                                        (board_id, artifact_id)).fetchone()
                return _link_row(existing), False, ()
            return candidate, True, append_activity(conn, tuple(activity))

        return await self._transaction(write)

    async def unlink(self, board_id: str, artifact_id: str, *,
                     activity: Sequence[ActivityDraft] = ()) -> tuple[bool, tuple[ActivityEvent, ...]]:
        check_link_board_id(board_id)
        check_artifact_id(artifact_id)

        def write(conn: sqlite3.Connection) -> tuple[bool, tuple[ActivityEvent, ...]]:
            cursor = conn.execute("DELETE FROM board_artifact_links WHERE board_id=? AND artifact_id=?",
                                  (board_id, artifact_id))
            if cursor.rowcount == 0:
                return False, ()
            return True, append_activity(conn, tuple(activity))

        return await self._transaction(write)

    # ------------------------------------------------------------ lecture

    async def links_of_board(self, board_id: str, *, limit: int,
                             before: BoardArtifactLink | None = None) -> Sequence[BoardArtifactLink]:
        check_link_board_id(board_id)
        check_link_limit(limit)
        if before is None:
            sql, params = "", ()
        else:
            key = utc_key(before.linked_at)
            sql, params = " AND (linked_at < ? OR (linked_at = ? AND artifact_id < ?))", (key, key, before.artifact_id)
        rows = await self._run(lambda c: c.execute(
            f"SELECT * FROM board_artifact_links WHERE board_id=?{sql} ORDER BY linked_at DESC, artifact_id DESC "
            "LIMIT ?", (board_id, *params, limit)).fetchall())
        return tuple(_link_row(row) for row in rows)

    async def count_links(self, board_id: str) -> int:
        check_link_board_id(board_id)
        row = await self._run(lambda c: c.execute(
            "SELECT COUNT(*) FROM board_artifact_links WHERE board_id=?", (board_id,)).fetchone())
        return int(row[0])

    async def boards_of_artifact(self, artifact_id: str, *, limit: int) -> Sequence[BoardArtifactLink]:
        check_artifact_id(artifact_id)
        check_link_limit(limit)
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM board_artifact_links WHERE artifact_id=? ORDER BY linked_at, board_id LIMIT ?",
            (artifact_id, limit)).fetchall())
        return tuple(_link_row(row) for row in rows)
