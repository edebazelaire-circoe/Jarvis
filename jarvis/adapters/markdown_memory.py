"""Markdown memory: the canonical store plus the legacy `MemoryBackend`.

Markdown is canonical; SQLite (`<root>/.jarvis/index.sqlite3`) is disposable
derived search state. Two ports on one class (handoff
jarvis-memory-intelligence-knowledge, Slice 02, contract page `docs/memory.md`):

- `MemoryBackend` (legacy, V1): `search` (capped at 10), `read`, `append_note`,
  `rebuild_index`. Behaviour kept; `append_note` now lands in
  `short_term_memory/` instead of `notes/`, same bytes.
- `CanonicalMemoryStore` (synchronous, called through a thread): `get`, `list`,
  `create`, `revise` (optimistic revision, prior revision kept under
  `.history/`), `history`, `rebuild_indexes`; plus `search_ranked` (no 10 cap,
  filters) and `promote_file` (copy with provenance, used by maintenance).

Layout: `<root>/<retention class>/*.md`; the directory is the retention class.
A legacy `notes/` file (or any file outside the five classes) is recalled as
`long_term_memory` and never moved. Directories starting with `.` or `_`
(`.jarvis`, `.history`, `_candidates`) are never indexed. A file without front
matter is a legacy note: its metadata is derived on read and written only when
the note is revised.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unicodedata
import urllib.parse
import uuid
from typing import Any, Mapping

from jarvis.adapters import memory_frontmatter
from jarvis.adapters.file_replace import replace_with_retry
from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.memory import (
    LEGACY_NOTES_RETENTION,
    MAX_SOURCES,
    MemoryErrorCode,
    MemoryFilters,
    MemoryKind,
    MemoryLevel,
    MemoryNote,
    MemoryPatch,
    MemoryStoreError,
    Provenance,
    RetentionClass,
    SourceType,
    new_memory_id,
)
from jarvis.domain.memory_policy import check_level_retention, is_level_allowed, is_protected
from jarvis.domain.results import MemoryHit, MemoryRecord

_LOG = logging.getLogger("jarvis")

HISTORY_DIR = ".history"
#: Legacy `append_note` and every new write land here (architecture D3).
NEW_WRITE_RETENTION = RetentionClass.SHORT_TERM
#: Longest wait for the start-up index sync before an operation goes ahead
#: anyway (it still queues behind the sync on the store lock).
_READY_TIMEOUT_S = 60.0
#: Hard ceiling of `search_ranked`; the legacy `search` keeps its 10.
MAX_RANKED_LIMIT = 500

_RETENTION_DIRS = frozenset(item.value for item in RetentionClass)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_REVISION_SUFFIX = r"\.rev(\d+)\.md"
#: Front-matter keys the store owns; any other key is kept untouched on revise.
_KNOWN_KEYS = (
    "id", "level", "kind", "scope", "created_at", "updated_at", "revision", "confidence",
    "agent", "valid_from", "valid_to", "sources", "supersedes", "superseded_by", "contradicts",
)
#: A protected note's content is never rewritten, by anyone.
_REWRITE_FIELDS = frozenset({"title", "body", "level", "kind", "confidence"})


@dataclass(frozen=True, slots=True)
class _Meta:
    """Row of `memory_meta`: the filterable facts of one note file."""

    note_id: str
    retention: str
    level: str
    kind: str
    scope: str
    revision: int
    updated_at: float
    superseded: bool
    valid_from: float | None
    valid_to: float | None


@dataclass(frozen=True, slots=True)
class _IndexedDoc:
    memory_id: str
    title: str
    body: str
    meta: _Meta | None = None


@dataclass(frozen=True, slots=True)
class _Loaded:
    """One note file read and interpreted. `note` is `None` when it cannot be represented."""

    rel: str
    text: str
    parsed: memory_frontmatter.FrontMatter
    title: str
    body: str
    note: MemoryNote | None
    #: Metadata was derived (legacy, corrupt or invalid block), not read from the file.
    derived: bool


@dataclass(frozen=True, slots=True)
class RankedMemoryHit:
    """A `search_ranked` result: ranked, with the facts a retriever filters on."""

    memory_id: str
    path: str
    title: str
    snippet: str
    score: float
    retention: RetentionClass
    level: MemoryLevel
    kind: MemoryKind
    scope: str
    revision: int
    updated_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None


def legacy_note_id(rel: str) -> str:
    """Stable id of a note that stores none: derived from its relative path."""

    return "legacy-" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:20]


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _utc(value: float | None) -> datetime | None:
    """Epoch seconds to an aware datetime; out-of-range values clamp to `datetime.min`/`max`."""

    if value is None:
        return None
    try:
        return _EPOCH + timedelta(seconds=value)
    except OverflowError:
        return datetime.min.replace(tzinfo=timezone.utc) if value < 0 else datetime.max.replace(tzinfo=timezone.utc)


def _ts(value: datetime | None) -> float | None:
    return None if value is None else value.timestamp()


class MarkdownMemoryBackend:
    """Markdown is canonical; SQLite is disposable derived search state."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.root / ".jarvis"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.meta_dir / "index.sqlite3"
        self._lock = threading.RLock()
        try:
            self._fts = self._ensure_schema()
        except sqlite3.DatabaseError:
            # The index is derived state. If it is corrupt, throw it away and
            # recover from canonical Markdown rather than failing the runtime.
            self.db_path.unlink(missing_ok=True)
            self._fts = self._ensure_schema()
        # Resync at process start so edits performed directly in the Markdown
        # vault while Jarvis was stopped cannot leave stale search results
        # behind. Off the constructor: a vault of thousands of notes must not
        # block Core start. Every read waits for it (`_wait_ready`).
        self._ready = threading.Event()
        threading.Thread(target=self._initial_sync, name="memory-index-sync", daemon=True).start()

    # ------------------------------------------------------------ legacy port
    async def search(self, query: str, limit: int = 5) -> list[MemoryHit]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    async def read(self, memory_id: str) -> MemoryRecord:
        return await asyncio.to_thread(self._read_sync, memory_id)

    async def append_note(self, title: str, body: str) -> MemoryRecord:
        return await asyncio.to_thread(self._append_note_sync, title, body)

    async def rebuild_index(self) -> int:
        return await asyncio.to_thread(self.rebuild_indexes)

    # --------------------------------------------------------- canonical port
    def get(self, memory_id: str) -> MemoryNote:
        """Latest revision of a note. `memory_not_found` when the id is unknown."""

        return self._find(memory_id).note

    def list(self, filters: MemoryFilters) -> tuple[MemoryNote, ...]:
        """Latest revisions matching `filters`, newest `updated_at` first, ties by id."""

        self._wait_ready()
        where, params = self._filter_sql(filters)
        sql = (f"SELECT path FROM memory_meta m{where} ORDER BY m.updated_at DESC, m.id ASC LIMIT ? OFFSET ?")
        params = [*params, filters.limit, filters.offset]

        def query() -> list[str]:
            with self._lock, self._connection() as conn:
                return [row["path"] for row in conn.execute(sql, params)]

        notes = []
        for rel in self._indexed(query):
            loaded = self._read_loaded(rel)
            if loaded is not None and loaded.note is not None:
                notes.append(loaded.note)
        return tuple(notes)

    def create(self, note: MemoryNote, *, filename: str | None = None) -> MemoryNote:
        """Persist a new note (caller-assigned id, revision 1) and return it as stored.

        `filename` only serves promotion, which keeps the source file name.
        """

        if not isinstance(note, MemoryNote):
            raise TypeError("note must be a MemoryNote")
        if note.revision != 1:
            raise ValueError("a new note starts at revision 1")
        check_level_retention(note.level, note.retention)
        self._wait_ready()
        with self._lock:
            if self._known_id(note.id):
                raise MemoryStoreError(MemoryErrorCode.CONFLICT_REVISION, f"note {note.id} already exists")
            directory = self._plain_dir(note.retention.value)
            name = self._safe_filename(filename) if filename is not None else self._new_name(note.title, note.id)
            target = directory / name
            if target.exists():
                raise FileExistsError(name)
            text = self._render(note, {})
            try:
                tmp = self._stage(directory, text)
                self._commit_new(tmp, target)
            except FileExistsError:
                raise
            except (OSError, UnicodeEncodeError) as exc:
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"note not written: {exc}") from exc
            loaded = self._loaded_from_text(self._rel(target), text, target.stat().st_mtime)
            self._index_after_write(self._doc_from_loaded(loaded, target.stat().st_mtime))
        return loaded.note

    def revise(self, memory_id: str, patch: MemoryPatch, expected_revision: int, *, human: bool = False) -> MemoryNote:
        """Write revision N+1 and keep revision N under `.history/`; never edits in place.

        `memory_conflict_revision` when `expected_revision` is not the current
        one. A protected note (`traumatic_memory`, `eternal_memory`) is never
        rewritten, and only a human (`human=True`) may change its links or
        validity (supersession).
        """

        if not isinstance(patch, MemoryPatch):
            raise TypeError("patch must be a MemoryPatch")
        self._wait_ready()
        with self._lock:
            loaded = self._find(memory_id)
            current = loaded.note
            if is_protected(current.retention):
                rewrites = sorted(_REWRITE_FIELDS.intersection(patch.changed_fields))
                if rewrites or not human:
                    raise MemoryStoreError(
                        MemoryErrorCode.SCOPE_DENIED,
                        f"{current.retention.value} is protected: "
                        + (f"{', '.join(rewrites)} cannot be rewritten" if rewrites else "only a human may change it"),
                    )
            if expected_revision != current.revision:
                raise MemoryStoreError(
                    MemoryErrorCode.CONFLICT_REVISION,
                    f"expected revision {expected_revision}, current is {current.revision}",
                )
            now = max(datetime.now(timezone.utc), current.created_at)
            revised = replace(
                current,
                title=current.title if patch.title is None else patch.title,
                body=current.body if patch.body is None else patch.body,
                level=current.level if patch.level is None else patch.level,
                kind=current.kind if patch.kind is None else patch.kind,
                valid_to=current.valid_to if patch.valid_to is None else patch.valid_to,
                confidence=current.confidence if patch.confidence is None else patch.confidence,
                superseded_by=current.superseded_by if patch.superseded_by is None else patch.superseded_by,
                sources=current.sources + patch.add_sources,
                supersedes=_union(current.supersedes, patch.add_supersedes),
                contradicts=_union(current.contradicts, patch.add_contradicts),
                revision=current.revision + 1,
                updated_at=now,
            )
            try:
                check_level_retention(revised.level, revised.retention)
            except ValueError as exc:
                if patch.level is not None:
                    raise  # the caller asked for a level the class refuses
                raise MemoryStoreError(
                    MemoryErrorCode.UNAVAILABLE,
                    f"note {current.id} breaks the level x retention matrix ({exc}); "
                    "fix its level or move it to an allowed class by hand, or revise it with an allowed `level`",
                ) from exc
            extra = {k: v for k, v in loaded.parsed.meta.items() if k not in _KNOWN_KEYS}
            text = self._render(revised, extra)
            path = self._internal_path(loaded.rel)
            self._assert_plain_chain(path)
            history_dir = self._plain_dir(HISTORY_DIR)
            history_path = history_dir / f"{current.id}.rev{current.revision}.md"
            history_existed = history_path.exists()
            tmp = history_tmp = None
            try:
                tmp = self._stage(path.parent, text)
                history_tmp = self._stage(history_dir, loaded.text)
                self._commit(history_tmp, history_path)
                history_tmp = None
                self._commit(tmp, path)
                tmp = None
            except (OSError, UnicodeEncodeError) as exc:
                # The current file is only ever replaced by a complete temp
                # file, so a failure here leaves the old revision untouched.
                if not history_existed:
                    history_path.unlink(missing_ok=True)
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"revision not written: {exc}") from exc
            finally:
                for leftover in (tmp, history_tmp):
                    if leftover is not None:
                        leftover.unlink(missing_ok=True)
            stat = path.stat()
            stored = self._loaded_from_text(loaded.rel, text, stat.st_mtime)
            self._index_after_write(self._doc_from_loaded(stored, stat.st_mtime))
        return stored.note

    def history(self, memory_id: str) -> tuple[MemoryNote, ...]:
        """Every revision, oldest first, the current one last."""

        loaded = self._find(memory_id)
        current = loaded.note
        found: dict[int, MemoryNote] = {}
        history_dir = self.root / HISTORY_DIR
        if history_dir.is_dir() and not history_dir.is_symlink():
            # fullmatch: ids `aaa` and `aaa.rev1` must not read each other's files.
            pattern = re.compile(re.escape(current.id) + _REVISION_SUFFIX)
            for path in history_dir.glob(f"{current.id}.rev*.md"):
                number = pattern.fullmatch(path.name)
                if number is None or path.is_symlink() or not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                old = self._loaded_from_text(loaded.rel, text, path.stat().st_mtime, fallback_id=current.id)
                if old.note is not None and int(number.group(1)) != current.revision:
                    found[int(number.group(1))] = replace(old.note, revision=int(number.group(1)))
        return (*(found[number] for number in sorted(found)), current)

    def rebuild_indexes(self) -> int:
        """Rebuild every derived index from the canonical files; returns notes indexed."""

        self._wait_ready()
        return self._rebuild_index_sync()

    # ------------------------------------------------- ranked search, promotion
    def search_ranked(
        self, query: str, limit: int = 20, filters: MemoryFilters | None = None,
    ) -> list[RankedMemoryHit]:
        """BM25-ranked hits over canonical notes, best first, with no 10-item cap.

        Front matter is not indexed. `filters` (scope, retention, level, kind,
        superseded) narrow the result; `limit` and `offset` of the filters are
        ignored, `limit` is the argument (at most `MAX_RANKED_LIMIT`).
        """

        limit = max(1, min(int(limit), MAX_RANKED_LIMIT))
        tokens = self._tokens(query)
        if not tokens:
            return []
        self._wait_ready()
        where, params = self._filter_sql(filters or MemoryFilters(), prefix=" AND ")

        def query_index() -> list[sqlite3.Row]:
            with self._lock, self._connection() as conn:
                if self._fts:
                    return conn.execute(
                        "SELECT memory_fts.memory_id AS path, memory_fts.title AS title, "
                        "snippet(memory_fts,2,'','', ' ... ',18) AS snippet, bm25(memory_fts) AS score, m.* "
                        "FROM memory_fts JOIN memory_meta m ON m.path = memory_fts.memory_id "
                        f"WHERE memory_fts MATCH ?{where} ORDER BY score LIMIT ?",
                        [self._fts_match(tokens), *params, limit],
                    ).fetchall()
                clauses = " OR ".join("lower(d.title || ' ' || d.body) LIKE ?" for _ in tokens[:12])
                return conn.execute(
                    "SELECT d.memory_id AS path, d.title AS title, substr(d.body,1,280) AS snippet, 0.0 AS score, m.* "
                    f"FROM memory_docs d JOIN memory_meta m ON m.path = d.memory_id WHERE ({clauses}){where} "
                    "ORDER BY m.updated_at DESC LIMIT ?",
                    [*(f"%{t.lower()}%" for t in tokens[:12]), *params, limit],
                ).fetchall()

        return [
            RankedMemoryHit(
                memory_id=row["id"], path=row["path"], title=row["title"], snippet=row["snippet"] or "",
                score=float(-row["score"]) if self._fts else 0.0,
                retention=RetentionClass(row["retention"]), level=MemoryLevel(row["level"]),
                kind=MemoryKind(row["kind"]), scope=row["scope"], revision=row["revision"],
                updated_at=_utc(row["updated_at"]), valid_from=_utc(row["valid_from"]),
                valid_to=_utc(row["valid_to"]),
            )
            for row in self._indexed(query_index)
        ]

    def promote_file(self, source_rel: str, target: RetentionClass) -> MemoryNote | None:
        """Copy a note into another retention class, with provenance; the source stays.

        The copy is a new note (new id) that keeps the file name, so a second
        call is a no-op (`None`). Its sources end with `{note, <source id>, now}`;
        a source without a stored id is cited by its relative path. The level
        drops to the lowest one the target class allows when needed (L0 -> L1).
        """

        self._wait_ready()
        with self._lock:
            source = self._read_loaded(source_rel)
            if source is None or source.note is None:
                raise FileNotFoundError(source_rel)
            name = Path(source.rel).name
            if (self._plain_dir(target.value) / name).exists():
                return None
            now = datetime.now(timezone.utc)
            origin = source.rel if source.derived else source.note.id
            level = source.note.level if is_level_allowed(source.note.level, target) else MemoryLevel.L1
            note = replace(
                source.note, id=new_memory_id(), retention=target, level=level, revision=1,
                created_at=now, updated_at=now, supersedes=(), superseded_by=None, contradicts=(),
                sources=(*source.note.sources[-(MAX_SOURCES - 1):], Provenance(SourceType.NOTE, origin, now)),
            )
            return self.create(note, filename=name)

    # ------------------------------------------------------------- index core
    def _initial_sync(self) -> None:
        try:
            self._rebuild_index_sync()
        except Exception as exc:  # noqa: BLE001 - thread boundary: nothing may end the sync silently
            # Derived state only: say so and carry on; the next read heals it.
            _LOG.warning("memory start-up index sync failed: %s: %s", type(exc).__name__, exc)
        finally:
            self._ready.set()

    @property
    def index_ready(self) -> bool:
        """True once the start-up index sync has ended (a recall that must not wait asks first; Slice 05)."""

        return self._ready.is_set()

    def _wait_ready(self) -> None:
        if not self._ready.wait(_READY_TIMEOUT_S):
            _LOG.warning("memory start-up index sync still running after %ss", _READY_TIMEOUT_S)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> bool:
        with self._lock, self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jarvis_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_meta (path TEXT PRIMARY KEY, id TEXT NOT NULL, "
                "retention TEXT NOT NULL, level TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL, "
                "revision INTEGER NOT NULL, updated_at REAL NOT NULL, superseded INTEGER NOT NULL, "
                "valid_from REAL, valid_to REAL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS memory_meta_id ON memory_meta(id)")
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
                    "memory_id UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2')"
                )
                conn.execute("INSERT OR REPLACE INTO jarvis_meta(key,value) VALUES('index_kind','fts5')")
                return True
            except sqlite3.OperationalError:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS memory_docs ("
                    "memory_id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL)"
                )
                conn.execute("INSERT OR REPLACE INTO jarvis_meta(key,value) VALUES('index_kind','plain')")
                return False

    def _heal_index(self) -> None:
        """The index is derived: recreate it (and drop it if corrupt), then refill from Markdown."""

        with self._lock:
            try:
                self._fts = self._ensure_schema()
            except sqlite3.DatabaseError:
                self.db_path.unlink(missing_ok=True)
                self._fts = self._ensure_schema()
            self._rebuild_index_sync()

    def _indexed(self, query):
        """Run an index query; on a damaged or missing index heal it once and retry."""

        try:
            return query()
        except sqlite3.DatabaseError:
            try:
                self._heal_index()
                return query()
            except Exception as exc:  # noqa: BLE001 - one bad file or disk fault must not become a raw crash
                _LOG.warning("memory index heal failed: %s: %s", type(exc).__name__, exc)
                raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "derived index unavailable") from exc

    def _iter_note_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for path in sorted(self.root.rglob("*.md")):
            relative = path.relative_to(self.root)
            if any(part.startswith((".", "_")) for part in relative.parts[:-1]) or path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            if self.root != resolved and self.root not in resolved.parents:
                continue
            # Junction aliases and loops reach one file by several paths: index it once.
            key = os.path.normcase(str(resolved))
            if key in seen:
                continue
            seen.add(key)
            paths.append(resolved)
        return paths

    def _iter_docs(self) -> list[_IndexedDoc]:
        docs: list[_IndexedDoc] = []
        for resolved in self._iter_note_paths():
            try:
                text = resolved.read_text(encoding="utf-8")
                mtime = resolved.stat().st_mtime
            except (OSError, UnicodeDecodeError):
                continue
            try:
                docs.append(self._doc_from_loaded(self._loaded_from_text(self._rel(resolved), text, mtime), mtime))
            except Exception as exc:  # noqa: BLE001 - one hostile file must never disable recall for the vault
                _LOG.warning("memory note skipped by the index: %s: %s: %s", self._rel(resolved), type(exc).__name__, exc)
        return docs

    def _rebuild_index_sync(self) -> int:
        # Files are read under the store lock: a write that lands during the
        # rebuild cannot be overwritten by an older snapshot.
        with self._lock:
            docs = self._iter_docs()
            with self._connection() as conn:
                conn.execute("DELETE FROM memory_meta")
                if self._fts:
                    conn.execute("DELETE FROM memory_fts")
                    conn.executemany(
                        "INSERT INTO memory_fts(memory_id,title,body) VALUES(?,?,?)",
                        [(d.memory_id, d.title, d.body) for d in docs],
                    )
                else:
                    conn.execute("DELETE FROM memory_docs")
                    conn.executemany(
                        "INSERT INTO memory_docs(memory_id,title,body) VALUES(?,?,?)",
                        [(d.memory_id, d.title, d.body) for d in docs],
                    )
                for doc in docs:
                    self._insert_meta(conn, doc)
                conn.execute(
                    "INSERT OR REPLACE INTO jarvis_meta(key,value) VALUES('last_rebuild_count',?)",
                    (str(len(docs)),),
                )
        return len(docs)

    @staticmethod
    def _insert_meta(conn: sqlite3.Connection, doc: _IndexedDoc) -> None:
        meta = doc.meta
        if meta is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO memory_meta(path,id,retention,level,kind,scope,revision,updated_at,"
            "superseded,valid_from,valid_to) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (doc.memory_id, meta.note_id, meta.retention, meta.level, meta.kind, meta.scope, meta.revision,
             meta.updated_at, int(meta.superseded), meta.valid_from, meta.valid_to),
        )

    def _upsert_doc(self, doc: _IndexedDoc) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM memory_meta WHERE path=?", (doc.memory_id,))
            if self._fts:
                conn.execute("DELETE FROM memory_fts WHERE memory_id=?", (doc.memory_id,))
                conn.execute(
                    "INSERT INTO memory_fts(memory_id,title,body) VALUES(?,?,?)",
                    (doc.memory_id, doc.title, doc.body),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO memory_docs(memory_id,title,body) VALUES(?,?,?)",
                    (doc.memory_id, doc.title, doc.body),
                )
            self._insert_meta(conn, doc)

    def _index_after_write(self, doc: _IndexedDoc) -> None:
        """Upsert the written note (R3: every mutation reaches the index)."""

        try:
            self._upsert_doc(doc)
        except sqlite3.Error:
            # The canonical Markdown write is already committed. Repair the
            # disposable index best-effort, but never report the durable write
            # as failed merely because derived state is unavailable. A later
            # read or process start will resync from Markdown.
            try:
                self._rebuild_index_sync()
            except sqlite3.Error as exc:
                _LOG.warning("memory index repair failed after a write: %s", exc)

    def _filter_sql(self, filters: MemoryFilters, *, prefix: str = " WHERE ") -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, values in (
            ("m.scope", filters.scopes),
            ("m.retention", tuple(item.value for item in filters.retentions)),
            ("m.level", tuple(item.value for item in filters.levels)),
            ("m.kind", tuple(item.value for item in filters.kinds)),
        ):
            if values:
                clauses.append(f"{column} IN ({','.join('?' * len(values))})")
                params.extend(values)
        if not filters.include_superseded:
            clauses.append("m.superseded = 0")
        return (prefix + " AND ".join(clauses) if clauses else ""), params

    def _known_id(self, memory_id: str) -> bool:
        try:
            return self._indexed_path(memory_id) is not None
        except MemoryStoreError:
            return False

    def _indexed_path(self, memory_id: str) -> str | None:
        def query() -> str | None:
            with self._lock, self._connection() as conn:
                row = conn.execute(
                    "SELECT path FROM memory_meta WHERE id=? ORDER BY revision DESC, updated_at DESC LIMIT 1",
                    (memory_id,),
                ).fetchone()
            return row["path"] if row else None

        return self._indexed(query)

    # ------------------------------------------------------------ legacy read
    @staticmethod
    def _tokens(query: str) -> list[str]:
        tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        return [t for t in tokens if t.strip()]

    @staticmethod
    def _fts_match(tokens: list[str]) -> str:
        return " OR ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in tokens[:12])

    def _search_sync(self, query: str, limit: int) -> list[MemoryHit]:
        limit = max(1, min(int(limit), 10))
        tokens = self._tokens(query)
        if not tokens:
            return []
        self._wait_ready()

        def query() -> list[MemoryHit]:
            with self._lock, self._connection() as conn:
                if self._fts:
                    rows = conn.execute(
                        "SELECT memory_id,title,snippet(memory_fts,2,'','', ' ... ',18) AS snippet, "
                        "bm25(memory_fts) AS rank FROM memory_fts WHERE memory_fts MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (self._fts_match(tokens), limit),
                    ).fetchall()
                    return [
                        MemoryHit(r["memory_id"], r["title"], r["snippet"] or "", float(-r["rank"]))
                        for r in rows
                    ]
                clauses = " OR ".join("lower(title || ' ' || body) LIKE ?" for _ in tokens[:12])
                params = [f"%{t.lower()}%" for t in tokens[:12]] + [limit]
                rows = conn.execute(
                    f"SELECT memory_id,title,substr(body,1,280) AS snippet FROM memory_docs WHERE {clauses} LIMIT ?",
                    params,
                ).fetchall()
                return [MemoryHit(r["memory_id"], r["title"], r["snippet"] or "", 0.0) for r in rows]

        return self._indexed(query)

    def _read_sync(self, memory_id: str) -> MemoryRecord:
        path = self._resolve_memory_id(memory_id)
        if not path.is_file() or path.suffix.lower() != ".md":
            raise FileNotFoundError(memory_id)
        text = path.read_text(encoding="utf-8")
        parsed = memory_frontmatter.parse(text)
        # The metadata block is not part of what a reader sees.
        text = parsed.body if parsed.has_block else text
        return MemoryRecord(path.relative_to(self.root).as_posix(), self._title_from_text(text, path.stem), text)

    def _append_note_sync(self, title: str, body: str) -> MemoryRecord:
        title = title.strip()
        body = body.strip()
        if not title or not body:
            raise ValueError("title/body cannot be empty")
        notes_dir = self._plain_dir(NEW_WRITE_RETENTION.value)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        slug = self._slug(title)[:60] or "note"
        name = f"{stamp}-{slug}-{uuid.uuid4().hex[:8]}.md"
        target = (notes_dir / name).resolve()
        if self.root not in target.parents:
            raise MemorySecurityError("target escaped memory root")
        content = f"# {title}\n\n{body}\n"
        with self._lock:
            self._commit(self._stage(notes_dir, content), target)
            loaded = self._loaded_from_text(self._rel(target), content, target.stat().st_mtime)
            self._index_after_write(self._doc_from_loaded(loaded, target.stat().st_mtime))
        return MemoryRecord(loaded.rel, title, content)

    # ------------------------------------------------------- note <-> file
    def _find(self, memory_id: str) -> _Loaded:
        """The latest revision of `memory_id`; the index is healed once if it is stale."""

        if not isinstance(memory_id, str) or not _ID.fullmatch(memory_id):
            raise MemorySecurityError("memory id is not a token")
        self._wait_ready()
        for attempt in (0, 1):
            rel = self._indexed_path(memory_id)
            if rel is None:
                break
            loaded = self._read_loaded(rel) if rel else None
            if loaded is not None and loaded.note is not None and loaded.note.id == memory_id:
                return loaded
            if attempt == 0 and rel is not None:
                # The index points at a file that moved or changed: refill it once.
                try:
                    self._heal_index()
                except Exception as exc:  # noqa: BLE001 - a failed heal is a coded error, never a raw crash
                    raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, "derived index unavailable") from exc
        raise MemoryStoreError(MemoryErrorCode.NOT_FOUND, f"no note {memory_id}")

    def _read_loaded(self, rel: str) -> _Loaded | None:
        path = self._internal_path(rel)
        if path.is_symlink() or not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            mtime = path.stat().st_mtime
        except (OSError, UnicodeDecodeError):
            return None
        return self._loaded_from_text(rel, text, mtime)

    def _loaded_from_text(self, rel: str, text: str, mtime: float, *, fallback_id: str | None = None) -> _Loaded:
        parsed = memory_frontmatter.parse(text)
        stem = Path(rel).stem
        title, body = self._split_title(parsed.body.replace("\r\n", "\n"), stem)
        retention = self._retention_of(rel)
        stamp = datetime.fromtimestamp(mtime, timezone.utc)
        default_id = fallback_id or legacy_note_id(rel)
        note, derived = None, True
        if parsed.has_block and parsed.meta:
            try:
                note, derived = self._note_from_meta(parsed.meta, retention, title, body, default_id, stamp), False
            except (ValueError, TypeError, KeyError):
                stored = parsed.meta.get("id")
                default_id = stored if isinstance(stored, str) and _ID.fullmatch(stored) else default_id
        if note is None:
            try:
                note = MemoryNote(
                    id=default_id, title=title, body=body, level=MemoryLevel.L1, kind=MemoryKind.FACT,
                    retention=retention, scope="private", created_at=stamp, updated_at=stamp,
                )
            except (ValueError, TypeError):
                note = None  # not representable (oversized body...): still indexed, never listed
        return _Loaded(rel, text, parsed, title, body, note, derived)

    @staticmethod
    def _note_from_meta(
        meta: Mapping[str, Any], retention: RetentionClass, title: str, body: str, default_id: str,
        stamp: datetime,
    ) -> MemoryNote:
        def moment(value: Any) -> datetime:
            if not isinstance(value, str):
                raise TypeError("a date is an ISO string")
            return datetime.fromisoformat(value)

        def optional(name: str) -> datetime | None:
            return moment(meta[name]) if meta.get(name) is not None else None

        # A hand-written block may omit dates: the file's mtime stands in.
        created = moment(meta["created_at"]) if "created_at" in meta else stamp
        sources = tuple(
            Provenance(SourceType(item["type"]), item["ref"], moment(item["at"])) for item in meta.get("sources", ())
        )
        return MemoryNote(
            id=meta.get("id", default_id), title=title, body=body,
            level=MemoryLevel(meta.get("level", MemoryLevel.L1.value)),
            kind=MemoryKind(meta.get("kind", MemoryKind.FACT.value)),
            retention=retention, scope=meta.get("scope", "private"),
            created_at=created, updated_at=moment(meta["updated_at"]) if "updated_at" in meta else created,
            revision=meta.get("revision", 1), agent=meta.get("agent"),
            valid_from=optional("valid_from"), valid_to=optional("valid_to"),
            confidence=meta.get("confidence", 1.0), sources=sources,
            supersedes=tuple(meta.get("supersedes", ())), superseded_by=meta.get("superseded_by"),
            contradicts=tuple(meta.get("contradicts", ())),
        )

    @staticmethod
    def _render(note: MemoryNote, extra: Mapping[str, Any]) -> str:
        meta: dict[str, Any] = {
            "id": note.id, "level": note.level.value, "kind": note.kind.value, "scope": note.scope,
            "created_at": note.created_at.isoformat(), "updated_at": note.updated_at.isoformat(),
            "revision": note.revision, "confidence": note.confidence,
        }
        if note.agent is not None:
            meta["agent"] = note.agent
        if note.valid_from is not None:
            meta["valid_from"] = note.valid_from.isoformat()
        if note.valid_to is not None:
            meta["valid_to"] = note.valid_to.isoformat()
        if note.sources:
            meta["sources"] = [{"type": s.type.value, "ref": s.ref, "at": s.at.isoformat()} for s in note.sources]
        if note.supersedes:
            meta["supersedes"] = list(note.supersedes)
        if note.superseded_by is not None:
            meta["superseded_by"] = note.superseded_by
        if note.contradicts:
            meta["contradicts"] = list(note.contradicts)
        meta.update(extra)
        body = note.body.strip("\n")
        return memory_frontmatter.compose(meta, f"# {note.title.strip()}\n" + (f"\n{body}\n" if body else ""))

    def _doc_from_loaded(self, loaded: _Loaded, mtime: float) -> _IndexedDoc:
        note = loaded.note
        meta = None
        if note is not None:
            meta = _Meta(
                note.id, note.retention.value, note.level.value, note.kind.value, note.scope, note.revision,
                note.updated_at.timestamp(), note.is_superseded, _ts(note.valid_from), _ts(note.valid_to),
            )
        # Front matter is metadata, not content: only the text after it is indexed.
        body = loaded.parsed.body if loaded.parsed.has_block else loaded.text
        return _IndexedDoc(loaded.rel, loaded.title, body, meta)

    def _split_title(self, text: str, fallback: str) -> tuple[str, str]:
        title = self._title_from_text(text, fallback)
        title = "".join(ch for ch in title if ch.isprintable())[:200].strip() or fallback[:200] or "note"
        lines = text.split("\n")
        first = next((i for i, line in enumerate(lines) if line.strip()), None)
        if first is not None and lines[first].startswith("# ") and lines[first][2:].strip():
            lines = lines[first + 1:]
        return title, "\n".join(lines).strip("\n")

    def _retention_of(self, rel: str) -> RetentionClass:
        head = rel.split("/", 1)[0]
        return RetentionClass(head) if head in _RETENTION_DIRS else LEGACY_NOTES_RETENTION

    # ------------------------------------------------------------- file system
    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _internal_path(self, rel: str) -> Path:
        """Absolute path of a stored relative path, refused if it leaves the root."""

        candidate = (self.root / rel).resolve(strict=False)
        if candidate != self.root and self.root not in candidate.parents:
            raise MemorySecurityError("memory path escaped root")
        return candidate

    def _assert_plain_chain(self, path: Path) -> None:
        """Refuse a path with a symlink or junction anywhere in its chain."""

        expected = os.path.normcase(os.path.abspath(path))
        if os.path.normcase(os.path.realpath(path)) != expected:
            raise MemorySecurityError("memory path crosses a link")

    def _plain_dir(self, name: str) -> Path:
        """`<root>/<name>`, created if needed, refused when it is (or sits behind) a link."""

        directory = self.root / name
        self._assert_plain_chain(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._assert_plain_chain(directory)
        return directory

    @staticmethod
    def _safe_filename(name: str) -> str:
        if name != Path(name).name or name in {"", ".", ".."} or "\\" in name:
            raise MemorySecurityError("memory file name must be a plain name")
        if not name.lower().endswith(".md") or name.startswith((".", "_")):
            raise ValueError("a memory file is a visible .md file")
        return name

    def _new_name(self, title: str, note_id: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"{stamp}-{(self._slug(title)[:60] or 'note')}-{note_id[:8]}.md"

    @staticmethod
    def _stage(directory: Path, text: str) -> Path:
        """Write `text` to a complete, fsynced temp file next to its destination."""

        fd, tmp_name = tempfile.mkstemp(prefix=".jarvis-note-", suffix=".tmp", dir=str(directory))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return tmp

    @staticmethod
    def _commit(tmp: Path, target: Path) -> None:
        """Atomic replace, patient with Windows' short file locks. The temp file is removed on failure."""

        try:
            replace_with_retry(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _commit_new(tmp: Path, target: Path) -> None:
        """Like `_commit`, but never overwrites: the name is claimed with O_EXCL first.

        A file that appears between the caller's `exists()` check and the
        replace (another process) raises `FileExistsError` and is left alone.
        """

        try:
            os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        try:
            replace_with_retry(tmp, target)
        except BaseException:
            target.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
            raise

    def _resolve_memory_id(self, memory_id: str) -> Path:
        decoded = str(memory_id)
        for _ in range(3):
            newer = urllib.parse.unquote(decoded)
            if newer == decoded:
                break
            decoded = newer
        rel = Path(decoded)
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            raise MemorySecurityError("memory path traversal denied")
        candidate = (self.root / rel).resolve(strict=False)
        if candidate != self.root and self.root not in candidate.parents:
            raise MemorySecurityError("memory path escaped root")
        return candidate

    @staticmethod
    def _title_from_text(text: str, fallback: str) -> str:
        for line in text.splitlines():
            if line.startswith("# ") and line[2:].strip():
                return line[2:].strip()
        return fallback

    @staticmethod
    def _slug(value: str) -> str:
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
        value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
        return value


def _union(current: tuple[str, ...], added: tuple[str, ...]) -> tuple[str, ...]:
    return (*current, *(item for item in added if item not in current))
