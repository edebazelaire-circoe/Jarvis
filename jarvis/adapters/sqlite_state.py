from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, TypeVar

from jarvis.domain.v2 import (
    Conversation, ConversationStatus, ConversationTurn, Device, Job, JobStatus,
    MissedRunPolicy, Notification, NotificationPriority, NotificationState,
    ScheduledItem, ScheduledStatus, TurnKind, jsonable,
)

T = TypeVar("T")
_SCHEMA_VERSION = 1


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _dump(value: Any) -> str:
    return json.dumps(jsonable(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class SQLiteStateRepository:
    """Single-file operational state adapter with serialized async access.

    The DB is canonical operational state: corruption is surfaced, never repaired
    by deletion. WAL provides safe restart behavior while the asyncio lock keeps
    one-process transactions deterministic.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (_SCHEMA_VERSION,))
            elif int(row[0]) > _SCHEMA_VERSION:
                raise RuntimeError(f"state DB schema {row[0]} is newer than supported {_SCHEMA_VERSION}")
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_turns_conversation_time ON turns(conversation_id, created_at, id);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
            CREATE TABLE IF NOT EXISTS scheduled_items (id TEXT PRIMARY KEY, status TEXT NOT NULL, next_fire_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_schedule_due ON scheduled_items(status, next_fire_at);
            CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_notifications_state ON notifications(state, created_at);
            ''')
            quick = conn.execute("PRAGMA quick_check").fetchone()
            if not quick or quick[0] != "ok":
                raise RuntimeError(f"state DB quick_check failed: {quick[0] if quick else 'unknown'}")
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"operational state database unavailable: {exc}") from exc
        self._conn = conn

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("state repository is not initialized")
        return self._conn

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            return await asyncio.to_thread(fn, self._connection())

    async def save_device(self, value: Device) -> None:
        await self._upsert("devices", value.device_id, value)

    async def save_conversation(self, value: Conversation) -> None:
        await self._run(lambda c: c.execute("INSERT INTO conversations(id,updated_at,data) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,data=excluded.data", (value.id, value.updated_at.isoformat(), _dump(value))))

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM conversations WHERE id=?", (conversation_id,)).fetchone())
        return self._conversation(json.loads(row[0])) if row else None

    async def save_turn(self, value: ConversationTurn) -> None:
        await self._run(lambda c: c.execute("INSERT OR IGNORE INTO turns(id,conversation_id,created_at,data) VALUES(?,?,?,?)", (value.id,value.conversation_id,value.created_at.isoformat(),_dump(value))))

    async def list_turns(self, conversation_id: str, *, limit: int = 20):
        rows = await self._run(lambda c: c.execute("SELECT data FROM (SELECT data,created_at,id FROM turns WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?) ORDER BY created_at,id", (conversation_id, max(1, limit))).fetchall())
        return tuple(self._turn(json.loads(r[0])) for r in rows)

    async def save_job(self, value: Job) -> None:
        await self._run(lambda c: c.execute("INSERT INTO jobs(id,status,created_at,data) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data", (value.id,value.status.value,value.created_at.isoformat(),_dump(value))))

    async def list_jobs(self, *, status: str | None = None):
        if status:
            rows = await self._run(lambda c: c.execute("SELECT data FROM jobs WHERE status=? ORDER BY created_at,id", (status,)).fetchall())
        else:
            rows = await self._run(lambda c: c.execute("SELECT data FROM jobs ORDER BY created_at,id").fetchall())
        return tuple(self._job(json.loads(r[0])) for r in rows)

    async def save_scheduled_item(self, value: ScheduledItem) -> None:
        await self._run(lambda c: c.execute("INSERT INTO scheduled_items(id,status,next_fire_at,data) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,next_fire_at=excluded.next_fire_at,data=excluded.data", (value.id,value.status.value,value.next_fire_at.isoformat(),_dump(value))))

    async def list_scheduled_items(self, *, active_only: bool = False):
        if active_only:
            rows = await self._run(lambda c: c.execute("SELECT data FROM scheduled_items WHERE status=? ORDER BY next_fire_at,id", (ScheduledStatus.ACTIVE.value,)).fetchall())
        else:
            rows = await self._run(lambda c: c.execute("SELECT data FROM scheduled_items ORDER BY next_fire_at,id").fetchall())
        return tuple(self._scheduled(json.loads(r[0])) for r in rows)

    async def save_notification(self, value: Notification) -> None:
        await self._run(lambda c: c.execute("INSERT INTO notifications(id,state,created_at,data) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data", (value.id,value.state.value,value.created_at.isoformat(),_dump(value))))

    async def list_notifications(self, *, state: str | None = None):
        if state:
            rows = await self._run(lambda c: c.execute("SELECT data FROM notifications WHERE state=? ORDER BY created_at,id", (state,)).fetchall())
        else:
            rows = await self._run(lambda c: c.execute("SELECT data FROM notifications ORDER BY created_at,id").fetchall())
        return tuple(self._notification(json.loads(r[0])) for r in rows)

    async def _upsert(self, table: str, key: str, value: Any) -> None:
        if table not in {"devices"}:
            raise ValueError("invalid table")
        await self._run(lambda c: c.execute(f"INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (key, _dump(value))))

    async def close(self) -> None:
        async with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                await asyncio.to_thread(conn.close)

    @staticmethod
    def _conversation(d):
        return Conversation(id=d["id"],status=ConversationStatus(d["status"]),originating_device_id=d["originating_device_id"],current_device_id=d["current_device_id"],created_at=_dt(d["created_at"]),updated_at=_dt(d["updated_at"]),summary=d.get("summary", ""),transport_session_id=d.get("transport_session_id"))
    @staticmethod
    def _turn(d):
        return ConversationTurn(id=d["id"],conversation_id=d["conversation_id"],kind=TurnKind(d["kind"]),content=d["content"],created_at=_dt(d["created_at"]),correlation_id=d["correlation_id"],reference_id=d.get("reference_id"),metadata=d.get("metadata", {}))
    @staticmethod
    def _job(d):
        return Job(id=d["id"],kind=d["kind"],status=JobStatus(d["status"]),requested_by_conversation_id=d.get("requested_by_conversation_id"),payload=d.get("payload",{}),result=d.get("result"),error=d.get("error"),created_at=_dt(d["created_at"]),started_at=_dt(d.get("started_at")),completed_at=_dt(d.get("completed_at")),idempotency_key=d["idempotency_key"])
    @staticmethod
    def _scheduled(d):
        return ScheduledItem(id=d["id"],kind=d["kind"],status=ScheduledStatus(d["status"]),payload=d.get("payload",{}),next_fire_at=_dt(d["next_fire_at"]),recurrence_seconds=d.get("recurrence_seconds"),missed_run_policy=MissedRunPolicy(d["missed_run_policy"]),max_lateness_seconds=d.get("max_lateness_seconds"),last_fire_at=_dt(d.get("last_fire_at")),created_at=_dt(d["created_at"]),requested_by_conversation_id=d.get("requested_by_conversation_id"),idempotency_key=d["idempotency_key"])
    @staticmethod
    def _notification(d):
        return Notification(id=d["id"],summary=d["summary"],body=d.get("body", ""),state=NotificationState(d["state"]),priority=NotificationPriority(d["priority"]),target_device_id=d["target_device_id"],originating_reference_id=d.get("originating_reference_id"),delivery_policy=d.get("delivery_policy","system_notification"),created_at=_dt(d["created_at"]),delivered_at=_dt(d.get("delivered_at")),expires_at=_dt(d.get("expires_at")),idempotency_key=d["idempotency_key"])
