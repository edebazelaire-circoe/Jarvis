from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unicodedata
import urllib.parse
import uuid

from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.results import MemoryHit, MemoryRecord


@dataclass(frozen=True, slots=True)
class _IndexedDoc:
    memory_id: str
    title: str
    body: str


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
        # Always resync at process start so edits performed directly in the
        # Markdown vault while Jarvis was stopped cannot leave stale search
        # results behind.
        self._rebuild_index_sync()

    async def search(self, query: str, limit: int = 5) -> list[MemoryHit]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    async def read(self, memory_id: str) -> MemoryRecord:
        return await asyncio.to_thread(self._read_sync, memory_id)

    async def append_note(self, title: str, body: str) -> MemoryRecord:
        return await asyncio.to_thread(self._append_note_sync, title, body)

    async def rebuild_index(self) -> int:
        return await asyncio.to_thread(self._rebuild_index_sync)

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

    def _iter_docs(self) -> list[_IndexedDoc]:
        docs: list[_IndexedDoc] = []
        for path in sorted(self.root.rglob("*.md")):
            if self.meta_dir == path or self.meta_dir in path.parents or path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            if self.root != resolved and self.root not in resolved.parents:
                continue
            try:
                text = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            memory_id = resolved.relative_to(self.root).as_posix()
            title = self._title_from_text(text, resolved.stem)
            docs.append(_IndexedDoc(memory_id, title, text))
        return docs

    def _rebuild_index_sync(self) -> int:
        docs = self._iter_docs()
        with self._lock, self._connection() as conn:
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
            conn.execute(
                "INSERT OR REPLACE INTO jarvis_meta(key,value) VALUES('last_rebuild_count',?)",
                (str(len(docs)),),
            )
        return len(docs)

    def _search_sync(self, query: str, limit: int) -> list[MemoryHit]:
        limit = max(1, min(int(limit), 10))
        tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        tokens = [t for t in tokens if t.strip()]
        if not tokens:
            return []
        with self._lock, self._connection() as conn:
            if self._fts:
                match = " OR ".join(f'"{t.replace(chr(34), chr(34)*2)}"' for t in tokens[:12])
                rows = conn.execute(
                    "SELECT memory_id,title,snippet(memory_fts,2,'','', ' ... ',18) AS snippet, "
                    "bm25(memory_fts) AS rank FROM memory_fts WHERE memory_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (match, limit),
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

    def _read_sync(self, memory_id: str) -> MemoryRecord:
        path = self._resolve_memory_id(memory_id)
        if not path.is_file() or path.suffix.lower() != ".md":
            raise FileNotFoundError(memory_id)
        text = path.read_text(encoding="utf-8")
        return MemoryRecord(path.relative_to(self.root).as_posix(), self._title_from_text(text, path.stem), text)

    def _append_note_sync(self, title: str, body: str) -> MemoryRecord:
        title = title.strip()
        body = body.strip()
        if not title or not body:
            raise ValueError("title/body cannot be empty")
        notes_dir = (self.root / "notes").resolve()
        if self.root != notes_dir and self.root not in notes_dir.parents:
            raise MemorySecurityError("notes directory escaped memory root")
        notes_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        slug = self._slug(title)[:60] or "note"
        name = f"{stamp}-{slug}-{uuid.uuid4().hex[:8]}.md"
        target = (notes_dir / name).resolve()
        if self.root not in target.parents:
            raise MemorySecurityError("target escaped memory root")
        content = f"# {title}\n\n{body}\n"
        with self._lock:
            fd, tmp_name = tempfile.mkstemp(prefix=".jarvis-note-", suffix=".tmp", dir=str(notes_dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, target)
            finally:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
            memory_id = target.relative_to(self.root).as_posix()
            try:
                self._upsert_doc(_IndexedDoc(memory_id, title, content))
            except sqlite3.Error:
                # The canonical Markdown write is already committed. Repair
                # the disposable index best-effort, but never report the
                # durable write as failed merely because derived state is
                # unavailable. A later process start will resync from Markdown.
                try:
                    self._rebuild_index_sync()
                except sqlite3.Error:
                    pass
        return MemoryRecord(memory_id, title, content)

    def _upsert_doc(self, doc: _IndexedDoc) -> None:
        with self._connection() as conn:
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
