"""Wiki knowledge assets: Markdown pages imported by copy (Slice 07).

Root `<data_root>/knowledge/wiki`. Canonical here means the imported copy, one
atomic JSON file per page under `pages/` (metadata plus body). The FTS5 index
under `index/` is a separate derived sqlite file: delete it and the next search
(or `rebuild()`) restores it from the pages, nothing is lost.

Import reads local files from an allowlist of roots only (default: the repo
`docs/` tree). A URL is recorded as `source_uri`, never fetched. Staleness
compares the stored source hash with the source as it is now (mtime is not
trusted). Contract: `docs/knowledge-assets.md`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from urllib.parse import urlsplit

from jarvis.domain.errors import MemorySecurityError
from jarvis.domain.knowledge import (
    MAX_ASSET_SUMMARY_CHARS,
    AssetHit,
    AssetKind,
    AssetScope,
    KnowledgeAsset,
    SourceRef,
)
from jarvis.domain.memory import (
    MAX_BODY_CHARS,
    MAX_RECALL_ITEMS,
    MAX_SNIPPET_CHARS,
    CapabilityState,
    CapabilityStatus,
    MemoryErrorCode,
    MemoryStoreError,
    capability_ok,
)

#: Largest source file read (bytes); a UTF-8 body of `MAX_BODY_CHARS` fits.
MAX_SOURCE_BYTES = 4 * MAX_BODY_CHARS
SOURCE_SUFFIX = ".md"
DEFAULT_ALLOWED_ROOT = Path(__file__).resolve().parents[2] / "docs"

_PAGE_PREFIX = "page-"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SLUG = re.compile(r"[^A-Za-z0-9]+")
_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)
_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class ImportReport:
    """Result of a tree import: assets written, and files skipped with the reason."""

    imported: tuple[KnowledgeAsset, ...]
    skipped: tuple[tuple[str, str], ...]


def _unavailable(message: str) -> MemoryStoreError:
    return MemoryStoreError(MemoryErrorCode.UNAVAILABLE, message)


def _not_found(asset_id: object) -> MemoryStoreError:
    return MemoryStoreError(MemoryErrorCode.NOT_FOUND, f"unknown wiki asset {str(asset_id)[:80]!r}")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _title_and_summary(text: str, fallback: str) -> tuple[str, str]:
    title = ""
    summary = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            title = title or stripped[2:].strip()
        elif not stripped.startswith(("#", "```", "---", "|")) and not summary:
            summary = stripped
        if title and summary:
            break
    return (title or fallback)[:200], summary[:300].strip()[:MAX_ASSET_SUMMARY_CHARS]


class WikiProvider:
    """`KnowledgeAssetProvider` for Wiki pages, plus the import/update/delete lifecycle."""

    kind = AssetKind.WIKI

    def __init__(
        self,
        root: Path,
        allowed_roots: Iterable[Path] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        roots = (DEFAULT_ALLOWED_ROOT,) if allowed_roots is None else tuple(allowed_roots)
        self.allowed_roots = tuple(Path(r).expanduser().resolve() for r in roots)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._pages = self.root / "pages"
        self._db = self.root / "index" / "wiki-index.sqlite3"
        self._lock = threading.RLock()
        try:
            self._pages.mkdir(parents=True, exist_ok=True)
            self._db.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _unavailable(f"wiki root unusable: {exc.__class__.__name__}") from exc

    # ------------------------------------------------------------------ port

    def status(self) -> CapabilityState:
        try:
            _, corrupt = self._load_pages()
            self._query("SELECT count(*) FROM wiki_fts", [])
        except (MemoryStoreError, OSError) as exc:
            return CapabilityState(CapabilityStatus.UNAVAILABLE, "wiki_unavailable", str(exc)[:200])
        if corrupt:
            return CapabilityState(CapabilityStatus.DEGRADED, "wiki_corrupt_pages", f"{corrupt} page file(s) unreadable")
        return capability_ok()

    def list(self, scope: AssetScope | None = None) -> tuple[KnowledgeAsset, ...]:
        pages, _ = self._load_pages()
        found = [self._asset(p, with_body=False) for p in pages if scope is None or p["scope"] == scope.value]
        return tuple(sorted(found, key=lambda a: (a.title.lower(), a.asset_id)))

    def search(self, query: str, limit: int, scope: AssetScope | None = None) -> Sequence[AssetHit]:
        limit = max(1, min(int(limit), MAX_RECALL_ITEMS))
        tokens = _TOKENS.findall(query)[:12]
        if not tokens:
            return []
        match = " OR ".join(f'"{t}"' for t in tokens)
        sql = (
            "SELECT asset_id, snippet(wiki_fts, 3, '', '', ' ... ', 18) AS snip, bm25(wiki_fts) AS rank "
            "FROM wiki_fts WHERE wiki_fts MATCH ?"
        )
        params: list[object] = [match]
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope.value)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self._query(sql, params)
        hits: list[AssetHit] = []
        for asset_id, snip, rank in rows:
            page = self._page_or_none(asset_id)
            # A hit that does not resolve to a page, or whose page scope differs
            # from the requested one, is dropped: the pages are the truth.
            if page is None or (scope is not None and page["scope"] != scope.value):
                continue
            hits.append(AssetHit(self._asset(page, with_body=False), (snip or "")[:MAX_SNIPPET_CHARS], float(-rank)))
        return hits

    def read(self, asset_id: str, scope: AssetScope | None = None) -> KnowledgeAsset:
        """The page with its body. A `scope` that differs from the page's is denied."""

        page = self._page_or_none(asset_id)
        if page is None:
            raise _not_found(asset_id)
        if scope is not None and page["scope"] != scope.value:
            raise MemoryStoreError(MemoryErrorCode.SCOPE_DENIED, "wiki asset is outside the requested scope")
        return self._asset(page, with_body=True)

    def rebuild(self) -> int:
        pages, _ = self._load_pages()
        rows = [(p["asset_id"], p["scope"], p["title"], p["body"]) for p in pages]
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._ensure_schema()
                    with self._connection() as conn:
                        conn.execute("DELETE FROM wiki_fts")
                        conn.executemany("INSERT INTO wiki_fts(asset_id, scope, title, body) VALUES(?,?,?,?)", rows)
                    return len(rows)
                except sqlite3.DatabaseError as exc:
                    if attempt == 2:
                        raise _unavailable(f"wiki index rebuild failed: {exc.__class__.__name__}") from exc
                    self._drop_index()  # corrupt derived file: start over from the pages
                except sqlite3.Error as exc:
                    raise _unavailable(f"wiki index rebuild failed: {exc.__class__.__name__}") from exc
        return len(rows)

    # ------------------------------------------------------------- lifecycle

    def import_file(
        self,
        path: Path | str,
        scope: AssetScope = AssetScope.PROJECT,
        asset_id: str | None = None,
        title: str | None = None,
    ) -> KnowledgeAsset:
        """Copy an allowlisted Markdown file in. Re-importing updates in place.

        The version only moves when the source hash changed. Raises
        `MemorySecurityError` outside the allowlist or through a link, and
        `ValueError` for an unreadable, oversized or non-UTF-8 source.
        """

        source, relative = self._safe_source(path)
        data = self._read_source(source)
        text = data.decode("utf-8")
        auto_title, summary = _title_and_summary(text, source.stem)
        uri = source.as_uri()
        return self._upsert(
            asset_id or self._derive_id(source.stem, uri),
            title or auto_title, scope, summary, text, _sha256(data),
            source_uri=uri, source_path=relative, source_file=str(source),
        )

    def import_tree(self, directory: Path | str, scope: AssetScope = AssetScope.PROJECT) -> ImportReport:
        """Import every `.md` under an allowlisted directory; links are never followed."""

        base, _ = self._safe_source(directory, directory=True)
        imported: list[KnowledgeAsset] = []
        skipped: list[tuple[str, str]] = []
        for current, dirs, files in os.walk(base, followlinks=False):
            here = Path(current)
            dirs[:] = sorted(d for d in dirs if not _is_link(here / d))
            for name in sorted(files):
                candidate = here / name
                if candidate.suffix.lower() != SOURCE_SUFFIX:
                    continue
                try:
                    imported.append(self.import_file(candidate, scope))
                except (MemorySecurityError, ValueError, OSError) as exc:
                    skipped.append((str(candidate), str(exc)[:160]))
        return ImportReport(tuple(imported), tuple(skipped))

    def import_text(
        self,
        uri: str,
        title: str,
        body: str,
        scope: AssetScope = AssetScope.PROJECT,
        asset_id: str | None = None,
    ) -> KnowledgeAsset:
        """Record a page whose text the caller already holds. `uri` (http/https) is only
        stored as `source_uri`; nothing is ever fetched. Never stale (no way to know)."""

        parts = urlsplit(uri)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("uri must be an http(s) URL; local files go through import_file")
        _, summary = _title_and_summary(body, title)
        return self._upsert(
            asset_id or self._derive_id(title, uri),
            title, scope, summary, body, _sha256(body.encode("utf-8")),
            source_uri=uri, source_path=None, source_file=None,
        )

    def refresh(self, asset_id: str) -> KnowledgeAsset:
        """Re-import a file-backed page from its source (the update path)."""

        page = self._page_or_none(asset_id)
        if page is None:
            raise _not_found(asset_id)
        if not page.get("source_file"):
            raise ValueError("a URL page has no local source to refresh")
        return self.import_file(page["source_file"], AssetScope(page["scope"]), asset_id, page["title"])

    def delete(self, asset_id: str) -> None:
        if self._page_or_none(asset_id) is None:
            raise _not_found(asset_id)
        with self._lock:
            self._ensure_index()
            self._page_path(asset_id).unlink(missing_ok=True)
            try:
                with self._connection() as conn:
                    conn.execute("DELETE FROM wiki_fts WHERE asset_id = ?", (asset_id,))
            except sqlite3.Error:
                self._drop_index()

    # -------------------------------------------------------------- internals

    def _derive_id(self, name: str, uri: str) -> str:
        slug = _SLUG.sub("-", name).strip("-").lower()[:100] or "page"
        return f"{slug}-{_sha256(uri.encode('utf-8'))[:8]}"

    def _upsert(
        self, asset_id: str, title: str, scope: AssetScope, summary: str, body: str, source_hash: str,
        *, source_uri: str, source_path: str | None, source_file: str | None,
    ) -> KnowledgeAsset:
        if not _ID.fullmatch(asset_id):
            raise ValueError("asset_id must be a short token (letters, digits, '_', '.', '-')")
        scope = AssetScope(scope)
        page = {
            "schema": _SCHEMA, "asset_id": asset_id, "title": title, "scope": scope.value,
            "summary": summary, "body": body, "source_uri": source_uri, "source_path": source_path,
            "source_file": source_file, "source_hash": source_hash, "version": 1,
            "fetched_at": self._clock().isoformat(),
        }
        with self._lock:
            self._ensure_index()
            old = self._page_or_none(asset_id)
            if old is not None:
                if old["source_hash"] == source_hash:
                    # Same content: keep version and fetch date, apply only a changed title or scope.
                    page["version"], page["fetched_at"] = old["version"], old["fetched_at"]
                else:
                    page["version"] = old["version"] + 1
            asset = self._asset(page, with_body=True)  # validates the domain bounds before writing
            self._write_page(asset_id, page)
            try:
                with self._connection() as conn:
                    conn.execute("DELETE FROM wiki_fts WHERE asset_id = ?", (asset_id,))
                    conn.execute(
                        "INSERT INTO wiki_fts(asset_id, scope, title, body) VALUES(?,?,?,?)",
                        (asset_id, scope.value, title, body),
                    )
            except sqlite3.Error:
                self._drop_index()  # derived: restored from the pages on next use
        return asset

    def _asset(self, page: dict, *, with_body: bool) -> KnowledgeAsset:
        stale = self._is_stale(page)
        source = SourceRef(
            uri=page["source_uri"],
            version_or_commit=f"sha256:{page['source_hash'][:16]}",
            fetched_at=datetime.fromisoformat(page["fetched_at"]),
            path=page.get("source_path"),
        )
        return KnowledgeAsset(
            asset_id=page["asset_id"], kind=AssetKind.WIKI, title=page["title"],
            scope=AssetScope(page["scope"]), source=source, summary=page["summary"],
            body=page["body"] if with_body else "", version=str(page["version"]), stale=stale,
        )

    def _is_stale(self, page: dict) -> bool:
        source_file = page.get("source_file")
        if not source_file:
            return False
        try:
            source, _ = self._safe_source(source_file)
            return _sha256(self._read_source(source)) != page["source_hash"]
        except (MemorySecurityError, ValueError, OSError):
            # Gone, moved out of the allowlist, or unreadable: the snapshot can no longer be trusted as current.
            return True

    # -- source safety

    def _safe_source(self, path: Path | str, *, directory: bool = False) -> tuple[Path, str]:
        """Absolute path and its path relative to the allowlist root, or `MemorySecurityError`.

        Refused: `..` parts, NUL, a path outside every root, any symlink or junction
        between the root and the target, a resolve that leaves the root.
        """

        raw = os.fspath(path)
        if "\x00" in raw or ".." in Path(raw).parts:
            raise MemorySecurityError("wiki source path traversal denied")
        candidate = Path(os.path.abspath(raw))
        for root in self.allowed_roots:
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            walk = root
            for part in relative.parts:
                walk = walk / part
                if _is_link(walk):
                    raise MemorySecurityError("wiki source goes through a symlink or junction")
            real = candidate.resolve(strict=False)
            if real != root and root not in real.parents:
                raise MemorySecurityError("wiki source escaped the allowlist")
            if directory and not candidate.is_dir():
                raise ValueError("source is not a directory")
            if not directory and candidate.suffix.lower() != SOURCE_SUFFIX:
                raise ValueError(f"only {SOURCE_SUFFIX} sources are imported")
            return candidate, relative.as_posix()
        raise MemorySecurityError("wiki source is outside the allowlist")

    @staticmethod
    def _read_source(source: Path) -> bytes:
        with source.open("rb") as handle:
            data = handle.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds the size limit")
        if len(data.decode("utf-8")) > MAX_BODY_CHARS:
            raise ValueError("source exceeds the body limit")
        return data

    # -- page files

    def _page_path(self, asset_id: str) -> Path:
        return self._pages / f"{_PAGE_PREFIX}{asset_id}.json"

    def _page_or_none(self, asset_id: object) -> dict | None:
        if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
            return None
        try:
            return self._parse_page(self._page_path(str(asset_id)))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def _parse_page(path: Path) -> dict:
        page = json.loads(path.read_text(encoding="utf-8"))
        for key in ("asset_id", "title", "scope", "summary", "body", "source_uri", "source_hash", "fetched_at"):
            if not isinstance(page[key], str):
                raise ValueError(key)
        if type(page["version"]) is not int or page["version"] < 1:
            raise ValueError("version")
        AssetScope(page["scope"])
        return page

    def _load_pages(self) -> tuple[list[dict], int]:
        pages: list[dict] = []
        corrupt = 0
        try:
            names = sorted(self._pages.glob(f"{_PAGE_PREFIX}*.json"))
        except OSError as exc:
            raise _unavailable(f"wiki pages unreadable: {exc.__class__.__name__}") from exc
        for path in names:
            try:
                pages.append(self._parse_page(path))
            except (OSError, ValueError, KeyError, TypeError):
                corrupt += 1
        return pages, corrupt

    def _write_page(self, asset_id: str, page: dict) -> None:
        target = self._page_path(asset_id)
        try:
            fd, tmp = tempfile.mkstemp(prefix=".wiki-", suffix=".tmp", dir=str(self._pages))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(page, handle, ensure_ascii=False, indent=1)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, target)
            finally:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise _unavailable(f"wiki page write failed: {exc.__class__.__name__}") from exc

    # -- derived index

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self._db, timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5("
                "asset_id UNINDEXED, scope UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2')"
            )

    def _drop_index(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self._db}{suffix}").unlink(missing_ok=True)

    def _ensure_index(self) -> None:
        """Fill a missing index from the pages (deleting the file loses nothing)."""

        with self._lock:
            if not self._db.exists():
                self.rebuild()

    def _query(self, sql: str, params: list[object]) -> list[tuple]:
        """Run a read on the index; a corrupt or missing-table index is rebuilt once."""

        with self._lock:
            self._ensure_index()
            for attempt in (1, 2):
                try:
                    with self._connection() as conn:
                        return conn.execute(sql, params).fetchall()
                except sqlite3.DatabaseError as exc:
                    if attempt == 2:
                        raise _unavailable(f"wiki index failed: {exc.__class__.__name__}") from exc
                    self._drop_index()
                    self.rebuild()
                except sqlite3.Error as exc:
                    raise _unavailable(f"wiki index failed: {exc.__class__.__name__}") from exc
        return []
