# Knowledge assets (Wiki)

Contract page for knowledge assets of the memory, intelligence and knowledge
handoff. Slice 07 ships the **Wiki** kind. Contracts:
`jarvis/domain/knowledge.py`, `jarvis/ports/knowledge.py` (see
[memory.md](memory.md)). Adapter: `jarvis/adapters/knowledge_wiki.py`. Tests:
`tests/unit/test_knowledge_wiki.py`. CodeGraph assets: [codegraph.md](codegraph.md).

A knowledge asset is imported or derived reference material. It lives under
`<data_root>/knowledge/<kind>/`, never in the personal memory root, and is never
canonical personal memory.

## Asset contract

`KnowledgeAssetProvider` (synchronous, called through a thread): `kind`,
`status()`, `list(scope)`, `search(query, limit, scope)`, `read(asset_id)`,
`rebuild()`. `list` and `search` return assets with an empty `body`; `read`
fills it. Every asset carries:

| Field | Wiki value |
|---|---|
| `asset_id` | token <= 128, `<slug>-<8 hex of the source uri hash>` unless the caller sets one |
| `source.uri` | `file:///...` of the imported file, or the recorded URL |
| `source.version_or_commit` | `sha256:<first 16 hex of the source hash>` |
| `source.path` | path relative to the allowlist root (`None` for a URL) |
| `source.fetched_at` | UTC time of the last content change import |
| `version` | `1`, +1 each time the source hash changes on re-import |
| `stale` | true when the source no longer matches the stored hash |
| `scope` | `private`, `project` or `shared` (`AssetScope`) |

Source and version are always present: a page cannot be stored without them.

## Storage

```
<data_root>/knowledge/wiki/
  pages/page-<asset_id>.json   the imported copy: metadata + body, one atomic file
  index/wiki-index.sqlite3     derived FTS5 index (separate sqlite file)
```

The pages are the truth. The index is disposable: delete it (or let it corrupt)
and the next `search`, `status` or `rebuild()` recreates it from the pages.
`WikiProvider(root, allowed_roots=None, clock=None)`; `allowed_roots=None`
means the repo `docs/` tree.

## Ingestion lifecycle

| Step | Call | Effect |
|---|---|---|
| import | `import_file(path, scope)`, `import_tree(dir, scope)` | copy an allowlisted `.md` in; a tree import returns the imported assets and the skipped files with the reason |
| record a URL | `import_text(uri, title, body, scope)` | the URL is stored as `source_uri`; **nothing is ever fetched** |
| update | `refresh(asset_id)` or re-import | same hash: no change; new hash: `version` + 1, new `fetched_at` |
| stale check | on every `list`, `search`, `read` | hash of the source now vs the stored one; source gone, moved out of the allowlist or behind a link also reads stale. File mtime is not trusted |
| delete | `delete(asset_id)` | removes the page and its index row; the source file is never touched |
| rebuild | `rebuild()` | refill the index from the pages, returns the count |

URL pages are never stale (there is no way to know) and cannot be refreshed.

## Safety

- Only paths under an allowlisted root are read. `..`, NUL, an absolute path
  outside every root, a sibling that merely shares a prefix, and any symlink or
  Windows junction between the root and the file are refused with
  `MemorySecurityError`; a tree import never descends into links.
- Only `.md`, valid UTF-8, at most 64 000 characters.
- No network access in this handoff.

## Scope isolation

`list`, `search` and `read` take a scope. `list(PROJECT)` and `search(..., PROJECT)`
never return a private page; `read(asset_id, scope=PROJECT)` of a private page
raises `memory_scope_denied`. The scope of a hit is checked on the page, not
trusted from the index. Calling without a scope sees every scope, so callers
(the loadout layer, Slice 09) must always pass one. The enum has no project
qualifier yet: `PROJECT` is one bucket, not `project:<id>`.

## Not in this slice

Semantic search, Brain injection and loadouts (Slice 09), Core routes
(Slices 10b and 12), CodeGraph and Skills.
