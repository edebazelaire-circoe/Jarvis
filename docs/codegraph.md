# CodeGraph

Code-structure knowledge asset of the memory, intelligence and knowledge
handoff (Slice 08). Code: `jarvis/adapters/knowledge_codegraph.py`
(`CodeGraphProvider`, a `KnowledgeAssetProvider` of kind `codegraph`). Tests:
`tests/unit/test_knowledge_codegraph.py`, fixture `tests/fixtures/codegraph_repo/`.
Asset contract: [memory.md](memory.md).

CodeGraph is **derived state**. Delete its files and nothing durable is lost: the
next query rebuilds them from the repository. It is not memory, never enters the
personal memory root, and is not wired into the Brain or any loadout yet (Slice 09).

## What is indexed

| Files | Extracted |
|---|---|
| Python (`.py`, `.pyi`), stdlib `ast` | symbols (class, function, method, module-level variable) with qualname and line span; imports; calls by name; references by name |
| JS/TS (`.js .jsx .mjs .cjs .ts .tsx`) | file node and import edges (`import ... from`, `export ... from`, `require()`, `import()`), relative specifiers only |
| C/C++ (`.c .h .cc .cpp .hpp .cxx`) | file node and `#include "..."` edges |
| `.go .rs .java .kt .cs .rb .php .swift .sh .ps1 .lua` | file node only |

No tree-sitter, no language server, no type resolution, no new dependency. Files
come from `git ls-files --cached --others --exclude-standard`: tracked plus
untracked-not-ignored, still on disk. A repository must be the root of a git
repository; a folder inside another repository is refused (`memory_unavailable`).
Files over 1 MB or unreadable are skipped with a diagnostic. A file whose path is too
long for Python on Windows is dropped silently (it never reaches the file list, so no
diagnostic).

## Storage and schema

One sqlite file per repository, `<provider root>/<repo_id>.sqlite3`
(`<data_root>/knowledge/codegraph` in production). `repo_id` is
`<folder name>-<8 hex of the sha1 of the lowercased resolved path>`; it is also the
asset id and the loadout `codegraph_repos` entry. The file is keyed by repo path and
records the HEAD it was indexed at. `PRAGMA user_version` is 1. A corrupt file or a
different version is deleted and rebuilt: it is derived, there are no migrations
(resolved architecture D6).

```
meta(key, value)                 repo, commit, indexed_at, tree (stat fingerprint)
files(path PK, sha256, lang, status ok|error, diagnostic)
symbols(file, qualname, name, kind, line, end_line)
edges(src_file, src_qual, kind import|call|ref, target_name, target_module, target_file, line)
```

`src_qual` is the enclosing symbol qualname, or `<module>` for module-level code.
`target_file` is set for imports that resolve to a file of the repository, else NULL
(external). Decorators, base classes, defaults and annotations belong to the
symbol they decorate, so a subclass depends on its base.

## Refresh rules

- `refresh(repo)` reads every indexable file and compares its sha256 with the stored
  one. Only new or changed files are parsed; removed files are dropped. The
  `RefreshReport.parsed` set is exactly what was parsed.
- Import resolution runs again over all import edges at the end of each refresh,
  because adding or removing a file elsewhere changes where an import points.
  That is why a rebuild from scratch equals the incremental result (tested).
- A refresh runs in one transaction and rewrites `commit`, `indexed_at` and `tree`.
  A new commit that changes no file parses nothing.
- A file that does not parse (`SyntaxError`) is stored with `status = error` and a
  diagnostic (`syntax_error line N: ...`), contributes no symbols or edges, and is
  not re-parsed until its content changes. Every answer lists these diagnostics.
- A query never refreshes an existing graph; it reports `stale`. The first query on a
  repository never indexed builds it. `list()`, `search()` and `status()` never
  build: an unindexed repository shows as `stale` / `degraded`.
- `rebuild()` deletes each graph file and indexes from scratch; it returns the number
  of repositories indexed.

## Provenance and staleness

Every answer carries `snapshot = {repo, commit, indexed_at, stale}` and
`confidence: name_match`. `stale` is true when `git rev-parse HEAD` differs from the
indexed commit, or when the stat fingerprint (path, size, mtime) of the indexable
working tree differs from the one recorded at refresh. A touched but unchanged file
therefore reads stale until the next refresh (cheap, since it re-hashes).
The converse is a known limit: an edit that leaves size and mtime unchanged is not detected as stale. Staleness is
reported, never hidden: the answer is still returned. `status()` is `degraded` with
`codegraph_stale` while any repository is stale or unindexed, and `unavailable`
when git fails or the folder is not a repository root.

## Query semantics

All queries return a `GraphAnswer` (`.as_dict()` for JSON): `query`, `subject`,
`snapshot`, `confidence`, `items`, `truncated`, `diagnostics`. `truncated` names the
caps that cut the answer: `limit`, `depth`, `size`. The `repo` argument is a repo id
or path; it may be omitted when the provider serves one repository.

| Query | Subject | Items |
|---|---|---|
| `symbol(name)` | name, qualname (`Engine.run`) or `file::qualname` | definitions: `id`, `path`, `qualname`, `kind`, `line` |
| `usages(name)` | symbol name (last dotted segment is used) | every import, call or reference whose target name matches: `path`, `line`, `kind`, `in` |
| `neighbors(subject)` | file path or symbol | direct edges, `direction` out/in, `relation` import/call/ref/defines |
| `path(src, dst)` | two files (import graph) or two symbols (call/ref graph) | shortest forward path as ordered steps; empty when none within `max_depth` |
| `impact(name)` | symbol | reverse-reachable closure over call/ref edges: `id`, `depth`, `via`, `line`, `kind` |

`id` is `file::qualname`. Ordering is deterministic (file, line, qualname).

Caps (out-of-range arguments raise `ValueError`): `limit` 1..500 (default 100);
`impact` `max_depth` 1..20 (default 5) and `max_nodes` 1..2000 (default 200);
`path` `max_depth` 1..20 (default 8) and 2000 visited nodes. A cap that cuts the
answer is named in `truncated`; an answer that exactly fits, or a search that was
exhaustive before reaching the cap (`path` with no route, cycles included), is not flagged.
Import usages carry the line of the imported name, so a multi-line
`from x import (a, b)` reports each name on its own line, as grep would.

`impact` answers "what can be affected by changing X": callers of X by name, then
callers of those, breadth first. A module-level use (`<module>`) is listed but not
expanded. Imports are listed by `usages` and `neighbors`, not followed by `impact`.

Asset surface: `list()` returns one asset per repository (scope `project`, no body,
`stale`, `confidence: name_match`, `SourceRef(uri=repo, version_or_commit=indexed
commit, fetched_at=indexed_at)`); `read(repo_id)` adds a body with the snapshot,
counts, skipped files and the file list; `search(query, limit)` ranks symbols whose
qualname contains the query (exact 1.0, prefix 0.7, substring 0.4).

## Limitation: name match, not type resolution

An edge targets a **name**. `x.run()` is a call to every symbol called `run`, in any
class or file; `self.foo()` likewise; a local variable with the name of a function is
a reference to it. So:

- `usages` and `impact` can contain false positives for common names; they never
  need type information to be complete for direct name use.
- They miss anything not spelled by name: `getattr(obj, "run")`, dynamic dispatch
  through renamed aliases (`import x as y` binds `y`, edges still say `x`), generated
  code, string-based registration.
- Non-Python languages have file and import edges only, no symbols.

Treat the result as navigation evidence to be confirmed by reading the cited
`path:line`, not as proof. This is why every answer states `confidence: name_match`.
CodeGraph does not replace a language server or a static analyzer.

## Timing

`JARVIS_CODEGRAPH_TIMING=1 pytest tests/unit/test_knowledge_codegraph.py` also indexes
this repository and prints cold and warm times. It is opt-in and has no time gate.
