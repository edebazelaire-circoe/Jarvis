"""CodeGraph knowledge provider (memory handoff, Slice 08). Contract page: `docs/codegraph.md`.

Derived, rebuildable code-structure index. Python files go through stdlib
`ast` (symbols, imports, calls and references by name); other known source
files only get a file node and, for JS/TS and C/C++, an import graph. The graph
is name-based, never type-resolved, and every answer says so
(`confidence: name_match`).

One derived sqlite file per repository, under the provider root
(`<data_root>/knowledge/codegraph`). It is keyed by repo path and records the
`git rev-parse HEAD` it was indexed at. Refresh is incremental by file
sha256. The file is disposable: a corrupt or foreign-version file is dropped and
rebuilt from the repository. Queries never mutate a graph that already exists:
they report `stale` instead.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import posixpath
import re
import sqlite3
import subprocess
import threading
import warnings
from typing import Any

from jarvis.domain.knowledge import AssetHit, AssetKind, AssetScope, KnowledgeAsset, SourceRef
from jarvis.domain.memory import (
    MAX_BODY_CHARS,
    CapabilityState,
    CapabilityStatus,
    MemoryErrorCode,
    MemoryStoreError,
    capability_ok,
    check_int_range,
)

CONFIDENCE = "name_match"
SCHEMA_VERSION = 1
MODULE_SCOPE = "<module>"
UNBORN_COMMIT = "UNBORN"

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
DEFAULT_IMPACT_DEPTH = 5
MAX_IMPACT_DEPTH = 20
DEFAULT_IMPACT_NODES = 200
MAX_IMPACT_NODES = 2_000
DEFAULT_PATH_DEPTH = 8
MAX_PATH_DEPTH = 20
PATH_VISIT_CAP = 2_000
MAX_FILE_BYTES = 1_000_000
_GIT_TIMEOUT_S = 60
_IN_CHUNK = 500

_JS_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
_C_SUFFIXES = (".c", ".h", ".cc", ".cpp", ".hpp", ".cxx")
#: Known source files that only get a file node (no symbols, no imports).
_FILE_ONLY_SUFFIXES = (".go", ".rs", ".java", ".kt", ".cs", ".rb", ".php", ".swift", ".sh", ".ps1", ".lua")

_JS_IMPORTS = (
    re.compile(r"""\bimport\s+(?:[^'";]*?\sfrom\s+)?['"]([^'"\n]+)['"]"""),
    re.compile(r"""\bexport\s+[^'";]*?\sfrom\s+['"]([^'"\n]+)['"]"""),
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""),
)
_C_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"\n]+)"', re.MULTILINE)

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, lang TEXT NOT NULL,
    status TEXT NOT NULL, diagnostic TEXT NOT NULL DEFAULT '');
CREATE TABLE symbols (
    file TEXT NOT NULL, qualname TEXT NOT NULL, name TEXT NOT NULL,
    kind TEXT NOT NULL, line INTEGER NOT NULL, end_line INTEGER NOT NULL);
CREATE INDEX symbols_name ON symbols(name);
CREATE INDEX symbols_file ON symbols(file);
CREATE TABLE edges (
    src_file TEXT NOT NULL, src_qual TEXT NOT NULL, kind TEXT NOT NULL,
    target_name TEXT NOT NULL, target_module TEXT NOT NULL DEFAULT '',
    target_file TEXT, line INTEGER NOT NULL);
CREATE INDEX edges_target ON edges(target_name);
CREATE INDEX edges_src ON edges(src_file, src_qual);
CREATE INDEX edges_target_file ON edges(target_file);
"""


# ------------------------------------------------------------------ result types
@dataclass(frozen=True, slots=True)
class Snapshot:
    """Provenance of an answer. `stale` is true if HEAD or the working tree moved on."""

    repo: str
    commit: str
    indexed_at: datetime
    stale: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "commit": self.commit,
            "indexed_at": self.indexed_at.isoformat(),
            "stale": self.stale,
        }


@dataclass(frozen=True, slots=True)
class GraphAnswer:
    """One query answer. `truncated` lists the caps that cut it (`depth`, `size`, `limit`)."""

    query: str
    subject: str
    snapshot: Snapshot
    items: tuple[Mapping[str, Any], ...]
    truncated: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    confidence: str = CONFIDENCE

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "subject": self.subject,
            "snapshot": self.snapshot.as_dict(),
            "confidence": self.confidence,
            "items": [dict(item) for item in self.items],
            "truncated": list(self.truncated),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """What one refresh touched. `parsed` is the only set of files that was read as source."""

    repo: str
    commit: str
    parsed: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: int = 0
    diagnostics: tuple[str, ...] = ()
    rebuilt: bool = False


@dataclass(slots=True)
class _Extracted:
    lang: str
    symbols: list[tuple[str, str, str, int, int]] = field(default_factory=list)
    edges: list[tuple[str, str, str, str, int]] = field(default_factory=list)
    diagnostic: str = ""


# ---------------------------------------------------------------------- extraction
class _PythonVisitor(ast.NodeVisitor):
    """Symbols, imports, calls and references of one module, by name."""

    def __init__(self) -> None:
        self.symbols: list[tuple[str, str, str, int, int]] = []
        # (src qualname, kind, target name, target module, line)
        self.edges: set[tuple[str, str, str, str, int]] = set()
        self._scope: list[tuple[str, bool]] = []  # (qualname, is_class)

    @property
    def _src(self) -> str:
        return self._scope[-1][0] if self._scope else MODULE_SCOPE

    def _define(self, node: ast.AST, name: str, kind: str) -> str:
        qual = f"{self._scope[-1][0]}.{name}" if self._scope else name
        end = getattr(node, "end_lineno", None) or node.lineno  # type: ignore[attr-defined]
        self.symbols.append((qual, name, kind, node.lineno, end))  # type: ignore[attr-defined]
        return qual

    def _enter(self, node: ast.AST, name: str, kind: str, *, is_class: bool) -> None:
        qual = self._define(node, name, kind)
        self._scope.append((qual, is_class))
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name, "class", is_class=True)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        in_class = bool(self._scope) and self._scope[-1][1]
        self._enter(node, node.name, "method" if in_class else "function", is_class=False)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._scope:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._define(node, target.id, "variable")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.edges.add((self._src, "import", alias.name.rpartition(".")[2], alias.name, alias.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            self.edges.add((self._src, "import", alias.name, module, alias.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            self.edges.add((self._src, "call", func.id, "", node.lineno))
        elif isinstance(func, ast.Attribute):
            self.edges.add((self._src, "call", func.attr, "", node.lineno))
            self.visit(func.value)
        else:
            self.visit(func)
        for child in (*node.args, *node.keywords):
            self.visit(child)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.edges.add((self._src, "ref", node.id, "", node.lineno))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self.edges.add((self._src, "ref", node.attr, "", node.lineno))
        self.visit(node.value)


def _extract_python(data: bytes) -> _Extracted:
    out = _Extracted(lang="python")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # indexing a repo is not the place to lint its escapes
            tree = ast.parse(data)
    except SyntaxError as exc:
        out.diagnostic = f"syntax_error line {exc.lineno or 0}: {exc.msg}"
        return out
    except (ValueError, RecursionError, MemoryError) as exc:
        out.diagnostic = f"unparseable: {type(exc).__name__}"
        return out
    visitor = _PythonVisitor()
    visitor.visit(tree)
    out.symbols = visitor.symbols
    out.edges = sorted(visitor.edges)
    return out


def _extract_regex(data: bytes, lang: str, patterns: Iterable[re.Pattern[str]]) -> _Extracted:
    out = _Extracted(lang=lang)
    text = data.decode("utf-8", errors="replace")
    seen: set[tuple[str, int]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            spec, line = match.group(1), text.count("\n", 0, match.start()) + 1
            if (spec, line) not in seen:
                seen.add((spec, line))
                out.edges.append((MODULE_SCOPE, "import", "", spec, line))
    out.edges.sort()
    return out


def _language(path: str) -> str | None:
    suffix = posixpath.splitext(path)[1].lower()
    if suffix in (".py", ".pyi"):
        return "python"
    if suffix in _JS_SUFFIXES:
        return "javascript"
    if suffix in _C_SUFFIXES:
        return "c"
    if suffix in _FILE_ONLY_SUFFIXES:
        return "other"
    return None


def _extract(path: str, data: bytes) -> _Extracted:
    lang = _language(path) or "other"
    if lang == "python":
        return _extract_python(data)
    if lang == "javascript":
        return _extract_regex(data, lang, _JS_IMPORTS)
    if lang == "c":
        return _extract_regex(data, lang, (_C_INCLUDE,))
    return _Extracted(lang=lang)


# ----------------------------------------------------------------- import resolution
def _first_existing(candidates: Iterable[str], files: set[str]) -> str | None:
    return next((c for c in candidates if c in files), None)


def _resolve_import(src_file: str, lang: str, module: str, name: str, files: set[str]) -> str | None:
    """Repository file a module reference points at, or `None` (external or unknown)."""

    src_dir = posixpath.dirname(src_file)
    if lang == "python":
        level = len(module) - len(module.lstrip("."))
        rest = module[level:].replace(".", "/")
        base = src_dir
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        if level == 0:
            base = ""
        stem = posixpath.join(base, rest) if rest else base
        if name and name != "*":
            sub = posixpath.join(stem, name)
            hit = _first_existing((f"{sub}.py", f"{sub}.pyi", f"{sub}/__init__.py"), files)
            if hit:
                return hit
        if not stem:
            return _first_existing(("__init__.py",), files)
        return _first_existing((f"{stem}.py", f"{stem}.pyi", f"{stem}/__init__.py"), files)
    if lang == "javascript":
        if not module.startswith("."):
            return None
        stem = posixpath.normpath(posixpath.join(src_dir, module))
        candidates = [stem, *(stem + ext for ext in _JS_SUFFIXES), *(f"{stem}/index{ext}" for ext in _JS_SUFFIXES)]
        return _first_existing(candidates, files)
    if lang == "c":
        return _first_existing((posixpath.normpath(posixpath.join(src_dir, module)), posixpath.normpath(module)), files)
    return None


# --------------------------------------------------------------------------- git
def _git(repo: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"git unavailable for {repo}: {exc}") from exc
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"git failed for {repo}: {detail}")
    return done.stdout


def _head(repo: Path) -> str:
    try:
        return _git(repo, "rev-parse", "--verify", "HEAD").decode().strip()
    except MemoryStoreError:
        _git(repo, "rev-parse", "--git-dir")  # not a repository at all: let it raise
        return UNBORN_COMMIT


def _require_toplevel(repo: Path) -> None:
    """The graph is keyed by repository path: refuse a folder inside another repository."""

    top = _git(repo, "rev-parse", "--show-toplevel").decode("utf-8", errors="replace").strip()
    if Path(top).resolve() != repo:
        raise MemoryStoreError(MemoryErrorCode.UNAVAILABLE, f"{repo} is not the root of a git repository")


def _source_files(repo: Path) -> list[str]:
    """Tracked plus untracked-not-ignored files still on disk with a known source suffix, sorted."""

    raw = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    names = {n.decode("utf-8", errors="replace") for n in raw.split(b"\0") if n}
    return sorted(n for n in names if _language(n) and (repo / n).is_file())


def _tree_fingerprint(repo: Path, paths: Sequence[str]) -> str:
    """Stat-only digest of the indexable working tree (path, size, mtime)."""

    digest = hashlib.sha256()
    for rel in paths:
        try:
            st = (repo / rel).stat()
            digest.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
        except OSError:
            digest.update(f"{rel}\0missing\n".encode())
    return digest.hexdigest()


# ---------------------------------------------------------------------- the provider
def repo_id(repo: Path) -> str:
    """Stable token for a repository path, usable as asset id and loadout entry."""

    resolved = repo.expanduser().resolve()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", resolved.name).strip("-.")[:60] or "repo"
    return f"{slug}-{hashlib.sha1(str(resolved).lower().encode()).hexdigest()[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _last_segment(subject: str) -> str:
    return subject.rpartition("::")[2].rpartition(".")[2]


class CodeGraphProvider:
    """`KnowledgeAssetProvider` for code structure, plus the graph queries."""

    kind = AssetKind.CODEGRAPH

    def __init__(
        self,
        root: Path,
        repos: Sequence[Path] = (),
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self._repos = {repo_id(Path(r)): Path(r).expanduser().resolve() for r in repos}
        self._clock = clock
        self._lock = threading.RLock()
        self._verified: set[Path] = set()

    # ------------------------------------------------------------------ plumbing
    def db_path(self, repo: str | Path | None = None) -> Path:
        return self.root / f"{self._repo_key(repo)[0]}.sqlite3"

    def _repo_key(self, repo: str | Path | None) -> tuple[str, Path]:
        if repo is None:
            if len(self._repos) != 1:
                raise ValueError("repo is required when the provider serves zero or several repositories")
            return next(iter(self._repos.items()))
        if isinstance(repo, str) and repo in self._repos:
            return repo, self._repos[repo]
        rid = repo_id(Path(repo))
        if rid not in self._repos:
            raise MemoryStoreError(MemoryErrorCode.NOT_FOUND, f"unknown codegraph repository {repo}")
        return rid, self._repos[rid]

    def _connect(self, rid: str) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{rid}.sqlite3"
        for attempt in (0, 1):
            con = sqlite3.connect(path)
            try:
                version = con.execute("PRAGMA user_version").fetchone()[0]
                if version == SCHEMA_VERSION:
                    con.execute("SELECT count(*) FROM meta").fetchone()
                    return con
                if version == 0 and con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0:
                    con.executescript(_SCHEMA)
                    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                    con.commit()
                    return con
                raise sqlite3.DatabaseError(f"foreign codegraph schema version {version}")
            except sqlite3.DatabaseError:
                con.close()
                if attempt:
                    raise
                path.unlink(missing_ok=True)  # derived state: rebuilt from the repository
        raise AssertionError("unreachable")

    def _check_repo(self, path: Path) -> None:
        if path not in self._verified:
            _require_toplevel(path)
            self._verified.add(path)

    def _meta(self, con: sqlite3.Connection) -> dict[str, str]:
        return dict(con.execute("SELECT key, value FROM meta"))

    # ------------------------------------------------------------------- refresh
    def refresh(self, repo: str | Path | None = None, *, _fresh: bool = False) -> RefreshReport:
        """Bring the graph to the current working tree, reading only changed files."""

        rid, path = self._repo_key(repo)
        with self._lock, closing(self._connect(rid)) as con:
            self._check_repo(path)
            commit = _head(path)
            names = _source_files(path)
            known = dict(con.execute("SELECT path, sha256 FROM files"))
            parsed: list[str] = []
            diagnostics: list[str] = []
            unchanged = 0
            with con:
                gone = sorted(set(known) - set(names))
                for rel in gone:
                    self._drop_file(con, rel)
                for rel in names:
                    data = self._read(path / rel)
                    digest = hashlib.sha256(data if data is not None else b"\0missing").hexdigest()
                    if known.get(rel) == digest:
                        unchanged += 1
                        continue
                    self._drop_file(con, rel)
                    if data is None:
                        extracted = _Extracted(lang=_language(rel) or "other", diagnostic="unreadable_or_too_large")
                    else:
                        extracted = _extract(rel, data)
                    parsed.append(rel)
                    self._store_file(con, rel, digest, extracted)
                self._resolve_all(con, set(names))
                diagnostics = [f"{p}: {d}" for p, d in con.execute(
                    "SELECT path, diagnostic FROM files WHERE status = 'error' ORDER BY path")]
                indexed_at = self._clock()
                con.executemany(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    [
                        ("repo", str(path)),
                        ("commit", commit),
                        ("indexed_at", indexed_at.isoformat()),
                        ("tree", _tree_fingerprint(path, names)),
                    ],
                )
        return RefreshReport(
            repo=str(path), commit=commit, parsed=tuple(parsed), removed=tuple(gone),
            unchanged=unchanged, diagnostics=tuple(diagnostics), rebuilt=_fresh,
        )

    @staticmethod
    def _read(path: Path) -> bytes | None:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                return None
            return path.read_bytes()
        except OSError:
            return None

    @staticmethod
    def _drop_file(con: sqlite3.Connection, rel: str) -> None:
        for table, column in (("files", "path"), ("symbols", "file"), ("edges", "src_file")):
            con.execute(f"DELETE FROM {table} WHERE {column} = ?", (rel,))

    @staticmethod
    def _store_file(con: sqlite3.Connection, rel: str, digest: str, out: _Extracted) -> None:
        con.execute(
            "INSERT INTO files(path, sha256, lang, status, diagnostic) VALUES (?, ?, ?, ?, ?)",
            (rel, digest, out.lang, "error" if out.diagnostic else "ok", out.diagnostic),
        )
        con.executemany(
            "INSERT INTO symbols(file, qualname, name, kind, line, end_line) VALUES (?, ?, ?, ?, ?, ?)",
            [(rel, *row) for row in out.symbols],
        )
        con.executemany(
            "INSERT INTO edges(src_file, src_qual, kind, target_name, target_module, line) VALUES (?, ?, ?, ?, ?, ?)",
            [(rel, src, kind, name, module, line) for src, kind, name, module, line in out.edges],
        )

    @staticmethod
    def _resolve_all(con: sqlite3.Connection, files: set[str]) -> None:
        """Re-resolve every import: a file added or removed elsewhere changes the answer."""

        langs = dict(con.execute("SELECT path, lang FROM files"))
        rows = con.execute(
            "SELECT rowid, src_file, target_name, target_module FROM edges WHERE kind = 'import'").fetchall()
        con.executemany(
            "UPDATE edges SET target_file = ? WHERE rowid = ?",
            [(_resolve_import(src, langs.get(src, "other"), module, name, files), rowid)
             for rowid, src, name, module in rows],
        )

    def rebuild(self) -> int:
        """Drop and rebuild every configured graph from scratch; returns repositories indexed."""

        count = 0
        for rid in self._repos:
            with self._lock:
                (self.root / f"{rid}.sqlite3").unlink(missing_ok=True)
                self.refresh(rid, _fresh=True)
            count += 1
        return count

    # ---------------------------------------------------------------- provenance
    def _snapshot(self, path: Path, con: sqlite3.Connection) -> Snapshot | None:
        """Provenance of the stored graph, or `None` when the repository was never indexed."""

        self._check_repo(path)
        meta = self._meta(con)
        if "commit" not in meta:
            return None
        stale = meta["commit"] != _head(path) or meta["tree"] != _tree_fingerprint(path, _source_files(path))
        return Snapshot(str(path), meta["commit"], datetime.fromisoformat(meta["indexed_at"]), stale)

    @staticmethod
    def _diagnostics(con: sqlite3.Connection) -> tuple[str, ...]:
        return tuple(f"{p}: {d}" for p, d in con.execute(
            "SELECT path, diagnostic FROM files WHERE status = 'error' ORDER BY path"))

    def _open(self, repo: str | Path | None) -> tuple[sqlite3.Connection, Snapshot, tuple[str, ...]]:
        """Connection to an indexed graph (indexed on first use) with its snapshot and diagnostics."""

        rid, path = self._repo_key(repo)
        with self._lock:
            con = self._connect(rid)
            try:
                snapshot = self._snapshot(path, con)
                if snapshot is None:
                    self.refresh(rid)
                    snapshot = self._snapshot(path, con)
                assert snapshot is not None
                return con, snapshot, self._diagnostics(con)
            except BaseException:
                con.close()
                raise

    # -------------------------------------------------------------------- queries
    def _answer(
        self, query: str, subject: str, repo: str | Path | None,
        build: Callable[[sqlite3.Connection], tuple[list[dict[str, Any]], list[str]]], limit: int | None,
    ) -> GraphAnswer:
        if limit is not None:
            check_int_range("limit", limit, 1, MAX_LIMIT)
        con, snapshot, diagnostics = self._open(repo)
        with closing(con):
            items, truncated = build(con)
        if limit is not None and len(items) > limit:
            items, truncated = items[:limit], [*truncated, "limit"]
        return GraphAnswer(query, subject, snapshot, tuple(items), tuple(truncated), diagnostics)

    @staticmethod
    def _nodes(con: sqlite3.Connection, subject: str) -> list[tuple[str, str, str, str, int]]:
        """Symbols named by `subject`: `file::qualname`, a qualname, or a bare name."""

        if "::" in subject:
            file, _, qual = subject.partition("::")
            if qual == MODULE_SCOPE and con.execute("SELECT 1 FROM files WHERE path = ?", (file,)).fetchone():
                return [(file, MODULE_SCOPE, MODULE_SCOPE, "module", 1)]
            rows = con.execute(
                "SELECT file, qualname, name, kind, line FROM symbols WHERE file = ? AND qualname = ? ORDER BY line",
                (file, qual))
        else:
            rows = con.execute(
                "SELECT file, qualname, name, kind, line FROM symbols WHERE name = ? OR qualname = ? "
                "ORDER BY file, line, qualname", (subject, subject))
        return rows.fetchall()

    def symbol(self, name: str, repo: str | Path | None = None, *, limit: int = DEFAULT_LIMIT) -> GraphAnswer:
        """Definitions whose name, qualname or `file::qualname` equals `name`."""

        def build(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
            return [
                {"id": f"{f}::{q}", "path": f, "qualname": q, "kind": k, "line": line}
                for f, q, _n, k, line in self._nodes(con, name)
            ], []

        return self._answer("symbol", name, repo, build, limit)

    def usages(self, name: str, repo: str | Path | None = None, *, limit: int = DEFAULT_LIMIT) -> GraphAnswer:
        """Every import, call or reference whose target name equals the symbol's last segment."""

        target = _last_segment(name)

        def build(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
            rows = con.execute(
                "SELECT src_file, src_qual, kind, line FROM edges WHERE target_name = ? "
                "ORDER BY src_file, line, src_qual, kind", (target,))
            return [
                {"path": f, "line": line, "kind": k, "in": f"{f}::{q}"} for f, q, k, line in rows
            ], []

        return self._answer("usages", name, repo, build, limit)

    def neighbors(self, subject: str, repo: str | Path | None = None, *, limit: int = DEFAULT_LIMIT) -> GraphAnswer:
        """Direct edges around a file path or a symbol, both directions."""

        def build(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
            items: dict[tuple[str, str, str, str], dict[str, Any]] = {}

            def add(of: str, direction: str, relation: str, node_id: str, path: str, line: int) -> None:
                key = (of, direction, relation, node_id)
                if key not in items or line < items[key]["line"]:
                    items[key] = {"of": of, "direction": direction, "relation": relation,
                                  "id": node_id, "path": path, "line": line}

            if con.execute("SELECT 1 FROM files WHERE path = ?", (subject,)).fetchone():
                for (target, line) in con.execute(
                        "SELECT target_file, MIN(line) FROM edges WHERE src_file = ? AND kind = 'import' "
                        "AND target_file IS NOT NULL GROUP BY target_file", (subject,)):
                    add(subject, "out", "import", target, target, line)
                for (src, line) in con.execute(
                        "SELECT src_file, MIN(line) FROM edges WHERE target_file = ? AND kind = 'import' "
                        "GROUP BY src_file", (subject,)):
                    add(subject, "in", "import", src, src, line)
                for q, k, line in con.execute(
                        "SELECT qualname, kind, line FROM symbols WHERE file = ?", (subject,)):
                    add(subject, "out", "defines", f"{subject}::{q}", subject, line)
            else:
                for f, q, name, _k, _line in self._nodes(con, subject):
                    of = f"{f}::{q}"
                    for tf, tq, relation, line in self._callees(con, f, q):
                        add(of, "out", relation, f"{tf}::{tq}", tf, line)
                    for sf, sq, relation, line in con.execute(
                            "SELECT src_file, src_qual, kind, MIN(line) FROM edges WHERE target_name = ? "
                            "AND kind IN ('call', 'ref') GROUP BY src_file, src_qual, kind", (name,)):
                        add(of, "in", relation, f"{sf}::{sq}", sf, line)
            return sorted(items.values(), key=lambda i: (i["of"], i["direction"], i["relation"], i["id"])), []

        return self._answer("neighbors", subject, repo, build, limit)

    @staticmethod
    def _callees(con: sqlite3.Connection, file: str, qual: str) -> list[tuple[str, str, str, int]]:
        """Symbols a node calls or references by name: (file, qualname, relation, line)."""

        out: list[tuple[str, str, str, int]] = []
        for target, relation, line in con.execute(
                "SELECT target_name, kind, MIN(line) FROM edges WHERE src_file = ? AND src_qual = ? "
                "AND kind IN ('call', 'ref') GROUP BY target_name, kind ORDER BY target_name, kind", (file, qual)):
            for tf, tq in con.execute(
                    "SELECT file, qualname FROM symbols WHERE name = ? ORDER BY file, line", (target,)):
                out.append((tf, tq, relation, line))
        return out

    def path(
        self, source: str, target: str, repo: str | Path | None = None, *, max_depth: int = DEFAULT_PATH_DEPTH,
    ) -> GraphAnswer:
        """Shortest forward path (call/ref edges between symbols, import edges between files).

        Items are the steps in order; empty when no path exists within the caps.
        """

        check_int_range("max_depth", max_depth, 1, MAX_PATH_DEPTH)

        def build(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
            def is_file(s: str) -> bool:
                return con.execute("SELECT 1 FROM files WHERE path = ?", (s,)).fetchone() is not None

            file_mode = is_file(source) and is_file(target)
            if file_mode:
                starts, goals = [source], {target}
            else:
                starts = [f"{f}::{q}" for f, q, *_ in self._nodes(con, source)]
                goals = {f"{f}::{q}" for f, q, *_ in self._nodes(con, target)}
            prev: dict[str, tuple[str | None, str, int]] = {s: (None, "", 0) for s in starts}
            frontier, found, truncated = list(starts), next((s for s in starts if s in goals), None), []
            depth = 0
            while frontier and found is None:
                if depth >= max_depth:
                    if any(n not in prev for f in frontier for n, _r, _l in self._forward(con, f, file_mode)):
                        truncated.append("depth")
                    break
                depth += 1
                nxt: list[str] = []
                for node in frontier:
                    for node_id, relation, line in self._forward(con, node, file_mode):
                        if node_id in prev:
                            continue
                        if len(prev) >= PATH_VISIT_CAP:
                            truncated.append("size")
                            return [], truncated
                        prev[node_id] = (node, relation, line)
                        nxt.append(node_id)
                        if node_id in goals:
                            found = node_id
                            break
                    if found:
                        break
                frontier = nxt
            if found is None:
                return [], truncated
            steps: list[dict[str, Any]] = []
            cursor: str | None = found
            while cursor is not None:
                parent, relation, line = prev[cursor]
                steps.append({"id": cursor, "path": cursor.partition("::")[0], "via": relation, "line": line})
                cursor = parent
            return steps[::-1], []

        return self._answer("path", f"{source} -> {target}", repo, build, None)

    def _forward(self, con: sqlite3.Connection, node: str, file_mode: bool) -> list[tuple[str, str, int]]:
        if file_mode:
            return [(t, "import", line) for t, line in con.execute(
                "SELECT target_file, MIN(line) FROM edges WHERE src_file = ? AND kind = 'import' "
                "AND target_file IS NOT NULL GROUP BY target_file ORDER BY target_file", (node,))]
        file, _, qual = node.partition("::")
        return [(f"{tf}::{tq}", rel, line) for tf, tq, rel, line in self._callees(con, file, qual)]

    def impact(
        self, name: str, repo: str | Path | None = None, *,
        max_depth: int = DEFAULT_IMPACT_DEPTH, max_nodes: int = DEFAULT_IMPACT_NODES,
    ) -> GraphAnswer:
        """Reverse-reachable closure over call/ref edges, with depth and size caps.

        A module-level use is a leaf (listed, not expanded). Items carry `depth`
        (1 = direct user) and `via` (the node whose name matched).
        """

        check_int_range("max_depth", max_depth, 1, MAX_IMPACT_DEPTH)
        check_int_range("max_nodes", max_nodes, 1, MAX_IMPACT_NODES)

        def build(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
            starts = [(f, q, n) for f, q, n, *_ in self._nodes(con, name)]
            visited = {(f, q) for f, q, _ in starts}
            items: list[dict[str, Any]] = []
            frontier = starts
            depth = 0
            while frontier:
                depth += 1
                by_name: dict[str, str] = {}
                for f, q, n in frontier:
                    by_name.setdefault(n, f"{f}::{q}")
                rows: set[tuple[str, str, int, str, str]] = set()
                names = sorted(by_name)
                for i in range(0, len(names), _IN_CHUNK):
                    chunk = names[i:i + _IN_CHUNK]
                    marks = ",".join("?" * len(chunk))
                    rows.update(con.execute(
                        f"SELECT src_file, src_qual, line, kind, target_name FROM edges "
                        f"WHERE kind IN ('call', 'ref') AND target_name IN ({marks})", chunk))
                fresh: dict[tuple[str, str], tuple[int, str, str]] = {}
                for f, q, line, kind, target in sorted(rows):
                    if (f, q) in visited or (f, q) in fresh:
                        continue
                    fresh[(f, q)] = (line, kind, by_name[target])
                if not fresh:
                    break
                if depth > max_depth:
                    return items, ["depth"]
                nxt: list[tuple[str, str, str]] = []
                for (f, q), (line, kind, via) in fresh.items():
                    if len(items) >= max_nodes:
                        return items, ["size"]
                    visited.add((f, q))
                    items.append({"id": f"{f}::{q}", "path": f, "qualname": q, "depth": depth,
                                  "via": via, "line": line, "kind": kind})
                    if q != MODULE_SCOPE:
                        nxt.append((f, q, q.rpartition(".")[2]))
                frontier = nxt
            return items, []

        return self._answer("impact", name, repo, build, None)

    # ---------------------------------------------------------- KnowledgeAssetProvider
    def status(self) -> CapabilityState:
        """Never indexes: a repository without a graph is degraded, a moved one is stale."""

        if not self._repos:
            return CapabilityState(CapabilityStatus.DISABLED, "codegraph_no_repo", "no repository configured")
        problems: list[str] = []
        for rid, path in self._repos.items():
            try:
                with closing(self._connect(rid)) as con:
                    snapshot = self._snapshot(path, con)
            except MemoryStoreError as exc:
                return CapabilityState(CapabilityStatus.UNAVAILABLE, "codegraph_repo_unavailable", exc.message[:200])
            if snapshot is None:
                problems.append(f"{path.name} not indexed")
            elif snapshot.stale:
                problems.append(f"{path.name} stale")
        if problems:
            return CapabilityState(CapabilityStatus.DEGRADED, "codegraph_stale", "; ".join(problems)[:200])
        return capability_ok()

    def _asset(self, rid: str, path: Path, *, body: bool) -> KnowledgeAsset:
        """`body=False` (list, search) never indexes: a missing graph shows as stale and empty."""

        title = path.name or str(path)
        with self._lock, closing(self._connect(rid)) as con:
            snapshot = self._snapshot(path, con)
            if snapshot is None and body:
                self.refresh(rid)
                snapshot = self._snapshot(path, con)
            if snapshot is None:
                source = SourceRef(uri=path.as_uri(), version_or_commit=_head(path), fetched_at=self._clock())
                return KnowledgeAsset(
                    asset_id=rid, kind=AssetKind.CODEGRAPH, title=title, scope=AssetScope.PROJECT,
                    source=source, summary="not indexed yet", version=str(SCHEMA_VERSION), stale=True,
                    confidence=CONFIDENCE)
            diagnostics = self._diagnostics(con)
            files = con.execute("SELECT count(*) FROM files").fetchone()[0]
            symbols = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
            by_lang = con.execute("SELECT lang, count(*) FROM files GROUP BY lang ORDER BY lang").fetchall()
            text = self._body(con, snapshot, files, symbols, by_lang, diagnostics) if body else ""
        langs = ", ".join(f"{lang} {n}" for lang, n in by_lang)
        return KnowledgeAsset(
            asset_id=rid, kind=AssetKind.CODEGRAPH, title=title, scope=AssetScope.PROJECT,
            source=SourceRef(uri=path.as_uri(), version_or_commit=snapshot.commit, fetched_at=snapshot.indexed_at),
            summary=f"{files} files ({langs}), {symbols} symbols, {len(diagnostics)} skipped; name-based graph",
            body=text, version=str(SCHEMA_VERSION), stale=snapshot.stale, confidence=CONFIDENCE,
        )

    @staticmethod
    def _body(con: sqlite3.Connection, snap: Snapshot, files: int, symbols: int,
              by_lang: Sequence[tuple[str, int]], diagnostics: Sequence[str]) -> str:
        lines = [
            f"repo: {snap.repo}", f"commit: {snap.commit}", f"indexed_at: {snap.indexed_at.isoformat()}",
            f"stale: {str(snap.stale).lower()}", f"confidence: {CONFIDENCE}",
            f"files: {files}  symbols: {symbols}  languages: " + ", ".join(f"{la} {n}" for la, n in by_lang),
        ]
        if diagnostics:
            lines += ["", "skipped:", *(f"- {d}" for d in diagnostics)]
        lines += ["", "files (symbols):"]
        for path, n in con.execute(
                "SELECT f.path, count(s.file) FROM files f LEFT JOIN symbols s ON s.file = f.path "
                "GROUP BY f.path ORDER BY f.path"):
            lines.append(f"- {path} ({n})")
        return "\n".join(lines)[:MAX_BODY_CHARS]

    def list(self, scope: AssetScope | None = None) -> tuple[KnowledgeAsset, ...]:
        if scope not in (None, AssetScope.PROJECT):
            return ()
        assets = []
        for rid, path in self._repos.items():
            try:
                assets.append(self._asset(rid, path, body=False))
            except MemoryStoreError:
                continue  # `status()` carries the reason
        return tuple(assets)

    def read(self, asset_id: str) -> KnowledgeAsset:
        rid, path = self._repo_key(asset_id)
        return self._asset(rid, path, body=True)

    def search(self, query: str, limit: int, scope: AssetScope | None = None) -> Sequence[AssetHit]:
        """Symbol-name search across repositories, best match first."""

        needle = query.strip()
        if not needle or limit < 1 or scope not in (None, AssetScope.PROJECT):
            return ()
        hits: list[AssetHit] = []
        low = needle.lower()
        for rid, path in self._repos.items():
            try:
                asset = self._asset(rid, path, body=False)
            except MemoryStoreError:
                continue
            with self._lock, closing(self._connect(rid)) as con:
                for f, q, n, k, line in con.execute(
                        "SELECT file, qualname, name, kind, line FROM symbols ORDER BY file, line"):
                    # Python lower(): SQLite lower() is ASCII-only and would miss `Écran`.
                    if low not in q.lower():
                        continue
                    score = 1.0 if low in (n.lower(), q.lower()) else 0.7 if n.lower().startswith(low) else 0.4
                    hits.append(AssetHit(asset, f"{k} {q} at {f}:{line}", score))
        hits.sort(key=lambda h: -h.score)
        return tuple(hits[:limit])
