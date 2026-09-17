from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, TypeVar

from jarvis.domain.v2 import (
    Conversation, ConversationStatus, ConversationTurn, Device, Job, JobStatus,
    MissedRunPolicy, Notification, NotificationPriority, NotificationState,
    ScheduledItem, ScheduledStatus, SpeechRequest, TurnKind, jsonable,
)
from jarvis.domain.voice_state import VoiceConversationSnapshot
from jarvis.domain.speech_presentation import BackendOutcome, OutcomeKind, SpeechDependency, SpeechSource
from jarvis.domain.voice_admission import (
    admitted_turn_binding, admitted_turn_order, canonical_admitted_turn_id, canonical_input_is_newer, canonical_input_matches,
)
from jarvis.domain.back_brain import BackBrainAdvisoryReference, BackBrainUnavailable, BackBrainWorkPayload, back_brain_job_id
from jarvis.domain.live_lifecycle import LiveLifecycleConflict, LiveLifecycleState, LiveSessionRecord

T = TypeVar("T")
#: v1: operational state. v2 (2026-09-16): `conversation_events` log.
_SCHEMA_VERSION = 2

#: Envelope ids with a partial index `(<id>, sequence)`; mirrors
#: `conversation_event_store.LOOKUP_FIELDS` (checked by the store tests).
_CONVERSATION_EVENT_LOOKUP_COLUMNS = ("session_id", "turn_id", "correlation_id", "task_id", "work_id",
                                      "speech_id", "outcome_id", "span_id")

#: Forward-only migrations, one transaction each, keyed by the version they
#: produce. Additive only: an older binary refuses the newer file ("newer than
#: supported") instead of misreading it. Contract: `docs/conversation-events.md`.
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        # AUTOINCREMENT: a sequence is never reused, even after the highest row
        # is pruned by retention, so a consumer cursor can never skip an event.
        # `data` is the encoded canonical event (source of truth); the other
        # columns are extracted copies for indexing and are cross-checked on read.
        # No foreign key to `conversations`: the log records facts even when the
        # operational conversation row is absent or later removed.
        """CREATE TABLE IF NOT EXISTS conversation_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            conversation_id TEXT NOT NULL,
            session_id TEXT,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            visibility TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            span_id TEXT, turn_id TEXT, correlation_id TEXT, task_id TEXT, work_id TEXT, speech_id TEXT,
            outcome_id TEXT,
            data TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_conversation ON conversation_events(conversation_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_occurred ON conversation_events(occurred_at, sequence)",
        *(f"CREATE INDEX IF NOT EXISTS idx_conversation_events_{column} ON conversation_events({column}, sequence) "
          f"WHERE {column} IS NOT NULL" for column in _CONVERSATION_EVENT_LOOKUP_COLUMNS),
    ),
}


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


async def run_sqlite_in_thread(fn: Callable[..., T], *args: Any) -> T:
    """Keep the caller's connection lock until native work has really ended.

    Shared by every SQLite adapter (`sqlite_state`, `sqlite_scene`).
    """
    worker = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancelling to_thread's waiter cannot interrupt SQLite. Releasing
        # the lock now could let another transaction or close use this
        # connection concurrently. Preserve even repeated cancellation.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()  # Observe worker failure; cancellation wins.
        raise


def _dump(value: Any) -> str:
    return json.dumps(jsonable(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def rollback_after_failure(conn: sqlite3.Connection, failure: BaseException) -> None:
    """Roll back an open transaction after `failure` without ever masking it.

    If ROLLBACK itself fails, the caller must still see the original failure; the
    rollback error is attached to it as a note (visible in the traceback) instead
    of replacing it. SQLite discards the unfinished transaction at next open.
    """
    if not conn.in_transaction:
        return
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error as rollback_error:
        failure.add_note(f"ROLLBACK also failed: {type(rollback_error).__name__}: {rollback_error}")


def pre_migration_backup_path(path: Path, version: int) -> Path:
    """`<db>.v<version>.bak`, next to the DB (see docs/state-model.md, rollback procedure)."""
    return path.with_name(f"{path.name}.v{version}.bak")


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
            await self._thread(self._initialize_sync)

    @staticmethod
    async def _thread(fn: Callable[..., T], *args: Any) -> T:
        return await run_sqlite_in_thread(fn, *args)

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            # Explicit, not a build default: in WAL mode FULL syncs the WAL at
            # every commit, so an acknowledged write survives OS crash/power loss.
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                # A fresh file starts at v1 and takes the same migrations as an
                # upgraded one: there is a single path to every schema version.
                conn.execute("INSERT INTO schema_version(version) VALUES (1)")
                version = 1
            elif int(row[0]) > _SCHEMA_VERSION:
                raise RuntimeError(f"state DB schema {row[0]} is newer than supported {_SCHEMA_VERSION}")
            else:
                version = int(row[0])
                if version < _SCHEMA_VERSION:
                    # Existing data about to be migrated: copy it first, before
                    # any schema statement runs on this file.
                    self._backup_before_migration(conn, version)
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_turns_conversation_time ON turns(conversation_id, created_at, id);
            CREATE TABLE IF NOT EXISTS voice_history_projections (
                conversation_id TEXT NOT NULL, output_key TEXT NOT NULL,
                confirmed_end INTEGER NOT NULL DEFAULT 0, pending_turn TEXT,
                PRIMARY KEY(conversation_id, output_key),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS voice_conversation_snapshots (
                conversation_id TEXT PRIMARY KEY, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS brain_sources (
                conversation_id TEXT NOT NULL, correlation_id TEXT NOT NULL, epoch INTEGER NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(conversation_id,correlation_id), UNIQUE(conversation_id,epoch),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS brain_current_sources (
                conversation_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS brain_invalidated_dependencies (
                conversation_id TEXT NOT NULL, work_id TEXT NOT NULL, source_correlation_id TEXT NOT NULL,
                PRIMARY KEY(conversation_id,work_id,source_correlation_id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS brain_outcomes (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_brain_outcomes_conversation ON brain_outcomes(conversation_id,created_at,id);
            CREATE TABLE IF NOT EXISTS brain_outcome_selections (
                conversation_id TEXT NOT NULL, selection_id TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(conversation_id,selection_id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS back_brain_advisories (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
            CREATE TABLE IF NOT EXISTS scheduled_items (id TEXT PRIMARY KEY, status TEXT NOT NULL, next_fire_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_schedule_due ON scheduled_items(status, next_fire_at);
            CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_notifications_state ON notifications(state, created_at);
            CREATE TABLE IF NOT EXISTS live_sessions (
                session_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                revision INTEGER NOT NULL, data TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_unresolved_live_session
                ON live_sessions((1)) WHERE state <> 'stopped';
            ''')
            self._migrate(conn, version)
            quick = conn.execute("PRAGMA quick_check").fetchone()
            if not quick or quick[0] != "ok":
                raise RuntimeError(f"state DB quick_check failed: {quick[0] if quick else 'unknown'}")
        except BaseException as exc:
            if conn is not None:
                # The repository never exposes a connection it could not
                # validate; closing it here keeps the file handle from leaking.
                conn.close()
            if isinstance(exc, sqlite3.DatabaseError):
                raise RuntimeError(f"operational state database unavailable: {exc}") from exc
            raise
        self._conn = conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection, version: int) -> None:
        """Apply each pending migration atomically (DDL + version bump in one transaction).

        A crash mid-migration rolls the step back and the next start retries it.
        The version is re-read under the write lock, so a concurrent initializer
        (another process on the same file) cannot apply a step twice.
        """
        for target in range(version + 1, _SCHEMA_VERSION + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = int(conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()[0])
                if current < target:
                    for statement in _MIGRATIONS[target]:
                        conn.execute(statement)
                    conn.execute("UPDATE schema_version SET version=?", (target,))
                conn.execute("COMMIT")
            except BaseException as exc:
                rollback_after_failure(conn, exc)
                raise

    def _backup_before_migration(self, conn: sqlite3.Connection, version: int) -> None:
        """One-time online copy of an existing DB to `<db>.v<version>.bak` before migrating it.

        An existing backup is never overwritten (the first pre-migration copy is
        the one worth keeping). The copy is written to a temporary name and renamed
        only when complete, so a crash never leaves a truncated `.bak` that looks
        valid. Any failure aborts initialization before the DB is changed.
        """
        target = pre_migration_backup_path(self.path, version)
        if target.exists():
            return
        partial = target.with_name(target.name + ".partial")
        try:
            partial.unlink(missing_ok=True)
            copy = sqlite3.connect(partial)
            try:
                conn.backup(copy)
            finally:
                copy.close()
            partial.replace(target)
        except (OSError, sqlite3.Error) as exc:
            try:
                partial.unlink(missing_ok=True)
            except OSError as cleanup_error:
                exc.add_note(f"partial backup not removed: {type(cleanup_error).__name__}: {cleanup_error}")
            raise RuntimeError(
                f"state DB schema {version} -> {_SCHEMA_VERSION}: pre-migration backup to {target.name} failed, "
                f"migration aborted and database unchanged: {type(exc).__name__}: {exc}") from exc

    async def run_serialized(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Adapter seam for sibling SQLite adapters sharing this file and connection.

        Runs `fn(connection)` in the worker thread under the repository lock, with
        the same cancellation guarantee as every repository method. Not part of the
        `StateRepository` port; `sqlite_conversation_events` is its only user.

        The connection is shared, so a callback may not leave a transaction open:
        on failure it is rolled back (original error kept); on success it is rolled
        back and `RuntimeError` is raised, since its outcome was never committed.
        """
        def guarded(conn: sqlite3.Connection) -> T:
            try:
                result = fn(conn)
            except BaseException as exc:
                rollback_after_failure(conn, exc)
                raise
            if conn.in_transaction:
                conn.execute("ROLLBACK")
                raise RuntimeError("run_serialized callback left a transaction open; it was rolled back")
            return result

        return await self._run(guarded)

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("state repository is not initialized")
        return self._conn

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            return await self._thread(fn, self._connection())

    async def save_device(self, value: Device) -> None:
        await self._upsert("devices", value.device_id, value)

    async def save_conversation(self, value: Conversation) -> None:
        await self._run(lambda c: c.execute("INSERT INTO conversations(id,updated_at,data) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,data=excluded.data", (value.id, value.updated_at.isoformat(), _dump(value))))

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM conversations WHERE id=?", (conversation_id,)).fetchone())
        return self._conversation(json.loads(row[0])) if row else None

    async def save_turn(self, value: ConversationTurn) -> None:
        await self._run(lambda c: c.execute("INSERT OR IGNORE INTO turns(id,conversation_id,created_at,data) VALUES(?,?,?,?)", (value.id,value.conversation_id,value.created_at.isoformat(),_dump(value))))

    async def claim_admitted_backend_dispatch(self, turn_id: str) -> bool:
        """Atomically reserve one direct-admitted USER for backend dispatch.

        Only the reservation flag changes. The immutable text/source/identities
        and archive remain untouched; a reservation is not execution evidence.
        """
        def claim(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                if self._validated_admitted_turn(conn, turn_id) is None:
                    conn.execute("COMMIT")
                    return False
                cursor = conn.execute("""
                    UPDATE turns
                    SET data=json_set(data,'$.metadata.backend_dispatch_reserved',json('true'))
                    WHERE id=? AND json_extract(data,'$.kind')='user'
                    AND json_type(data,'$.metadata.voice_admission')='object'
                    AND json_type(data,'$.metadata.backend_dispatch_reserved') IS NULL
                    """, (turn_id,))
                claimed = cursor.rowcount == 1
                conn.execute("COMMIT")
                return claimed
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(claim)

    def _validated_admitted_turn(self, conn, turn_id):
        row = conn.execute("SELECT data FROM turns WHERE id=?", (turn_id,)).fetchone()
        turn = self._turn(json.loads(row[0])) if row else None
        binding = admitted_turn_binding(turn) if turn else None
        order = admitted_turn_order(turn) if turn else None
        if binding is None or order is None:
            return None
        owned = conn.execute("SELECT data FROM brain_sources WHERE conversation_id=? AND correlation_id=?",
                             (turn.conversation_id, turn.correlation_id)).fetchone()
        checkpoint = conn.execute("SELECT data FROM voice_conversation_snapshots WHERE conversation_id=?", (turn.conversation_id,)).fetchone()
        source = SpeechSource.from_payload(json.loads(owned[0])) if owned else None
        snapshot = VoiceConversationSnapshot.from_dict(json.loads(checkpoint[0])) if checkpoint else None
        if (source is None or source.turn_id != turn.id or source.correlation_id != turn.correlation_id
                or snapshot is None or not canonical_input_matches(snapshot, binding)):
            return None
        checkpoint_order = next((item for item in snapshot.turns if item.turn_id == order.turn_id), None)
        if checkpoint_order is None or checkpoint_order != order:
            return None
        return turn, binding, source

    async def list_turns_since(self, since: datetime, *, kind: str, limit: int) -> tuple[ConversationTurn, ...]:
        """Turns of `kind` created at or after `since`, oldest first, at most the `limit` newest.

        Walks `idx_turns_conversation_time` per conversation whose `updated_at`
        is not older than `since` (`append_turn` keeps it >= its turns). Times
        are compared as stored ISO text (every Core writer stores UTC), then
        re-checked as datetimes.
        """
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("since must be timezone aware")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        bound = since.astimezone(timezone.utc).isoformat()
        rows = await self._run(lambda c: c.execute(
            "SELECT data FROM turns WHERE conversation_id IN (SELECT id FROM conversations WHERE updated_at>=?) "
            "AND created_at>=? AND json_extract(data,'$.kind')=? ORDER BY created_at DESC,id DESC LIMIT ?",
            (bound, bound, kind, limit)).fetchall())
        selected = [turn for turn in (self._turn(json.loads(r[0])) for r in rows) if turn.created_at >= since]
        return tuple(reversed(selected))

    async def list_turns(self, conversation_id: str, *, limit: int = 20):
        rows = await self._run(lambda c: c.execute("SELECT data FROM (SELECT data,created_at,id FROM turns WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?) ORDER BY created_at,id", (conversation_id, max(1, limit))).fetchall())
        return tuple(self._turn(json.loads(r[0])) for r in rows)

    def _voice_projection(self, conn: sqlite3.Connection, conversation_id: str, output_key: str) -> tuple[int, ConversationTurn | None]:
        row = conn.execute("SELECT confirmed_end,pending_turn FROM voice_history_projections WHERE conversation_id=? AND output_key=?", (conversation_id, output_key)).fetchone()
        if row is None:
            return 0, None
        return int(row[0]), self._turn(json.loads(row[1])) if row[1] else None

    async def get_voice_projection(self, conversation_id: str, output_key: str) -> tuple[int, ConversationTurn | None]:
        return await self._run(lambda conn: self._voice_projection(conn, conversation_id, output_key))

    async def stage_voice_projection(self, conversation_id: str, output_key: str, start: int, turn: ConversationTurn) -> tuple[int, ConversationTurn | None]:
        """Persist the exact range BEFORE turn/archive writes, in one SQLite transaction."""
        def stage(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("INSERT OR IGNORE INTO voice_history_projections(conversation_id,output_key) VALUES(?,?)", (conversation_id, output_key))
                offset, pending = self._voice_projection(conn, conversation_id, output_key)
                if pending is None:
                    if offset != start or turn.conversation_id != conversation_id:
                        raise ValueError("voice projection cursor conflict")
                    conn.execute("UPDATE voice_history_projections SET pending_turn=? WHERE conversation_id=? AND output_key=?", (_dump(turn), conversation_id, output_key))
                    pending = turn
                conn.execute("COMMIT")
                return offset, pending
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(stage)

    async def complete_voice_projection(self, conversation_id: str, output_key: str, turn_id: str) -> int:
        """Advance only the staged range that both durable stores have accepted."""
        def complete(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                offset, pending = self._voice_projection(conn, conversation_id, output_key)
                if pending is None or pending.id != turn_id:
                    raise ValueError("voice projection pending range conflict")
                end = pending.metadata["confirmed_end"]
                if type(end) is not int or not offset < end <= 8192:
                    raise ValueError("invalid voice projection range")
                conn.execute("UPDATE voice_history_projections SET confirmed_end=?,pending_turn=NULL WHERE conversation_id=? AND output_key=?", (end, conversation_id, output_key))
                conn.execute("COMMIT")
                return end
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(complete)

    async def save_voice_snapshot(self, snapshot: VoiceConversationSnapshot) -> None:
        await self._run(lambda conn: conn.execute(
            "INSERT INTO voice_conversation_snapshots(conversation_id,data) VALUES(?,?) ON CONFLICT(conversation_id) DO UPDATE SET data=excluded.data",
            (snapshot.conversation_id, _dump(snapshot.to_dict())),
        ))

    async def get_voice_snapshot(self, conversation_id: str) -> VoiceConversationSnapshot | None:
        row = await self._run(lambda conn: conn.execute("SELECT data FROM voice_conversation_snapshots WHERE conversation_id=?", (conversation_id,)).fetchone())
        return VoiceConversationSnapshot.from_dict(json.loads(row[0])) if row else None

    async def get_turn(self, turn_id: str) -> ConversationTurn | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM turns WHERE id=?", (turn_id,)).fetchone())
        return self._turn(json.loads(row[0])) if row else None

    async def allocate_brain_source(self, conversation_id: str, turn_id: str, correlation_id: str) -> SpeechSource:
        def allocate(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM brain_sources WHERE conversation_id=? AND correlation_id=?", (conversation_id, correlation_id)).fetchone()
                if row:
                    source = SpeechSource.from_payload(json.loads(row[0]))
                    if source.turn_id != turn_id:
                        raise ValueError("brain source identity conflict")
                else:
                    epoch = conn.execute("SELECT COALESCE(MAX(epoch),0)+1 FROM brain_sources WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
                    source = SpeechSource(turn_id=turn_id, correlation_id=correlation_id, intent_id=turn_id, intent_epoch=epoch)
                    conn.execute("INSERT INTO brain_sources VALUES(?,?,?,?)", (conversation_id, correlation_id, epoch, _dump(source)))
                conn.execute("COMMIT")
                return source
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(allocate)

    async def get_brain_source(self, conversation_id: str, correlation_id: str) -> SpeechSource | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM brain_sources WHERE conversation_id=? AND correlation_id=?", (conversation_id, correlation_id)).fetchone())
        return SpeechSource.from_payload(json.loads(row[0])) if row else None

    async def get_current_brain_source(self, conversation_id: str) -> SpeechSource | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM brain_current_sources WHERE conversation_id=?", (conversation_id,)).fetchone())
        return SpeechSource.from_payload(json.loads(row[0])) if row else None

    async def activate_brain_source(self, conversation_id: str, source: SpeechSource) -> bool:
        def activate(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                changed = activate_owned(conn)
                conn.execute("COMMIT")
                return changed
            except Exception:
                conn.execute("ROLLBACK")
                raise
        def activate_owned(conn):
            owned = conn.execute("SELECT data FROM brain_sources WHERE conversation_id=? AND correlation_id=?", (conversation_id, source.correlation_id)).fetchone()
            if owned is None or SpeechSource.from_payload(json.loads(owned[0])) != source:
                raise ValueError("cannot activate an unowned brain source")
            current_row = conn.execute("SELECT data FROM brain_current_sources WHERE conversation_id=?", (conversation_id,)).fetchone()
            current = SpeechSource.from_payload(json.loads(current_row[0])) if current_row else None
            if current == source:
                return False
            candidate_row = conn.execute("SELECT data FROM turns WHERE id=?", (source.turn_id,)).fetchone()
            candidate_turn = self._turn(json.loads(candidate_row[0])) if candidate_row else None
            candidate = admitted_turn_binding(candidate_turn) if candidate_turn else None
            candidate_order = admitted_turn_order(candidate_turn) if candidate_turn else None
            if candidate_turn and "voice_admission" in candidate_turn.metadata and (candidate is None or candidate_order is None):
                return False
            newer = current is None or source.intent_epoch > current.intent_epoch
            if candidate is not None:
                checkpoint = conn.execute("SELECT data FROM voice_conversation_snapshots WHERE conversation_id=?", (conversation_id,)).fetchone()
                snapshot = VoiceConversationSnapshot.from_dict(json.loads(checkpoint[0])) if checkpoint else None
                if snapshot is None or snapshot.current_session_id != candidate.session_id or not canonical_input_matches(snapshot, candidate):
                    return False
                checkpoint_order = next((item for item in snapshot.turns if item.turn_id == candidate_order.turn_id), None)
                if checkpoint_order is None or checkpoint_order != candidate_order:
                    return False
                if current is not None:
                    current_turn_row = conn.execute("SELECT data FROM turns WHERE id=?", (current.turn_id,)).fetchone()
                    current_turn = self._turn(json.loads(current_turn_row[0])) if current_turn_row else None
                    current_binding = admitted_turn_binding(current_turn) if current_turn else None
                    current_order = admitted_turn_order(current_turn) if current_turn else None
                    if current_turn and "voice_admission" in current_turn.metadata and (current_binding is None or current_order is None):
                        return False  # Corrupt direct evidence cannot masquerade as legacy ordering.
                    if current_binding is not None:
                        # Preserve the Task08 monotone generation watermark as
                        # well as canonical order. An allocation-order conflict
                        # cannot authorize either an old intent or epoch rollback.
                        durable_orders = self._admitted_order_ancestors(conn, snapshot, candidate_order, current_order)
                        if durable_orders is None:
                            return False
                        newer = newer and canonical_input_is_newer(snapshot, candidate, current_binding,
                            candidate_order=candidate_order, current_order=current_order, durable_orders=durable_orders)
            if not newer:
                return False
            cursor = conn.execute("INSERT INTO brain_current_sources VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET epoch=excluded.epoch,data=excluded.data", (conversation_id, source.intent_epoch, _dump(source)))
            return cursor.rowcount > 0
        return await self._run(activate)

    def _admitted_order_ancestors(self, conn, snapshot, candidate_order, current_order):
        """Follow existing USER proofs, never a parallel lineage store.

        Each persisted proof has fixed size. Traversal has no arbitrary depth
        cutoff: linear conversation must not freeze after a number of turns.
        It runs in the existing SQLite worker and stops at a join/root/missing
        record. Visited identities make malformed cycles finite.
        """
        if candidate_order is None or current_order is None:
            return None
        if candidate_order.session_id != current_order.session_id:
            return ()
        known = {item.turn_id: item for item in snapshot.turns if item.session_id == candidate_order.session_id}
        known.setdefault(candidate_order.turn_id, candidate_order)
        known.setdefault(current_order.turn_id, current_order)
        pending = [(current_order.turn_id, candidate_order.turn_id),
                   (candidate_order.turn_id, current_order.turn_id)]
        visited = set()
        durable = []
        while pending:
            key, other = pending.pop()
            if key == other:
                return tuple(durable)  # Direct ancestry proved; older ancestry is irrelevant.
            if key in visited:
                continue
            visited.add(key)
            order = known.get(key)
            if order is None:
                row = conn.execute("SELECT data FROM turns WHERE id=?", (
                    canonical_admitted_turn_id(snapshot.conversation_id, candidate_order.session_id, key),)).fetchone()
                if row is None:
                    continue
                turn = self._turn(json.loads(row[0]))
                order = admitted_turn_order(turn)
                if order is None or order.turn_id != key or order.session_id != candidate_order.session_id:
                    return None
                known[key] = order
                durable.append(order)
            if order.previous_turn_id is not None:
                pending.append((order.previous_turn_id, other))
        return tuple(durable)

    async def invalidate_brain_dependency(self, conversation_id: str, dependency: SpeechDependency) -> None:
        await self._run(lambda c: c.execute("INSERT OR IGNORE INTO brain_invalidated_dependencies VALUES(?,?,?)", (conversation_id, dependency.work_id, dependency.source_correlation_id)))

    async def list_invalidated_brain_dependencies(self, conversation_id: str, *, limit: int = 257) -> tuple[SpeechDependency, ...]:
        if type(limit) is not int or not 1 <= limit <= 257:
            raise ValueError("invalid dependency limit")
        rows = await self._run(lambda c: c.execute("SELECT work_id,source_correlation_id FROM brain_invalidated_dependencies WHERE conversation_id=? ORDER BY work_id,source_correlation_id LIMIT ?", (conversation_id, limit)).fetchall())
        return tuple(SpeechDependency(work_id=row[0], source_correlation_id=row[1]) for row in rows)

    async def save_brain_outcome(self, value: BackendOutcome) -> tuple[BackendOutcome, bool]:
        """One immutable content version; only its observation kind may mature."""
        def save(conn):
            row = conn.execute("SELECT data FROM brain_outcomes WHERE id=?", (value.id,)).fetchone()
            if row:
                existing = BackendOutcome.from_payload(json.loads(row[0]))
                for name in ("conversation_id", "source", "work_id", "text", "status"):
                    if getattr(existing, name) != getattr(value, name):
                        raise ValueError("brain outcome identity conflict")
                if existing.kind is OutcomeKind.SPEECH_RESULT and value.kind is not OutcomeKind.SPEECH_RESULT:
                    from dataclasses import replace
                    existing = replace(existing, kind=value.kind)
                    conn.execute("UPDATE brain_outcomes SET data=? WHERE id=?", (_dump(existing), value.id))
                    return existing, True
                return existing, False
            conn.execute("INSERT INTO brain_outcomes VALUES(?,?,?,?)", (value.id, value.conversation_id, value.created_at.isoformat(), _dump(value)))
            return value, True
        return await self._run(save)

    async def get_brain_outcome(self, conversation_id: str, outcome_id: str) -> BackendOutcome | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM brain_outcomes WHERE conversation_id=? AND id=?", (conversation_id, outcome_id)).fetchone())
        return BackendOutcome.from_payload(json.loads(row[0])) if row else None

    async def list_brain_outcomes(self, conversation_id: str, *, limit: int = 32) -> tuple[BackendOutcome, ...]:
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("invalid outcome limit")
        rows = await self._run(lambda c: c.execute("SELECT data FROM brain_outcomes WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?", (conversation_id, limit)).fetchall())
        return tuple(BackendOutcome.from_payload(json.loads(row[0])) for row in rows)

    async def get_brain_selection(self, conversation_id: str, selection_id: str) -> SpeechRequest | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM brain_outcome_selections WHERE conversation_id=? AND selection_id=?", (conversation_id, selection_id)).fetchone())
        return SpeechRequest.from_payload(json.loads(row[0])) if row else None

    async def save_brain_selection(self, conversation_id: str, selection_id: str, speech: SpeechRequest) -> None:
        await self._run(lambda c: c.execute("INSERT INTO brain_outcome_selections VALUES(?,?,?)", (conversation_id, selection_id, _dump(speech))))

    async def save_job(self, value: Job) -> None:
        await self._run(lambda c: c.execute("INSERT INTO jobs(id,status,created_at,data) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,data=excluded.data", (value.id,value.status.value,value.created_at.isoformat(),_dump(value))))

    async def get_job(self, job_id: str) -> Job | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone())
        return self._job(json.loads(row[0])) if row else None

    async def accept_admitted_job(self, value: Job, turn_id: str, *, capacity: int = 16) -> tuple[Job, bool]:
        """One transaction owns both the existing voice reservation and Job."""
        payload = BackBrainWorkPayload.from_payload(value.payload)
        if (payload.scope != "admitted_work" or value.kind != "back_brain" or value.status is not JobStatus.PENDING or value.revision != 0
                or value.requested_by_conversation_id != payload.provenance.conversation_id
                or payload.provenance.source.turn_id != turn_id
                or value.id != back_brain_job_id(payload.provenance.conversation_id, payload.provenance.source.correlation_id)
                or value.idempotency_key != value.id):
            raise ValueError("invalid admitted job")
        def accept(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM jobs WHERE id=? OR json_extract(data,'$.idempotency_key')=?", (value.id, value.idempotency_key)).fetchone()
                if row:
                    existing = self._job(json.loads(row[0]))
                    if (existing.id, existing.kind, existing.requested_by_conversation_id, existing.idempotency_key, existing.payload) != (value.id, value.kind, value.requested_by_conversation_id, value.idempotency_key, value.payload):
                        raise ValueError("conflicting immutable job")
                    conn.execute("COMMIT")
                    return existing, False
                active = conn.execute("SELECT count(*) FROM jobs WHERE json_extract(data,'$.kind')='back_brain' AND status IN ('pending','running')").fetchone()[0]
                if active >= capacity:
                    raise BackBrainUnavailable("back_brain_capacity")
                validated = self._validated_admitted_turn(conn, turn_id)
                if validated is None:
                    raise ValueError("job source has no valid canonical admission")
                turn, binding, source = validated
                proof = payload.provenance
                current_row = conn.execute("SELECT data FROM brain_current_sources WHERE conversation_id=?", (turn.conversation_id,)).fetchone()
                checkpoint_row = conn.execute("SELECT data FROM voice_conversation_snapshots WHERE conversation_id=?", (turn.conversation_id,)).fetchone()
                checkpoint = VoiceConversationSnapshot.from_dict(json.loads(checkpoint_row[0]))
                current = SpeechSource.from_payload(json.loads(current_row[0])) if current_row else None
                if current != source or checkpoint.revision != proof.snapshot_revision:
                    raise ValueError("job source is no longer current or projection changed")
                context_turns = []
                for dependency in proof.context_dependencies:
                    row = conn.execute("SELECT data FROM turns WHERE id=? AND conversation_id=?", (dependency.turn_id, turn.conversation_id)).fetchone()
                    context_turn = self._turn(json.loads(row[0])) if row else None
                    if not dependency.matches(context_turn):
                        raise ValueError("job context dependency is not exact immutable history")
                    context_turns.append(context_turn)
                if context_turns != sorted(context_turns, key=lambda value: (value.created_at, value.id)):
                    raise ValueError("job context order differs from immutable history")
                if payload.context_text != "\n".join(f"{value.kind.value}: {value.content}" for value in context_turns):
                    raise ValueError("job context text differs from its dependencies")
                if (binding.addressing.value != "addressed" or binding.conversation_id != proof.conversation_id
                        or source != proof.source or turn.content != payload.request_text
                        or (binding.session_id, binding.canonical_turn_id, binding.transcript_id, binding.transcript_revision, binding.provider_item_id)
                        != (proof.session_id, proof.canonical_turn_id, proof.transcript_id, proof.transcript_revision, proof.provider_item_id)):
                    raise ValueError("job provenance conflicts with admitted USER")
                claimed = conn.execute("UPDATE turns SET data=json_set(data,'$.metadata.backend_dispatch_reserved',json('true')) WHERE id=? AND json_type(data,'$.metadata.backend_dispatch_reserved') IS NULL", (turn_id,))
                if claimed.rowcount != 1:
                    raise BackBrainUnavailable("back_brain_already_reserved")
                conn.execute("INSERT INTO jobs VALUES(?,?,?,?)", (value.id, value.status.value, value.created_at.isoformat(), _dump(value)))
                conn.execute("COMMIT")
                return value, True
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(accept)

    async def accept_speculative_job(self, value: Job, *, capacity: int = 16) -> tuple[Job, bool]:
        """Accept immutable provisional analysis without a turn reservation."""
        from jarvis.domain.back_brain import BackBrainSpeculativeProvenance, provenance_job_id, BackBrainAdvisoryDependency
        payload = BackBrainWorkPayload.from_payload(value.payload)
        proof = payload.provenance
        if (not isinstance(proof, BackBrainSpeculativeProvenance) or value.kind != "back_brain"
                or value.status is not JobStatus.PENDING or value.revision != 0
                or value.requested_by_conversation_id != proof.conversation_id
                or value.id != provenance_job_id(proof) or value.idempotency_key != value.id
                or payload.request_text != "\n".join(d.text for d in proof.dependencies) or payload.context_text):
            raise ValueError("invalid speculative job")
        def accept(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM jobs WHERE id=?", (value.id,)).fetchone()
                if row:
                    existing = self._job(json.loads(row[0]))
                    if (existing.kind, existing.payload, existing.requested_by_conversation_id, existing.idempotency_key) != (value.kind, value.payload, value.requested_by_conversation_id, value.idempotency_key):
                        raise ValueError("conflicting immutable speculative job")
                    conn.execute("COMMIT")
                    return existing, False
                if conn.execute("SELECT count(*) FROM jobs WHERE json_extract(data,'$.kind')='back_brain' AND status IN ('pending','running')").fetchone()[0] >= capacity:
                    raise BackBrainUnavailable("back_brain_capacity")
                row = conn.execute("SELECT data FROM voice_conversation_snapshots WHERE conversation_id=?", (proof.conversation_id,)).fetchone()
                snapshot = VoiceConversationSnapshot.from_dict(json.loads(row[0])) if row else None
                if snapshot is None or snapshot.current_session_id != proof.session_id or snapshot.revision != proof.snapshot_revision:
                    raise ValueError("speculative checkpoint changed")
                current = {u.transcript_id: BackBrainAdvisoryDependency(u.correlation.session_id, u.transcript_id,
                    u.revision, u.correlation.provider_input_id, u.committed, u.text) for u in snapshot.users}
                if any(current.get(d.transcript_id) != d for d in proof.dependencies):
                    raise ValueError("speculative dependencies changed")
                conn.execute("INSERT INTO jobs VALUES(?,?,?,?)", (value.id, value.status.value, value.created_at.isoformat(), _dump(value)))
                conn.execute("COMMIT")
                return value, True
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(accept)

    async def transition_job(self, value: Job, *, expected_revision: int) -> bool:
        if value.revision != expected_revision + 1:
            raise ValueError("job transition requires next revision")
        def transition(conn):
            row = conn.execute("SELECT data FROM jobs WHERE id=?", (value.id,)).fetchone()
            current = self._job(json.loads(row[0])) if row else None
            if current is None or current.revision != expected_revision:
                return False
            allowed = {JobStatus.PENDING: {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.INTERRUPTED},
                       JobStatus.RUNNING: {JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}}
            if value.status not in allowed.get(current.status, set()):
                raise ValueError("invalid terminal job transition")
            if (current.kind, current.payload, current.idempotency_key, current.requested_by_conversation_id) != (value.kind, value.payload, value.idempotency_key, value.requested_by_conversation_id):
                raise ValueError("job transition changed immutable provenance")
            cursor = conn.execute("UPDATE jobs SET status=?,data=? WHERE id=? AND coalesce(json_extract(data,'$.revision'),0)=?", (value.status.value, _dump(value), value.id, expected_revision))
            return cursor.rowcount == 1
        return await self._run(transition)

    async def save_back_brain_advisory(self, value: BackBrainAdvisoryReference) -> BackBrainAdvisoryReference:
        if not isinstance(value, BackBrainAdvisoryReference):
            raise ValueError("typed advisory required")
        def save(conn):
            conn.execute("INSERT OR IGNORE INTO back_brain_advisories VALUES(?,?,?,?)", (value.reference_id, value.conversation_id, value.created_at, json.dumps(value.to_payload())))
            row = conn.execute("SELECT data FROM back_brain_advisories WHERE id=?", (value.reference_id,)).fetchone()
            stored = BackBrainAdvisoryReference.from_payload(json.loads(row[0]))
            if stored != value:
                raise ValueError("conflicting immutable advisory reference")
            conn.execute("DELETE FROM back_brain_advisories WHERE conversation_id=? AND id NOT IN (SELECT id FROM back_brain_advisories WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 128)", (value.conversation_id, value.conversation_id))
            return stored
        return await self._run(save)

    async def get_back_brain_advisory(self, reference_id: str) -> BackBrainAdvisoryReference | None:
        row = await self._run(lambda c: c.execute("SELECT data FROM back_brain_advisories WHERE id=?", (reference_id,)).fetchone())
        return BackBrainAdvisoryReference.from_payload(json.loads(row[0])) if row else None

    async def list_back_brain_advisories(self, conversation_id: str, *, limit: int = 32) -> tuple[BackBrainAdvisoryReference, ...]:
        rows = await self._run(lambda c: c.execute("SELECT data FROM back_brain_advisories WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?", (conversation_id, limit)).fetchall())
        return tuple(BackBrainAdvisoryReference.from_payload(json.loads(row[0])) for row in rows)

    async def list_jobs(self, *, status: str | None = None):
        if status:
            rows = await self._run(lambda c: c.execute("SELECT data FROM jobs WHERE status=? ORDER BY created_at,id", (status,)).fetchall())
        else:
            rows = await self._run(lambda c: c.execute("SELECT data FROM jobs ORDER BY created_at,id").fetchall())
        return tuple(self._job(json.loads(r[0])) for r in rows)

    async def list_conversation_jobs(self, conversation_id: str, *, limit: int = 32) -> tuple[Job, ...]:
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError("invalid job list limit")
        rows = await self._run(lambda c: c.execute("SELECT data FROM jobs WHERE json_extract(data,'$.kind')='back_brain' AND json_extract(data,'$.requested_by_conversation_id')=? ORDER BY created_at DESC,id DESC LIMIT ?", (conversation_id, limit)).fetchall())
        return tuple(self._job(json.loads(row[0])) for row in rows)

    async def list_active_back_brain_jobs(self) -> tuple[Job, ...]:
        # At most 16 admitted jobs exist normally; one extra exposes old/corrupt overflow.
        rows = await self._run(lambda c: c.execute("SELECT data FROM jobs WHERE json_extract(data,'$.kind')='back_brain' AND status IN ('pending','running') ORDER BY created_at,id LIMIT 17").fetchall())
        return tuple(self._job(json.loads(row[0])) for row in rows)

    async def back_brain_freshness(self, conversation_id, source, dependencies):
        def read(conn):
            conn.execute("BEGIN")
            try:
                row = conn.execute("SELECT data FROM brain_current_sources WHERE conversation_id=?", (conversation_id,)).fetchone()
                source_current = bool(row and SpeechSource.from_payload(json.loads(row[0])) == source)
                current = True
                for dependency in dependencies:
                    row = conn.execute("SELECT data FROM turns WHERE id=? AND conversation_id=?", (dependency.turn_id, conversation_id)).fetchone()
                    if row is None:
                        if current is True:
                            current = None
                    elif not dependency.matches(self._turn(json.loads(row[0]))):
                        current = False
                conn.execute("COMMIT")
                return source_current, current
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(read)

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

    @staticmethod
    def _live_record(row) -> LiveSessionRecord | None:
        if row is None:
            return None
        record = LiveSessionRecord.from_payload(json.loads(row[3]))
        if (row[0] != record.session_id or row[1] != record.state.value
                or type(row[2]) is not int or row[2] != record.revision):
            raise RuntimeError("Live lifecycle storage columns disagree with record")
        return record

    async def reserve_live_session(self, value: LiveSessionRecord) -> tuple[LiveSessionRecord, bool]:
        if value.state is not LiveLifecycleState.STARTING or value.revision != 1:
            raise ValueError("Live reservation must be initial STARTING state")

        def reserve(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                records = [self._live_record(row) for row in conn.execute(
                    "SELECT session_id,state,revision,data FROM live_sessions"
                ).fetchall()]
                existing = next((item for item in records if item.session_id == value.session_id), None)
                if existing is not None:
                    if (existing.state is not LiveLifecycleState.STOPPED
                            and existing.owner_incarnation_id == value.owner_incarnation_id):
                        conn.execute("COMMIT")
                        return existing, False
                    raise LiveLifecycleConflict("live_identity_conflict")
                if any(item.state is not LiveLifecycleState.STOPPED for item in records):
                    raise LiveLifecycleConflict("live_lease_held")
                conn.execute("INSERT INTO live_sessions(session_id,state,revision,data) VALUES(?,?,?,?)",
                             (value.session_id, value.state.value, value.revision, _dump(value.to_payload())))
                conn.execute("COMMIT")
                return value, True
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(reserve)

    async def get_live_session(self, session_id: str) -> LiveSessionRecord | None:
        row = await self._run(lambda conn: conn.execute(
            "SELECT session_id,state,revision,data FROM live_sessions WHERE session_id=?", (session_id,),
        ).fetchone())
        return self._live_record(row)

    async def get_unresolved_live_session(self) -> LiveSessionRecord | None:
        rows = await self._run(lambda conn: conn.execute(
            "SELECT session_id,state,revision,data FROM live_sessions",
        ).fetchall())
        records = [self._live_record(row) for row in rows]
        unresolved = [item for item in records if item.state is not LiveLifecycleState.STOPPED]
        if len(unresolved) > 1:
            raise RuntimeError("multiple unresolved Live lifecycle records")
        return unresolved[0] if unresolved else None

    async def cas_live_session(self, value: LiveSessionRecord, *, expected_revision: int) -> tuple[LiveSessionRecord, bool]:
        if type(expected_revision) is not int or value.revision != expected_revision + 1:
            raise ValueError("invalid Live lifecycle CAS revision")

        def update(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT session_id,state,revision,data FROM live_sessions WHERE session_id=?",
                    (value.session_id,),
                ).fetchone()
                current = self._live_record(row)
                if current is None:
                    raise LiveLifecycleConflict("live_session_not_found")
                if current == value:
                    conn.execute("COMMIT")
                    return current, False
                if current.revision != expected_revision:
                    raise LiveLifecycleConflict("live_stale_revision")
                cursor = conn.execute(
                    "UPDATE live_sessions SET state=?,revision=?,data=? WHERE session_id=? AND revision=?",
                    (value.state.value, value.revision, _dump(value.to_payload()),
                     value.session_id, expected_revision),
                )
                if cursor.rowcount == 1:
                    conn.execute("COMMIT")
                    return value, True
                raise LiveLifecycleConflict("live_stale_revision")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return await self._run(update)

    async def _upsert(self, table: str, key: str, value: Any) -> None:
        if table not in {"devices"}:
            raise ValueError("invalid table")
        await self._run(lambda c: c.execute(f"INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (key, _dump(value))))

    async def close(self) -> None:
        async with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                await self._thread(conn.close)

    @staticmethod
    def _conversation(d):
        return Conversation(id=d["id"],status=ConversationStatus(d["status"]),originating_device_id=d["originating_device_id"],current_device_id=d["current_device_id"],created_at=_dt(d["created_at"]),updated_at=_dt(d["updated_at"]),summary=d.get("summary", ""),transport_session_id=d.get("transport_session_id"))
    @staticmethod
    def _turn(d):
        return ConversationTurn(id=d["id"],conversation_id=d["conversation_id"],kind=TurnKind(d["kind"]),content=d["content"],created_at=_dt(d["created_at"]),correlation_id=d["correlation_id"],reference_id=d.get("reference_id"),metadata=d.get("metadata", {}))
    @staticmethod
    def _job(d):
        return Job(id=d["id"],kind=d["kind"],status=JobStatus(d["status"]),requested_by_conversation_id=d.get("requested_by_conversation_id"),payload=d.get("payload",{}),result=d.get("result"),error=d.get("error"),created_at=_dt(d["created_at"]),started_at=_dt(d.get("started_at")),completed_at=_dt(d.get("completed_at")),idempotency_key=d["idempotency_key"],revision=d.get("revision",0),cancellation=d.get("cancellation","none"),cancel_requested=d.get("cancel_requested",False),progress=d.get("progress"))
    @staticmethod
    def _scheduled(d):
        return ScheduledItem(id=d["id"],kind=d["kind"],status=ScheduledStatus(d["status"]),payload=d.get("payload",{}),next_fire_at=_dt(d["next_fire_at"]),recurrence_seconds=d.get("recurrence_seconds"),missed_run_policy=MissedRunPolicy(d["missed_run_policy"]),max_lateness_seconds=d.get("max_lateness_seconds"),last_fire_at=_dt(d.get("last_fire_at")),created_at=_dt(d["created_at"]),requested_by_conversation_id=d.get("requested_by_conversation_id"),idempotency_key=d["idempotency_key"])
    @staticmethod
    def _notification(d):
        return Notification(id=d["id"],summary=d["summary"],body=d.get("body", ""),state=NotificationState(d["state"]),priority=NotificationPriority(d["priority"]),target_device_id=d["target_device_id"],originating_reference_id=d.get("originating_reference_id"),delivery_policy=d.get("delivery_policy","system_notification"),created_at=_dt(d["created_at"]),delivered_at=_dt(d.get("delivered_at")),expires_at=_dt(d.get("expires_at")),idempotency_key=d["idempotency_key"])
