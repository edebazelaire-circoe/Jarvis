"""Semantic recall leg: a derived vector index plus its retriever (Slice 03).

Derived and disposable: `<memory>/.jarvis/semantic.sqlite3` holds float32
BLOBs keyed `(memory_id, revision, model_id, chunk_no)`. Delete the file and
nothing durable is lost: the next sync re-embeds the canonical notes. The file
carries its own `PRAGMA user_version` (not covered by the `_MIGRATIONS` rule of
CLAUDE.md, it is never migrated: a different version is dropped and rebuilt).

- Vectors are stored normalised, so cosine similarity is a dot product. The
  scan is brute force: `numpy` when importable, else stdlib `array` in pure
  Python. A capacity guard (20 000 chunks) turns a too-large index into
  `degraded: semantic_capacity`; lexical recall keeps going.
- Chunking: one chunk per note below 1 500 characters, else paragraph windows.
- Embedding never runs on the write path. A write only calls
  `SemanticIndex.notify_written(memory_id)` (any thread); a background task
  embeds and stores. A model change purges the other models' vectors and
  re-embeds; a deleted or corrupt file is recreated and re-filled.
- Notes of the `private` scope are not embedded (nor searched) unless
  `allow_private`: embeddings may leave the machine (risk R12).
- A hit is never trusted: the retriever re-reads the note from the canonical
  store and drops what no longer exists, is superseded or out of scope.

Contract page: `docs/memory.md` (Hybrid retrieval).
"""

from __future__ import annotations

import asyncio
from array import array
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import math
from operator import mul
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Protocol, TypeVar

from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    PRIVATE_SCOPE,
    CapabilityState,
    CapabilityStatus,
    DegradedReason,
    MemoryErrorCode,
    MemoryFilters,
    MemoryLevel,
    MemoryNote,
    MemoryStoreError,
    RecallQuery,
    RetentionClass,
    capability_ok,
)
from jarvis.domain.memory_leg import (
    LEG_SEMANTIC,
    LEG_TOP,
    LegDegraded,
    LegHit,
    LegResult,
    is_valid_at,
    provenance_ref,
)
from jarvis.adapters.memory_leg_pool import LegPool
from jarvis.ports.memory_retrieval import EmbeddingProvider

_LOG = logging.getLogger("jarvis")

T = TypeVar("T")

SCHEMA_VERSION = 1
#: Chunks above which the brute-force scan is refused (`semantic_capacity`).
DEFAULT_CAPACITY = 20_000
#: A note shorter than this is one chunk; a longer one is cut into paragraph windows.
CHUNK_CHARS = 1_500
#: Cosine below this is noise, not recall (an unrelated note would otherwise
#: always fill the semantic list). Deliberately low: short queries against
#: `text-embedding-3-small` often score 0.25-0.45 for genuinely relevant notes,
#: so a higher floor would cut real recall. Injectable per retriever; the value
#: for a real model is a calibration done by a human (H4/H5, `--real-embed`).
DEFAULT_MIN_SCORE = 0.18
#: Deadline checks of the pure-Python scan: every this many chunks.
_SCAN_CHECK_EVERY = 256
_EMBED_BATCH = 16
#: Consecutive embedding failures that mean the provider is down, not that one note is bad.
_SYSTEMIC_FAILURES = 3
#: Longest wait before a note that failed to embed is tried again.
_MAX_BACKOFF_S = 3_600.0
#: `index_note(known=...)` default: look the stored state up.
_LOOKUP: Any = object()

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    chunk_no INTEGER NOT NULL,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL,
    digest TEXT NOT NULL,
    scope TEXT NOT NULL,
    retention TEXT NOT NULL,
    level TEXT NOT NULL,
    updated_at REAL NOT NULL,
    valid_from REAL,
    valid_to REAL,
    superseded INTEGER NOT NULL,
    PRIMARY KEY (memory_id, revision, model_id, chunk_no)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS chunks_model ON chunks(model_id, memory_id);
"""


class SemanticCapacityExceeded(Exception):
    """The index holds (or would hold) more chunks than the brute-force scan accepts."""


class SemanticScanTimeout(Exception):
    """The scan ran past its deadline and stopped."""


class NoteStore(Protocol):
    """The slice of `MarkdownMemoryBackend` the index uses (synchronous, called in a thread)."""

    def get(self, memory_id: str) -> MemoryNote: ...

    def list(self, filters: MemoryFilters) -> tuple[MemoryNote, ...]: ...


# ---------------------------------------------------------------- chunk and vector helpers
def chunk_body(body: str, limit: int = CHUNK_CHARS) -> list[str]:
    """One chunk below `limit` characters, else paragraph windows of at most `limit`."""

    body = body.strip()
    if len(body) < limit:
        return [body]
    chunks: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = paragraph.strip()
        while len(paragraph) > limit:  # one paragraph larger than a window: hard cut
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:].lstrip()
        if not paragraph:
            continue
        if current and len(current) + 2 + len(paragraph) > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks or [""]


def embedding_texts(note: MemoryNote) -> list[str]:
    """The texts sent to the embedder: the title in front of every chunk."""

    return [f"{note.title}\n{chunk}".strip() for chunk in chunk_body(note.body)]


def note_digest(note: MemoryNote) -> str:
    """What the stored vectors depend on besides `(id, revision)`: text and filter facts."""

    def stamp(value: datetime | None) -> str:
        return "" if value is None else value.isoformat()

    parts = (
        note.title, note.body, note.scope, note.retention.value, note.level.value, str(int(note.is_superseded)),
        stamp(note.valid_from), stamp(note.valid_to),
    )
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def _normalized(vector: Sequence[float]) -> array:
    if any(not math.isfinite(value) for value in vector):
        raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "the embedder returned a non-finite value")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not norm > 0.0 or not math.isfinite(norm):
        # A zero vector has no direction: stored, it would match nothing and hide a broken provider.
        raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "the embedder returned a zero or overflowing vector")
    scale = 1.0 / norm
    return array("f", (value * scale for value in vector))


def _is_corruption(exc: sqlite3.DatabaseError) -> bool:
    """A damaged file (garbled, truncated, empty, schema lost), not a busy or locked one."""

    if isinstance(exc, sqlite3.OperationalError):
        message = str(exc).lower()
        return "no such table" in message or "no such column" in message or "malformed" in message
    return True


def _numpy() -> Any:
    """`numpy` when importable (optional extra), else `None`: the scan then runs in pure Python."""

    try:
        import numpy
    except ImportError:
        return None
    return numpy


@dataclass(frozen=True, slots=True)
class SemanticHit:
    memory_id: str
    revision: int
    chunk_no: int
    score: float


@dataclass(frozen=True, slots=True)
class _Row:
    memory_id: str
    revision: int
    chunk_no: int
    scope: str
    retention: str
    level: str
    updated_at: float
    valid_from: float | None
    valid_to: float | None
    superseded: bool


@dataclass(slots=True)
class _Snapshot:
    """The searchable rows in memory: latest revision of each note, current model only."""

    generation: int
    model_id: str
    rows: list[_Row]
    vectors: Any  # numpy float32 matrix (n, dim) or list[array('f')]
    dim: int
    numpy: Any = None  # the numpy module when `vectors` is a matrix


class SemanticIndex:
    """Vector store plus the background embedding queue of one memory root."""

    def __init__(
        self,
        path: Path,
        embedder: EmbeddingProvider,
        store: NoteStore,
        *,
        allow_private: bool = False,
        capacity: int = DEFAULT_CAPACITY,
        embed_timeout_s: float = 10.0,
        retry_interval_s: float = 30.0,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.path = Path(path)
        self.embedder = embedder
        self.store = store
        self.allow_private = allow_private
        self.capacity = capacity
        self._embed_timeout_s = embed_timeout_s
        self._retry_interval_s = retry_interval_s
        self._lock = threading.RLock()
        self._generation = 0
        self._snapshot_cache: _Snapshot | None = None
        self._count_cache: tuple[int, int] | None = None
        # A full reconcile is owed until one completes (new file, new model, lost file).
        self._dirty = True
        self._building = False
        self._capacity_hit = False
        self._last_error = ""
        self._pending: dict[str, None] = {}
        self._pending_lock = threading.Lock()
        # Notes that failed to embed while others succeeded: note id -> (attempts, retry not before).
        self._poison: dict[str, tuple[int, float]] = {}
        self._reconcile_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        _numpy()  # the import costs about 0.2 s: paid here, never inside the first recall
        self._prepare()
        self._sync_model()

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        """True once the index mirrors the store (no full reconcile owed or running)."""

        return not self._dirty and not self._building

    @property
    def capacity_hit(self) -> bool:
        return self._capacity_hit

    @property
    def poisoned(self) -> int:
        """Notes the embedder refuses (they stay out of the index, the rest is served)."""

        return len(self._poison)

    @property
    def last_error(self) -> str:
        return self._last_error

    def readable_scopes(self, scopes: Iterable[str]) -> tuple[str, ...]:
        """`scopes` the index may search: `private` only when `allow_private`."""

        return tuple(scope for scope in scopes if self.allow_private or scope != PRIVATE_SCOPE)

    def wants(self, note: MemoryNote) -> bool:
        return self.allow_private or note.scope != PRIVATE_SCOPE

    # ---------------------------------------------------------------- storage
    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                _LOG.info("semantic index schema v%s is not v%s: dropped, it is derived and rebuilds", version, SCHEMA_VERSION)
                conn.executescript("DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS meta;")
            conn.executescript(_DDL)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        finally:
            conn.close()

    def _prepare(self) -> None:
        """Create the file and its schema; a damaged file is discarded (derived state)."""

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._init_schema()
            except sqlite3.DatabaseError:
                _LOG.warning("semantic index %s is damaged: recreated, it re-embeds from the notes", self.path.name)
                for suffix in ("", "-wal", "-shm", "-journal"):
                    Path(f"{self.path}{suffix}").unlink(missing_ok=True)
                self._init_schema()
            self._invalidate()

    def _invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._snapshot_cache = None

    def _ensure_file(self) -> None:
        """The file was deleted under us: recreate it empty and owe a full reconcile."""

        if self.path.exists():
            return
        with self._lock:
            if not self.path.exists():
                _LOG.info("semantic index file is gone: recreated, a rebuild follows")
                self._prepare()
                self._sync_model()
                self._dirty = True

    @contextmanager
    def _connection(self):
        self._ensure_file()
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _recover(self, exc: sqlite3.DatabaseError) -> None:
        """The file is damaged while running (garbled, truncated, empty): recreate it, owe a rebuild."""

        _LOG.warning("semantic index is damaged (%s: %s): recreated, it re-embeds from the notes", type(exc).__name__, exc)
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)
        self._init_schema()
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('model_id', ?)", (self.embedder.model_id,))
            conn.commit()
        finally:
            conn.close()
        self._dirty = True
        self._invalidate()

    def _run(self, work: Callable[[sqlite3.Connection], T], after: Callable[[T], None] | None = None) -> T:
        """Run `work(conn)` in one transaction under the lock; a damaged file is recreated and `work` retried once.

        `after(result)` runs under the same lock once the transaction committed
        (the cache moves only with the file).
        """

        with self._lock:
            try:
                with self._connection() as conn:
                    result = work(conn)
            except sqlite3.DatabaseError as exc:
                if not _is_corruption(exc):
                    raise
                self._recover(exc)
                with self._connection() as conn:
                    result = work(conn)
            if after is not None:
                after(result)
            return result

    def _sync_model(self) -> None:
        """A model change invalidates every stored vector of the other models."""

        model = self.embedder.model_id

        def work(conn: sqlite3.Connection) -> bool:
            row = conn.execute("SELECT value FROM meta WHERE key='model_id'").fetchone()
            if row is not None and row["value"] == model and not conn.execute(
                "SELECT 1 FROM chunks WHERE model_id != ? LIMIT 1", (model,),
            ).fetchone():
                return False
            conn.execute("DELETE FROM chunks WHERE model_id != ?", (model,))
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('model_id', ?)", (model,))
            return True

        def after(changed: bool) -> None:
            if changed:
                self._dirty = True
                self._invalidate()

        self._run(work, after)

    def count(self) -> int:
        return self._run(lambda conn: conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE model_id=?", (self.embedder.model_id,),
        ).fetchone()[0])

    def _chunk_count(self) -> int:
        """`count()`, remembered until the next write."""

        with self._lock:
            cached = self._count_cache
            if cached is not None and cached[0] == self._generation:
                return cached[1]
            generation = self._generation
        total = self.count()
        with self._lock:
            self._count_cache = (generation, total)
        return total

    def indexed(self) -> dict[str, tuple[int, str]]:
        """Latest `(revision, digest)` stored per note for the current model."""

        rows = self._run(lambda conn: conn.execute(
            "SELECT memory_id, MAX(revision) AS revision, digest FROM chunks WHERE model_id=? GROUP BY memory_id",
            (self.embedder.model_id,),
        ).fetchall())
        return {row["memory_id"]: (row["revision"], row["digest"]) for row in rows}

    def stored(self, memory_id: str) -> tuple[int, str] | None:
        """Latest `(revision, digest)` stored for one note under the current model."""

        row = self._run(lambda conn: conn.execute(
            "SELECT MAX(revision) AS revision, digest FROM chunks WHERE model_id=? AND memory_id=?",
            (self.embedder.model_id, memory_id),
        ).fetchone())
        return None if row is None or row["revision"] is None else (row["revision"], row["digest"])

    def store_vectors(self, note: MemoryNote, vectors: Sequence[Sequence[float]], digest: str) -> None:
        """Replace the stored chunks of `note` with `vectors` (one per chunk), in one transaction."""

        model = self.embedder.model_id
        blobs = [_normalized(vector) for vector in vectors]
        valid_from = None if note.valid_from is None else note.valid_from.timestamp()
        valid_to = None if note.valid_to is None else note.valid_to.timestamp()
        rows = [
            (note.id, note.revision, model, number, len(blob), blob.tobytes(), digest, note.scope,
             note.retention.value, note.level.value, note.updated_at.timestamp(), valid_from, valid_to,
             int(note.is_superseded))
            for number, blob in enumerate(blobs)
        ]
        added = [
            (_Row(note.id, note.revision, number, note.scope, note.retention.value, note.level.value,
                  note.updated_at.timestamp(), valid_from, valid_to, note.is_superseded), blob.tobytes())
            for number, blob in enumerate(blobs)
        ]

        def work(conn: sqlite3.Connection) -> int:
            others = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE model_id=? AND memory_id != ?", (model, note.id),
            ).fetchone()[0]
            if others + len(rows) > self.capacity:
                raise SemanticCapacityExceeded(f"{others + len(rows)} chunks exceed the capacity {self.capacity}")
            conn.execute("DELETE FROM chunks WHERE memory_id=?", (note.id,))
            conn.executemany(
                "INSERT INTO chunks(memory_id,revision,model_id,chunk_no,dim,vec,digest,scope,retention,level,"
                "updated_at,valid_from,valid_to,superseded) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows,
            )
            return others + len(rows)

        def after(total: int) -> None:
            self._advance({note.id}, added, total)
            self._maybe_clear_capacity(total)

        self._run(work, after)

    def remove(self, memory_ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(memory_ids))
        if not ids:
            return

        def work(conn: sqlite3.Connection) -> int:
            conn.executemany("DELETE FROM chunks WHERE memory_id=?", [(item,) for item in ids])
            return conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE model_id=?", (self.embedder.model_id,),
            ).fetchone()[0]

        def after(total: int) -> None:
            self._advance(set(ids), [], total)
            self._maybe_clear_capacity(total)

        self._run(work, after)

    def _maybe_clear_capacity(self, total: int) -> None:
        """Removals brought the index back under the guard: serve again and refill what was refused."""

        if self._capacity_hit and total <= self.capacity:
            self._capacity_hit = False
            self._dirty = True

    def _advance(self, removed: set[str], added: list[tuple[_Row, bytes]], total: int) -> None:
        """Move the in-memory snapshot past a committed write instead of rebuilding it on the next recall.

        Copy-on-write: a scan that holds the previous snapshot is unaffected.
        """

        model = self.embedder.model_id
        old = self._snapshot_cache
        usable = old is not None and old.generation == self._generation and old.model_id == model
        self._generation += 1
        self._count_cache = (self._generation, total)
        if not usable:
            self._snapshot_cache = None
            return
        assert old is not None
        dim = old.dim
        keep = [index for index, row in enumerate(old.rows) if row.memory_id not in removed]
        blobs = [blob for _, blob in added if len(blob) == dim * 4]
        added_rows = [row for row, blob in added if len(blob) == dim * 4]
        rows = [old.rows[index] for index in keep] + added_rows
        numpy = old.numpy if old.numpy is not None else (_numpy() if not old.vectors else None)
        vectors: Any
        if not rows:
            vectors, numpy = [], None
        elif numpy is not None:
            parts = []
            if keep:
                parts.append(old.vectors[keep] if len(keep) != len(old.rows) else old.vectors)
            if blobs:
                parts.append(numpy.frombuffer(b"".join(blobs), dtype=numpy.float32).reshape(len(blobs), dim))
            vectors = parts[0] if len(parts) == 1 else numpy.concatenate(parts)
        else:
            vectors = [old.vectors[index] for index in keep]
            for blob in blobs:
                vector = array("f")
                vector.frombytes(blob)
                vectors.append(vector)
        self._snapshot_cache = _Snapshot(self._generation, model, rows, vectors, dim, numpy)

    # ----------------------------------------------------------------- search
    def _snapshot(self) -> _Snapshot:
        model = self.embedder.model_id
        with self._lock:
            cached = self._snapshot_cache
            if cached is not None and cached.generation == self._generation and cached.model_id == model:
                return cached
            dim = self.embedder.dim

            def load(conn: sqlite3.Connection) -> tuple[list[_Row], list[bytes]]:
                rows: list[_Row] = []
                blobs: list[bytes] = []
                latest: dict[str, int] = {}
                cursor = conn.execute(
                    "SELECT memory_id,revision,chunk_no,dim,vec,scope,retention,level,updated_at,valid_from,valid_to,"
                    "superseded FROM chunks WHERE model_id=? ORDER BY memory_id, revision DESC, chunk_no", (model,),
                )
                for row in cursor:
                    if row["dim"] != dim or len(row["vec"]) != dim * 4:
                        continue
                    if latest.setdefault(row["memory_id"], row["revision"]) != row["revision"]:
                        continue
                    rows.append(_Row(
                        row["memory_id"], row["revision"], row["chunk_no"], row["scope"], row["retention"], row["level"],
                        row["updated_at"], row["valid_from"], row["valid_to"], bool(row["superseded"]),
                    ))
                    blobs.append(row["vec"])
                return rows, blobs

            rows, blobs = self._run(load)
            generation = self._generation  # a recovery inside `_run` moved it
            numpy = _numpy()
            if numpy is not None and blobs:
                vectors: Any = numpy.frombuffer(b"".join(blobs), dtype=numpy.float32).reshape(len(blobs), dim)
            else:
                vectors = []
                for blob in blobs:
                    vector = array("f")
                    vector.frombytes(blob)
                    vectors.append(vector)
            snapshot = _Snapshot(generation, model, rows, vectors, dim, numpy if blobs else None)
            self._snapshot_cache = snapshot
            return snapshot

    def search(
        self,
        vector: Sequence[float],
        *,
        scopes: Sequence[str],
        retentions: Sequence[RetentionClass] = (),
        levels: Sequence[MemoryLevel] = (),
        include_history: bool = False,
        at: datetime | None = None,
        limit: int = LEG_TOP,
        min_score: float = DEFAULT_MIN_SCORE,
        deadline: float | None = None,
    ) -> list[SemanticHit]:
        """Best chunk per note by cosine, best first. `deadline` is a `time.monotonic()` instant."""

        self._ensure_file()
        if self._capacity_hit or self._chunk_count() > self.capacity:
            raise SemanticCapacityExceeded(f"more than {self.capacity} chunks")
        snapshot = self._snapshot()
        if not snapshot.rows:
            return []
        query = _normalized(vector)
        if len(query) != snapshot.dim:
            raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "query vector does not match the index dimension")
        stamp = (at or datetime.now(timezone.utc)).timestamp()
        allowed_scopes = frozenset(scopes)
        allowed_retentions = frozenset(item.value for item in retentions)
        allowed_levels = frozenset(item.value for item in levels)
        candidates = [
            index for index, row in enumerate(snapshot.rows)
            if row.scope in allowed_scopes
            and (not allowed_retentions or row.retention in allowed_retentions)
            and (not allowed_levels or row.level in allowed_levels)
            and (include_history or (
                not row.superseded
                and (row.valid_from is None or row.valid_from <= stamp)
                and (row.valid_to is None or stamp < row.valid_to)
            ))
        ]
        scores = self._scores(snapshot, query, candidates, deadline)
        best: dict[str, tuple[float, int, int]] = {}
        for index, score in zip(candidates, scores):
            row = snapshot.rows[index]
            if score >= min_score and (row.memory_id not in best or score > best[row.memory_id][0]):
                best[row.memory_id] = (score, row.chunk_no, row.revision)
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:limit]
        return [SemanticHit(memory_id, revision, chunk, score) for memory_id, (score, chunk, revision) in ranked]

    @staticmethod
    def _scores(snapshot: _Snapshot, query: array, candidates: list[int], deadline: float | None) -> list[float]:
        if not candidates:
            return []
        numpy = snapshot.numpy
        if numpy is not None:
            matrix = snapshot.vectors[candidates] if len(candidates) != len(snapshot.rows) else snapshot.vectors
            result = matrix @ numpy.asarray(query, dtype=numpy.float32)
            if deadline is not None and time.monotonic() > deadline:
                raise SemanticScanTimeout("scan finished past its deadline")
            return [float(value) for value in result]
        scores: list[float] = []
        for position, index in enumerate(candidates):
            if deadline is not None and position % _SCAN_CHECK_EVERY == 0 and time.monotonic() > deadline:
                raise SemanticScanTimeout(f"scan stopped after {position} of {len(candidates)} chunks")
            scores.append(sum(map(mul, query, snapshot.vectors[index])))
        return scores

    # -------------------------------------------------------------- embedding
    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = list(texts[start:start + _EMBED_BATCH])
            got = await asyncio.wait_for(self.embedder.embed(batch, self._embed_timeout_s), self._embed_timeout_s)
            if len(got) != len(batch) or any(len(vector) != self.embedder.dim for vector in got):
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "the embedder returned the wrong number or size of vectors")
            vectors.extend(got)
        return vectors

    async def index_note(self, note: MemoryNote, *, known: Any = _LOOKUP) -> bool:
        """Embed and store `note` unless its vectors are current. True when it was embedded."""

        if not self.wants(note):
            await asyncio.to_thread(self.remove, [note.id])
            return False
        digest = note_digest(note)
        if known is _LOOKUP:
            known = await asyncio.to_thread(self.stored, note.id)
        if known == (note.revision, digest):
            return False
        vectors = await self._embed(embedding_texts(note))
        await asyncio.to_thread(self.store_vectors, note, vectors, digest)
        return True

    async def _index_one(self, memory_id: str) -> None:
        try:
            note = await asyncio.to_thread(self.store.get, memory_id)
        except MemoryStoreError as exc:
            if exc.code is not MemoryErrorCode.NOT_FOUND:
                raise
            await asyncio.to_thread(self.remove, [memory_id])  # deleted note: its vectors go too
            return
        except MemorySecurityError:
            return
        await self.index_note(note)

    def _list_notes(self) -> list[MemoryNote]:
        notes: list[MemoryNote] = []
        offset = 0
        while True:
            page = self.store.list(MemoryFilters(include_superseded=True, limit=500, offset=offset))
            notes.extend(page)
            if len(page) < 500:
                return notes
            offset += 500

    def _record_failure(self, exc: BaseException) -> None:
        # Texts never reach a log: only the failure class and its (sanitised) message.
        self._last_error = f"{type(exc).__name__}: {exc}"[:200]
        _LOG.warning("semantic index embedding failed: %s", self._last_error)

    def _backed_off(self, memory_id: str) -> bool:
        entry = self._poison.get(memory_id)
        return entry is not None and time.monotonic() < entry[1]

    def _park(self, memory_id: str) -> None:
        """Remember a note the embedder refused; it is retried later with a growing delay."""

        attempts = self._poison.get(memory_id, (0, 0.0))[0] + 1
        delay = min(self._retry_interval_s * 2 ** (attempts - 1), _MAX_BACKOFF_S)
        self._poison[memory_id] = (attempts, time.monotonic() + delay)

    async def reconcile(self) -> int:
        """Bring the index in line with the store (new, changed, deleted, other-model notes).

        Returns the notes embedded. A note the embedder refuses is parked (retried
        later with a growing delay, the status says so) and the pass goes on with
        the others. When the provider itself is down (every attempt fails, or
        several in a row) the pass stops and leaves a full reconcile owed. The
        capacity guard stops it and flags `capacity_hit`.
        """

        async with self._reconcile_lock:
            self._building = True
            self._dirty = False
            self._capacity_hit = False
            done = fine = failures = streak = 0
            last: Exception | None = None
            try:
                await asyncio.to_thread(self._sync_model)
                self._dirty = False
                notes = await asyncio.to_thread(self._list_notes)
                wanted = {note.id: note for note in notes if self.wants(note)}
                have = await asyncio.to_thread(self.indexed)
                await asyncio.to_thread(self.remove, [memory_id for memory_id in have if memory_id not in wanted])
                for stale in [memory_id for memory_id in self._poison if memory_id not in wanted]:
                    del self._poison[stale]
                for note in wanted.values():
                    if self._backed_off(note.id):
                        continue
                    try:
                        if await self.index_note(note, known=have.get(note.id)):
                            done += 1
                        self._poison.pop(note.id, None)
                        fine += 1
                        streak = 0
                    except (SemanticCapacityExceeded, asyncio.CancelledError):
                        raise
                    except Exception as exc:  # noqa: BLE001 - provider boundary: one bad note must not stop the pass
                        last, failures, streak = exc, failures + 1, streak + 1
                        self._record_failure(exc)
                        self._park(note.id)
                        if streak >= _SYSTEMIC_FAILURES:
                            break
                if failures and (streak >= _SYSTEMIC_FAILURES or fine == 0):
                    # Nothing went through (a note already current counts as through), or a run of
                    # failures: the provider is down, not the notes.
                    for note in wanted.values():
                        self._poison.pop(note.id, None)
                    self._dirty = True
                elif failures:
                    self._last_error = f"{len(self._poison)} note(s) could not be embedded: {last}"[:200]
                else:
                    self._last_error = ""
            except SemanticCapacityExceeded as exc:
                self._capacity_hit = True
                _LOG.warning("semantic index capacity reached: %s", exc)
            except asyncio.CancelledError:
                self._dirty = True
                raise
            except Exception as exc:  # noqa: BLE001 - store boundary: captured, logged, retried
                self._dirty = True
                self._record_failure(exc)
            finally:
                self._building = False
            return done

    # ------------------------------------------------------------ write queue
    def notify_written(self, memory_id: str) -> None:
        """A note was created, revised or deleted. Safe from any thread, never blocks, never embeds."""

        with self._pending_lock:
            self._pending[memory_id] = None
            self._poison.pop(memory_id, None)  # a new write is a new chance: no waiting out the back-off
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:  # the loop is closed: the next start() picks the queue up
                pass

    def _take_pending(self) -> list[str]:
        with self._pending_lock:
            ids = list(self._pending)
            self._pending.clear()
        return ids

    def _has_pending(self) -> bool:
        with self._pending_lock:
            return bool(self._pending)

    async def process_pending(self) -> int:
        """Embed the queued notes. A refused note is parked and the others go on; a provider down parks the rest."""

        done = streak = 0
        while True:
            ids = self._take_pending()
            if not ids:
                return done
            for position, memory_id in enumerate(ids):
                try:
                    await self._index_one(memory_id)
                    self._poison.pop(memory_id, None)
                    done += 1
                    streak = 0
                    self._last_error = "" if not self._poison else self._last_error
                except SemanticCapacityExceeded as exc:
                    self._capacity_hit = True
                    _LOG.warning("semantic index capacity reached: %s", exc)
                except asyncio.CancelledError:
                    for rest in ids[position:]:
                        self._park(rest)
                    raise
                except Exception as exc:  # noqa: BLE001 - provider boundary: captured, logged, retried
                    self._record_failure(exc)
                    self._park(memory_id)
                    streak += 1
                    if streak >= _SYSTEMIC_FAILURES:
                        for rest in ids[position + 1:]:
                            self._park(rest)
                        return done

    async def sync(self) -> None:
        """One worker step: the owed full reconcile, then the queued notes."""

        if self._dirty or self._building:  # a running pass is waited for, then checked again
            await self.reconcile()
        await self.process_pending()
        if self._dirty and not self._last_error:  # the file was recreated under the queue: refill at once
            await self.reconcile()

    def start(self) -> None:
        """Start the background worker on the running loop (idempotent)."""

        if self._task is not None and not self._task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._task = self._loop.create_task(self._worker(), name="memory-semantic-index")

    def kick(self) -> None:
        """Make sure a rebuild is running when the index is not ready (called by a recall)."""

        if not self.ready:
            self.start()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _worker(self) -> None:
        wake = self._wake
        assert wake is not None
        while True:
            await self.sync()
            if self._has_pending():
                continue
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), self._retry_interval_s)
            except asyncio.TimeoutError:
                now = time.monotonic()
                with self._pending_lock:
                    self._pending.update(dict.fromkeys(
                        memory_id for memory_id, (_, retry_at) in self._poison.items() if retry_at <= now
                    ))


class SemanticRetriever:
    """`RecallLeg` over a `SemanticIndex`: embed the query, scan, re-read canonical notes."""

    name = LEG_SEMANTIC

    def __init__(self, index: SemanticIndex, *, min_score: float = DEFAULT_MIN_SCORE) -> None:
        self.index = index
        self._min_score = min_score
        self._last_error = ""
        self._pool = LegPool("semantic")

    async def hits(self, query: RecallQuery, limit: int = LEG_TOP, timeout_s: float = 0.25) -> LegResult:
        scopes = self.index.readable_scopes(query.scopes)
        if not scopes:
            return LegResult()  # nothing the index may search: the query text is not even sent
        deadline = time.monotonic() + timeout_s
        self.index.kick()
        try:
            vectors = await asyncio.wait_for(self.index.embedder.embed([query.text], timeout_s), timeout_s)
            if len(vectors) != 1 or len(vectors[0]) != self.index.embedder.dim:
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "the embedder returned a vector of the wrong size")
        except asyncio.TimeoutError as exc:
            self._last_error = "query embedding timed out"
            raise LegDegraded(DegradedReason.SEMANTIC_TIMEOUT, self._last_error) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider boundary: becomes a degraded reason, never a failed recall
            self._last_error = f"{type(exc).__name__}: {exc}"[:200]
            _LOG.warning("semantic query embedding failed: %s", self._last_error)
            raise LegDegraded(DegradedReason.SEMANTIC_UNAVAILABLE, self._last_error) from exc
        self._last_error = ""
        at = query.at or datetime.now(timezone.utc)
        try:
            found = await self._pool.run(
                self.index.search, vectors[0], scopes=scopes, retentions=query.retentions, levels=query.levels,
                include_history=query.include_history, at=at, limit=limit, min_score=self._min_score,
                deadline=deadline,
            )
            hits = await self._pool.run(self._hydrate, query, scopes, at, found)
        except SemanticCapacityExceeded as exc:
            raise LegDegraded(DegradedReason.SEMANTIC_CAPACITY, str(exc)) from exc
        except SemanticScanTimeout as exc:
            raise LegDegraded(DegradedReason.SEMANTIC_TIMEOUT, str(exc)) from exc
        except (MemoryStoreError, sqlite3.Error) as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"[:200]
            _LOG.warning("semantic leg failed: %s", self._last_error)
            raise LegDegraded(DegradedReason.SEMANTIC_UNAVAILABLE, self._last_error) from exc
        partial = not self.index.ready or self.index.poisoned
        return LegResult(tuple(hits), DegradedReason.SEMANTIC_UNAVAILABLE if partial else None)

    def _hydrate(self, query: RecallQuery, scopes: Sequence[str], at: datetime, found: Sequence[SemanticHit]) -> list[LegHit]:
        """Read each hit from the canonical store and re-check what the vector row may have missed."""

        hits: list[LegHit] = []
        for hit in found:
            try:
                note = self.index.store.get(hit.memory_id)
            except MemoryStoreError as exc:
                if exc.code is not MemoryErrorCode.NOT_FOUND:
                    raise
                self.index.notify_written(hit.memory_id)  # a deleted note: the worker drops its vectors
                continue
            except MemorySecurityError:
                continue
            if note.scope not in scopes:
                continue
            if query.retentions and note.retention not in query.retentions:
                continue
            if query.levels and note.level not in query.levels:
                continue
            if not query.include_history and (note.is_superseded or not is_valid_at(note.valid_from, note.valid_to, at)):
                continue
            chunks = chunk_body(note.body)
            chunk = chunks[hit.chunk_no] if note.revision == hit.revision and hit.chunk_no < len(chunks) else chunks[0]
            hits.append(LegHit(
                memory_id=note.id, revision=note.revision, updated_at=note.updated_at, title=note.title,
                snippet=chunk, level=note.level, retention=note.retention,
                provenance_ref=provenance_ref(note.retention, note.id), superseded=note.is_superseded,
                why=f"cosine {hit.score:.2f}",
            ))
        return hits

    def status(self) -> CapabilityState:
        index = self.index
        if index.capacity_hit:
            return CapabilityState(
                CapabilityStatus.DEGRADED, "semantic_capacity",
                f"more than {index.capacity} chunks: the semantic leg is off, lexical recall continues",
            )
        error = self._last_error or index.last_error
        if error:
            return CapabilityState(CapabilityStatus.DEGRADED, "semantic_unavailable", f"embedding failed: {error}"[:300])
        if not index.ready:
            return CapabilityState(CapabilityStatus.DEGRADED, "semantic_rebuilding", "the semantic index is being built")
        return capability_ok()
