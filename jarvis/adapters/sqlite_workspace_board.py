"""SQLite adapter of the Board store (handoff board-session, Slice 02).

Port: `jarvis.ports.workspace_board.BoardRepository`. Contract: `docs/boards.md`
(Persistence). Tables `work_boards`, `jarvis_sessions`,
`board_conversation_bindings` come from migration v3 of `sqlite_state`.

Like `sqlite_conversation_events`, it shares the operational state DB file,
connection, lock and worker thread of `SQLiteStateRepository` through
`run_serialized`: no second database, no second connection model. Lifecycle
(initialize, migration, backup, close) belongs to that repository.

Guarantees:

- `data` is the value's `to_payload()`; every read decodes it with the strict
  domain `from_payload` and cross-checks the key columns. A row failing either
  is surfaced as `BoardStoreError`, never skipped or repaired (the DB is
  canonical state);
- a closed Session row is never rewritten: the upsert updates only
  `WHERE status='open'` and raises `BoardError(session_closed)` otherwise;
- a closed binding never goes back to `open` nor to `foreground` (same
  `session_closed`); its lifecycle may still move between
  `background_running` and `suspended`;
- any other `sqlite3.Error` (locked, I/O) is raised as `BoardStoreUnavailable`
  (a `BoardStoreError`, code `board_store_failed`);
- `commit_switch` writes every changed Board, Session and binding in one
  `BEGIN IMMEDIATE` transaction: all or nothing;
- uniqueness the domain also checks (one open Session, one foreground binding
  per Session) is enforced by the file too; a violation becomes a `BoardError`
  with the domain's code, never a raw `IntegrityError`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import sqlite3
from typing import Any, TypeVar

from jarvis.adapters.sqlite_state import SQLiteStateRepository, immediate_transaction
from jarvis.domain.workspace_board import (
    Board, BoardConversationBinding, BoardError, BoardErrorCode, BoardStatus, BrainLifecycle, JarvisSession,
    SessionStatus,
)
from jarvis.ports.workspace_board import BoardStoreError, BoardStoreUnavailable

T = TypeVar("T")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode(table: str, key: str, raw: str, parse: Callable[[object], T]) -> T:
    try:
        return parse(json.loads(raw))
    except (ValueError, TypeError) as exc:  # JSONDecodeError and BoardError are ValueErrors
        raise BoardStoreError(table, key, f"{type(exc).__name__}: {exc}") from exc


def _board_row(row: sqlite3.Row) -> Board:
    board = _decode("work_boards", row["board_id"], row["data"], Board.from_payload)
    if board.board_id != row["board_id"] or board.status.value != row["status"]:
        raise BoardStoreError("work_boards", row["board_id"], "key columns disagree with data")
    return board


def _session_row(row: sqlite3.Row) -> JarvisSession:
    key = row["jarvis_session_id"]
    session = _decode("jarvis_sessions", key, row["data"], JarvisSession.from_payload)
    if (session.jarvis_session_id != key or session.status.value != row["status"]
            or session.active_board_id != row["active_board_id"]):
        raise BoardStoreError("jarvis_sessions", key, "key columns disagree with data")
    return session


def _binding_row(row: sqlite3.Row) -> BoardConversationBinding:
    key = f"{row['jarvis_session_id']}/{row['board_id']}"
    binding = _decode("board_conversation_bindings", key, row["data"], BoardConversationBinding.from_payload)
    if (binding.key != (row["jarvis_session_id"], row["board_id"]) or binding.conversation_id != row["conversation_id"]
            or binding.lifecycle.value != row["lifecycle"] or binding.status.value != row["status"]):
        raise BoardStoreError("board_conversation_bindings", key, "key columns disagree with data")
    return binding


# ----------------------------------------------------------------- statements (sync, on the shared connection)

def _put_board(conn: sqlite3.Connection, board: Board) -> None:
    conn.execute(
        "INSERT INTO work_boards(board_id,status,created_at,updated_at,data) VALUES(?,?,?,?,?) "
        "ON CONFLICT(board_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,data=excluded.data",
        (board.board_id, board.status.value, board.created_at.isoformat(), board.updated_at.isoformat(),
         _json(board.to_payload())),
    )


def _put_session(conn: sqlite3.Connection, session: JarvisSession) -> None:
    try:
        cursor = conn.execute(
            "INSERT INTO jarvis_sessions(jarvis_session_id,status,started_at,active_board_id,data) VALUES(?,?,?,?,?) "
            "ON CONFLICT(jarvis_session_id) DO UPDATE SET status=excluded.status,"
            "active_board_id=excluded.active_board_id,data=excluded.data WHERE jarvis_sessions.status='open'",
            (session.jarvis_session_id, session.status.value, session.started_at.isoformat(), session.active_board_id,
             _json(session.to_payload())),
        )
    except sqlite3.IntegrityError as exc:
        raise BoardError(
            BoardErrorCode.INVALID_SESSION,
            f"session {session.jarvis_session_id} cannot be stored open: another session is already open",
        ) from exc
    if cursor.rowcount == 0:
        # The SQL guard: the row exists and is closed. Closed history is immutable.
        raise BoardError(BoardErrorCode.SESSION_CLOSED, f"session {session.jarvis_session_id} is closed")


def _put_binding(conn: sqlite3.Connection, binding: BoardConversationBinding) -> None:
    try:
        # SQL guard: a closed binding never reopens nor becomes foreground again.
        # Other updates of a closed binding stay allowed: its CLI may still be
        # `background_running`, then `suspended` (`list_live_bindings`).
        cursor = conn.execute(
            "INSERT INTO board_conversation_bindings(jarvis_session_id,board_id,conversation_id,lifecycle,status,"
            "created_at,data) VALUES(?,?,?,?,?,?,?) ON CONFLICT(jarvis_session_id,board_id) DO UPDATE SET "
            "conversation_id=excluded.conversation_id,lifecycle=excluded.lifecycle,status=excluded.status,"
            "data=excluded.data WHERE NOT (board_conversation_bindings.status='closed' AND "
            "(excluded.status='open' OR excluded.lifecycle='foreground'))",
            (binding.jarvis_session_id, binding.board_id, binding.conversation_id, binding.lifecycle.value,
             binding.status.value, binding.created_at.isoformat(), _json(binding.to_payload())),
        )
    except sqlite3.IntegrityError as exc:
        # Second foreground in the Session, or a Session/Board that does not exist.
        raise BoardError(
            BoardErrorCode.BINDING_CONFLICT,
            f"binding {binding.key} refused by the store: {exc}",
        ) from exc
    if cursor.rowcount == 0:
        raise BoardError(
            BoardErrorCode.SESSION_CLOSED,
            f"binding {binding.key} is closed: it cannot reopen or become foreground",
        )


class SQLiteBoardRepository:
    """`BoardRepository` over the shared state DB (schema v3)."""

    def __init__(self, state: SQLiteStateRepository) -> None:
        self._state = state

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        try:
            return await self._state.run_serialized(fn)
        except sqlite3.Error as exc:
            # Rules already surfaced as `BoardError` inside `fn`; anything else
            # SQLite raises (locked, I/O, ...) becomes the one storage failure
            # type callers catch, with SQLite's own words kept.
            operation = getattr(fn, "__qualname__", "operation").split(".<locals>")[0].rsplit(".", 1)[-1]
            raise BoardStoreUnavailable(operation, f"{type(exc).__name__}: {exc}") from exc

    #: One `BEGIN IMMEDIATE` transaction per call (shared helper of `sqlite_state`).
    _transaction = staticmethod(immediate_transaction)

    # ------------------------------------------------------------ Boards

    async def get_board(self, board_id: str) -> Board | None:
        row = await self._run(lambda c: c.execute("SELECT * FROM work_boards WHERE board_id=?", (board_id,)).fetchone())
        return _board_row(row) if row else None

    async def list_boards(self, *, include_archived: bool = False) -> Sequence[Board]:
        sql = "SELECT * FROM work_boards"
        params: tuple[Any, ...] = ()
        if not include_archived:
            sql += " WHERE status=?"
            params = (BoardStatus.ACTIVE.value,)
        rows = await self._run(lambda c: c.execute(sql + " ORDER BY created_at, board_id", params).fetchall())
        return tuple(_board_row(row) for row in rows)

    async def count_boards(self) -> int:
        """Every Board, archived included: `ensure_default` keys on zero."""

        return int(await self._run(lambda c: c.execute("SELECT count(*) FROM work_boards").fetchone()[0]))

    async def save_board(self, board: Board) -> None:
        await self._run(lambda c: _put_board(c, board))

    async def insert_board_if_empty(self, board: Board) -> bool:
        """Insert `board` only if `work_boards` is empty, atomically. True if inserted.

        The idempotence key of the default-Board migration (06 section H): a
        re-run, or two concurrent starts on the same file, insert at most once.
        """

        def insert(conn: sqlite3.Connection) -> bool:
            inserted = False

            def write(c: sqlite3.Connection) -> None:
                nonlocal inserted
                if c.execute("SELECT 1 FROM work_boards LIMIT 1").fetchone() is None:
                    _put_board(c, board)
                    inserted = True

            self._transaction(conn, write)
            return inserted

        return await self._run(insert)

    # ------------------------------------------------------------ Sessions

    async def get_session(self, jarvis_session_id: str) -> JarvisSession | None:
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM jarvis_sessions WHERE jarvis_session_id=?", (jarvis_session_id,)).fetchone())
        return _session_row(row) if row else None

    async def current_session(self) -> JarvisSession | None:
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM jarvis_sessions WHERE status=?", (SessionStatus.OPEN.value,)).fetchone())
        return _session_row(row) if row else None

    async def save_session(self, session: JarvisSession) -> None:
        await self._run(lambda c: _put_session(c, session))

    async def list_sessions(self, *, limit: int) -> Sequence[JarvisSession]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM jarvis_sessions ORDER BY started_at DESC, jarvis_session_id DESC LIMIT ?",
            (limit,)).fetchall())
        return tuple(_session_row(row) for row in rows)

    # ------------------------------------------------------------ bindings

    async def list_bindings(self, jarvis_session_id: str) -> Sequence[BoardConversationBinding]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM board_conversation_bindings WHERE jarvis_session_id=? ORDER BY created_at, board_id",
            (jarvis_session_id,)).fetchall())
        return tuple(_binding_row(row) for row in rows)

    async def save_binding(self, binding: BoardConversationBinding) -> None:
        await self._run(lambda c: _put_binding(c, binding))

    async def binding_by_conversation(self, conversation_id: str) -> BoardConversationBinding | None:
        # One binding per Core conversation by construction (each binding gets
        # a fresh conversation); if a damaged file held two, the newest wins
        # deterministically rather than an arbitrary row.
        row = await self._run(lambda c: c.execute(
            "SELECT * FROM board_conversation_bindings WHERE conversation_id=? "
            "ORDER BY created_at DESC, jarvis_session_id DESC LIMIT 1", (conversation_id,)).fetchone())
        return _binding_row(row) if row else None

    async def list_live_bindings(self) -> Sequence[BoardConversationBinding]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM board_conversation_bindings WHERE lifecycle IN (?, ?) ORDER BY created_at, board_id",
            (BrainLifecycle.FOREGROUND.value, BrainLifecycle.BACKGROUND_RUNNING.value)).fetchall())
        return tuple(_binding_row(row) for row in rows)

    # ------------------------------------------------------------ switch

    async def commit_switch(
        self,
        *,
        sessions: Sequence[JarvisSession],
        boards: Sequence[Board],
        bindings: Sequence[BoardConversationBinding],
    ) -> None:
        """One transaction for everything a switch or a new Session changes.

        Write order satisfies the per-statement unique indexes and foreign
        keys: Boards, then closing Sessions before the opening one, then
        demoted bindings before the promoted foreground one.
        """

        ordered_sessions = sorted(sessions, key=lambda s: s.status is SessionStatus.OPEN)
        ordered_bindings = sorted(bindings, key=lambda b: b.lifecycle is BrainLifecycle.FOREGROUND)

        def write(conn: sqlite3.Connection) -> None:
            for board in boards:
                _put_board(conn, board)
            for session in ordered_sessions:
                _put_session(conn, session)
            for binding in ordered_bindings:
                _put_binding(conn, binding)

        await self._run(lambda c: self._transaction(c, write))
