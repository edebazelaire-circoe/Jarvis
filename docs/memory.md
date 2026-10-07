# Memory contracts

Contract page of the memory, intelligence and knowledge handoff
(`jarvis-memory-intelligence-knowledge`). Slice 01 defined the contracts (pure
models and ports); Slice 02 built the canonical store ([Canonical store](#canonical-store-slice-02)).
Retrieval arrives in Slice 03, consolidation in Slice 04, Brain injection in
Slice 05. Later slices append their own sections here.

Sources: `jarvis/domain/memory.py`, `memory_policy.py`, `knowledge.py`,
`memory_settings.py`; ports `jarvis/ports/memory_store.py`, `memory_retrieval.py`,
`memory_consolidation.py`, `knowledge.py`, `capability.py`. Tests:
`tests/unit/test_memory_contracts.py`.

## Terminology

| Term | Meaning |
|---|---|
| **Canonical store** (`CanonicalMemoryStore`) | The only owner of durable truth: Markdown notes under `<data_root>/memory`. Writes go through it and nowhere else. |
| **Derived index** | Disposable, rebuilt from canonical: the FTS5 lexical index, the semantic vector index, the Tencent mirror, knowledge indexes. Delete one and nothing durable is lost. |
| **Retriever** (`MemoryRetriever`) | Ranks canonical notes for a query. Never writes, never supplies text of its own: a hit that does not resolve to a canonical `memory_id` is dropped. |
| **Consolidator** (`MemoryConsolidator`) | Turns L0 evidence into **candidates**; a decision commits a canonical note with provenance. |
| **Candidate** | A proposed note in `_candidates/`. Not recalled, not auto-deleted. States: `proposed` then `accepted`, `rejected` or `superseded_by_newer`. |
| **Retention class** | Lifetime policy, the directory name (`short_term_memory`, `long_term_memory`, `traumatic_memory`, `eternal_memory`, `plastic_memory`). |
| **Level** | Abstraction, front-matter `level`: L0 raw evidence, L1 atomic fact or preference, L2 scenario or context, L3 stable profile. |
| **Scope** | Who may see a note: `private`, `shared`, `board:<id>`, `project:<id>`. Matched exactly (never by prefix: `board:b1` does not grant `board:b10`), deny by default. A knowledge `AssetScope` maps onto it: `PRIVATE` is `private`, `SHARED` is `shared`, and `PROJECT` is `project:<id>` for the project that owns the asset (the id comes from the loadout or the asset source, not from the enum). |
| **Agent memory policy** (`AgentMemoryPolicy`) | Per-agent read and write scopes. `private` needs an explicit `allow_private`. |
| **Knowledge asset** | Wiki page, CodeGraph snapshot or Skill under `<data_root>/knowledge`. Imported or derived, never canonical memory. Always has a `SourceRef`. |
| **Loadout** | What one agent profile (plus optional role) may see: memory scopes, wiki ids, codegraph repos, skill ids. Default is nothing (`NullLoadoutResolver`). |
| **Capability state** | `ok`, `degraded`, `disabled` or `unavailable` for one leg, with a stable `reason_code` whenever it is not `ok`. |
| **Board memory** | A separate, mature system (`BoardMemoryStore`, WSP). Not merged: it is a peer source with scope `board:<id>`, read-only to the new retriever. |
| **CONTEXT_GLOBAL** | Brain bootstrap instructions (`<data_root>/CONTEXT_GLOBAL`). **Not memory**: never indexed, consolidated or recalled by memory modules. The L3 profile reaches the Brain through the per-turn memory block, never by writing into CONTEXT_GLOBAL. |
| **Legacy `MemoryBackend`** | `jarvis/ports/memory.py`, unchanged. Mixes search, read, append and rebuild. `MarkdownMemoryBackend` implements it and the new ports side by side (Slice 02). Its `notes/` directory is an unclassified legacy class, recalled as `long_term_memory` and never moved. |

Authority rule: canonical storage owns truth. Everything a retriever returns
references a canonical source or is labelled derived. Tencent or any index
becomes an authority only if this rule is broken, so the port shapes forbid it
(a retriever has no write method, an `EmbeddingProvider` only returns vectors).

## Two axes: level x retention

Retention class and level are independent. The class is the directory and says
how long a note lives. The level is front matter and says how abstract it is.
Promotion between classes moves the file; abstraction changes the level through
consolidation. Neither implies the other, and a UI shows them in two columns,
never in one badge.

Allowed pairs (`LEVELS_BY_RETENTION`, checked by `check_level_retention`):

| Retention class \ Level | L0 evidence | L1 atomic | L2 scenario | L3 profile |
|---|---|---|---|---|
| `short_term_memory` | yes | yes | yes | no |
| `long_term_memory` | no | yes | yes | yes |
| `plastic_memory` | no | yes | yes | yes |
| `traumatic_memory` (protected) | no | yes | yes | no |
| `eternal_memory` (protected) | no | yes | yes | yes |

L0 is transient raw evidence, so it only lives in `short_term_memory`. A
traumatic note is a specific episode or lesson, never a stable profile.
Protected classes (`traumatic_memory`, `eternal_memory`): no consolidation path
may delete or rewrite them; supersession is by human action only. Automatic
consolidation may only commit into `long_term_memory` or `plastic_memory`
(`AUTO_COMMIT_RETENTIONS`) with `confidence >= 0.8` (`AUTO_MIN_CONFIDENCE`).

**Enforcement.** `MemoryNote`, `Candidate` and `MemoryPatch` do **not** check
level x retention: a legacy note must be representable before it is classified.
A `CanonicalMemoryStore` implementation MUST call `check_level_retention` on
`create` and on every `revise`, including when `MemoryPatch.level` changes the
level of an existing note (check the new level against the note's retention).
The consolidator does the same before committing a candidate.

## Metadata schema (`MemoryNote`)

A note is a Markdown file with a flat `---` front-matter block (`key: value`
lines, values are JSON scalars, arrays or objects; parser: `memory_frontmatter.py`,
see [Canonical store](#canonical-store-slice-02)). A file without front matter is
a valid legacy note: defaults are derived lazily and written back only when the
note is mutated.

| Field | Type | Rule |
|---|---|---|
| `id` | token <= 64 | stable identity, independent of the path (`new_memory_id()`, assigned by the caller of `create`) |
| `title` | one line <= 200 | required; the first `# ` heading of the file, not a front-matter key |
| `body` | text <= 64 000 | the note: the text after the heading |
| `level` | `L0`..`L3` | see matrix |
| `kind` | `fact`, `preference`, `scenario`, `profile`, `episode` | |
| `retention` | the five classes | the directory, not stored in front matter |
| `scope` | `private`, `shared`, `board:<id>`, `project:<id>` | |
| `created_at`, `updated_at` | aware datetime | `updated_at >= created_at` |
| `valid_from`, `valid_to` | aware datetime or null | temporal validity, `valid_to >= valid_from` |
| `confidence` | 0..1 | finite |
| `sources` | list of `Provenance` (<= 32) | `{type: turn, note, board, manual or consolidation; ref; at}` |
| `revision` | int >= 1 | only the store advances it; a mutation writes N+1 and keeps N in history |
| `supersedes`, `contradicts` | ids (<= 32 each) | links, written by consolidation or a human |
| `superseded_by` | id or null | |
| `agent` | token or null | author agent |

A note never links to itself. Contradictions are explicit links; a conflicting
fact never overwrites: it supersedes (closing `valid_to` on the old note) or is
flagged `contradicts` for human review. `MemoryPatch` can change title, body,
level, kind, `valid_to`, confidence, `superseded_by` and add sources and links.
Identity, `created_at`, `revision`, `retention` and `scope` are not patchable.
`MemoryPatch` cannot clear `valid_to` or `superseded_by` (`None` means
unchanged), so reopening a closed or superseded note is unsupported by design.

## Ports

| Port | Methods | Notes |
|---|---|---|
| `CanonicalMemoryStore` | `get(id)`, `list(filters)`, `create(note)`, `revise(id, patch, expected_revision)`, `history(id)`, `rebuild_indexes()` | Synchronous (disk), called through a thread. |
| `MemoryRetriever` | `async recall(query, budget)`, `status()` | One implementation per leg or hybrid. |
| `RecallLeg` | `name`, `async hits(query, limit, timeout_s)`, `status()` | One ranked list of the hybrid (Slice 03): lexical, semantic, Tencent slot. |
| `EmbeddingProvider` | `model_id`, `dim`, `async embed(texts, timeout)` | Default provider is `none`. |
| `MemoryConsolidator` | `async propose(evidence)`, `async decide(candidate_id, decision, actor)` | Idempotent per evidence hash. |
| `CandidateExtractor` | `async extract(evidence)` | Output is untrusted, schema-validated by the consolidator. |
| `KnowledgeAssetProvider` | `kind`, `status()`, `list(scope)`, `search(query, limit, scope)`, `read(id)`, `rebuild()` | `list` and `search` return assets without body. |
| `LoadoutResolver` | `resolve(profile, role)` | `NullLoadoutResolver` grants nothing; the real one is `KnowledgeLoadoutResolver` (Slice 09, [skills-and-loadouts.md](skills-and-loadouts.md)). |
| `CapabilityReporter` | `capability_id`, `status()` | Cheap, never raises, no synchronous network probe. |

## Budgets

Defaults of `RecallBudget` (hard ceilings are the model bounds):

| Budget | Default | Range |
|---|---|---|
| items per recall | 6 | 1..50 (internal ceiling; the user setting `recall.max_items` is 1..10) |
| characters per item | 400 | 1..2 000 |
| characters of dynamic recall | 3 000 | up to 50 x 2 000 |
| overall recall wall clock | 400 ms | 100..1 500 |
| lexical leg | 150 ms | 1..1 500 |
| semantic leg (query embedding included) | 250 ms | 1..1 500 |
| Tencent leg | 250 ms | 1..1 500 |

Legs run concurrently. The 1..50 range is the model's internal ceiling, kept
wider than the 1..10 a user may set in `MemorySettings`, so internal callers (the
Memory Center sandbox, tests) can ask for more than the Brain injection uses.
 Brain injection caps (Slice 05) are `profile` 2 048,
6 items, 400 per item, 6 000 characters in total, knowledge manifest 1 024.
`RecallQuery` text is bounded to 2 000 characters; empty `scopes` recall nothing.
Settings (`MemorySettings`): `recall.max_items` 1..10, `recall.timeout_ms`
100..1 500; the settings file itself is Slice 10a.

## Error codes (stable)

`MemoryErrorCode` values travel in routes, MCP results and logs: never rename.

| Code | Meaning |
|---|---|
| `memory_not_found` | unknown note, candidate or asset id |
| `memory_conflict_revision` | `expected_revision` is not the current revision |
| `memory_scope_denied` | the agent's policy does not allow the scope |
| `memory_degraded` | reserved for route-level status (a route answering with a partial result); recall itself never raises it, it reports degradation as data through `DegradedReason` (see below) |
| `memory_unavailable` | disk, root, provider or sidecar in failure |

## Degraded semantics

- Degraded is data, not an exception. A leg that times out or fails does not
  fail the recall: `RecallResult.degraded` lists `DegradedReason` values
  (`lexical_timeout`, `semantic_timeout`, `semantic_unavailable`,
  `semantic_capacity`, `tencent_timeout`, `tencent_unavailable`,
  `recall_timeout`, `store_unavailable`) and the items of the legs that
  finished are used. Lexical keeps working with the provider `none`.
- A candidate decided as `superseded_by_newer` is decided by the system, not a
  person: convention is a system actor name in `decided_by` (for example
  `system`), while `accepted` and `rejected` carry the human or policy actor.
- A retriever raises `MemoryStoreError(memory_unavailable)` only when nothing
  can answer. An `EmbeddingProvider` raises it on failure or timeout; the
  caller converts it to a degraded reason.
- The Brain never waits on a degraded leg beyond the overall timeout, and a
  failure of memory never blocks a turn.
- `CapabilityState`: `ok` carries no reason; `degraded`, `disabled` and
  `unavailable` require a `reason_code` so a UI cannot show plain "on" for a leg
  that does not work.
- Canonical writes never wait on a mirror or an index.

## Settings model

`MemorySettings` (pure dataclasses, `jarvis/domain/memory_settings.py`) defaults
to the safe local configuration: recall on (6 items, 400 ms), semantic off with
provider `none`, consolidation `manual`, Tencent off, Wiki, CodeGraph and Skills
on. Incompatible combinations cannot be built: `semantic.enabled` with provider
`none`, `consolidation.mode=auto` without `semantic.enabled`, `tencent.enabled`
without a URL. There is no secret field: tokens live in `credentials`.

## Canonical store (Slice 02)

`MarkdownMemoryBackend` (`jarvis/adapters/markdown_memory.py`) implements
`CanonicalMemoryStore` and the legacy `MemoryBackend` on one class. Tests:
`tests/unit/test_memory_store_canonical.py`, `test_memory_frontmatter.py`.

### File format

```
---
id: "3f2a9c0e5b7d4e1f8a6b2c4d6e8f0a1b"
level: "L1"
kind: "preference"
scope: "private"
created_at: "2026-10-07T09:00:00+00:00"
updated_at: "2026-10-07T09:30:00+00:00"
revision: 2
confidence: 0.9
sources: [{"type": "turn", "ref": "turn-12", "at": "2026-10-07T09:00:00+00:00"}]
---
# Title

Body.
```

- The block is flat `key: value` lines between two `---` lines. A key is an
  identifier, a value is one line of JSON (scalar, array or object). It is read
  by `jarvis/adapters/memory_frontmatter.py`, an in-house parser: the repository
  has no YAML dependency and does not gain one.
- Written keys: `id`, `level`, `kind`, `scope`, `created_at`, `updated_at`,
  `revision`, `confidence` always; `agent`, `valid_from`, `valid_to`, `sources`,
  `supersedes`, `superseded_by`, `contradicts` only when set. `retention` is
  never written: it is the directory. The title is the first `# ` heading, the
  body is the text after it (leading and trailing blank lines are not kept).
- **Unknown keys are preserved.** A revision rewrites the keys the store owns
  and keeps every other key as it found it.
- **A corrupt block never drops a note.** A metadata line over 65 536 characters, or
  JSON nested so deeply that the parser's stack overflows, counts as corrupt, so
  one hostile file can never stop the index from building. A delimited block that is not strictly
  valid (a line that is not `key: json`, a duplicate key, bad JSON, `NaN`) gives
  empty metadata and the whole file text as the body, block included, so the
  note stays listed and searchable. The raw file is kept in `.history/` when the
  note is next revised. A block missing a field or holding an invalid value
  (`level: "L9"`) falls back to the defaults below and keeps a valid `id`.
- **A file without a block is a legacy note.** Defaults are derived on read and
  never written back unless the note is revised: `id` = `legacy-<hash of the
  relative path>` (stable while the file stays), `level` L1, `kind` fact, scope
  `private`, `confidence` 1, both dates = the file modification time,
  `revision` 1. A body longer than the 64 000-character bound has no note view:
  it is full-text indexed (the legacy `search` finds it) but has no `memory_meta`
  row, so `get`, `list` and `search_ranked` do not return it. Once revised, the note carries a stored `id`, which survives
  moves.

### Layout and legacy notes

- `<memory>/<retention class>/*.md` is canonical; the directory is the class
  (`short_term_memory`, `long_term_memory`, `traumatic_memory`, `eternal_memory`,
  `plastic_memory`). New writes (`create`, and the legacy `append_note`) go to
  the directory of their class, `short_term_memory/` for `append_note`.
- **Legacy `notes/`** (written before Slice 02 by `append_note`) and any file
  outside the five classes are recalled as `long_term_memory` and never moved.
  Revising such a note adds front matter in place.
- Directories starting with `.` or `_` are never indexed or listed:
  `.jarvis` (derived index), `.history` (revisions), `_candidates` (Slice 04).
- Board memory (`boards/<id>/memory`) is not under this root and is never
  written by the store.

### Revisions, history and concurrency

- `revise(id, patch, expected_revision)` writes revision N+1 as a complete temp
  file, copies the previous file to `.history/<id>.rev<N>.md`, then replaces the
  live file (`replace_with_retry`: patient with Windows file locks). A failure
  at any step leaves the old revision untouched, removes the temp file and the
  history copy that never became a revision, and raises
  `MemoryStoreError(memory_unavailable)`.
- A stale `expected_revision` raises `memory_conflict_revision`; the check and
  the write are one critical section of the store lock. The lock is per
  process, and there is no lock file: **two processes writing the same vault can
  lose updates** (a measured run with two writer processes lost 84 of 245
  acknowledged writes). Run one writer process per vault; coordination across
  processes is not built. `create` claims its file name exclusively (`O_EXCL`),
  so a file that appears first is never overwritten (`FileExistsError`).
- `history(id)` returns every revision, oldest first, the current one last. The
  history files are canonical (they are the revisions) and git-free; they are
  excluded from recall.
- Body normalisation: CRLF becomes LF on read, leading and trailing blank lines
  are trimmed, so the note `create` and `revise` return is the normalised one.
  Text that cannot be encoded as UTF-8 (a lone surrogate) is refused with
  `memory_unavailable` before anything is written; the old revision stays.
- `create` and `revise` call `check_level_retention` (a `ValueError` before any
  write). A hand-written note that already breaks the level x retention matrix
  (for example `L3` in `short_term_memory`) cannot take an unrelated patch: the
  store answers `memory_unavailable` naming the level. The way out is a human
  fix of its `level` in the file or its directory, or a revision that sets an
  allowed `level`. `create` refuses an existing id with `memory_conflict_revision`.
- **Provenance reads**: `get(id)` returns `sources` (where it came from and
  when), `created_at`, `updated_at`, `revision` and the links; `history(id)`
  shows how it changed.

### Protected classes

There is no delete in the port, and no automatic path deletes or rewrites a
note in `traumatic_memory` or `eternal_memory`. `revise` on a protected note
always refuses to change `title`, `body`, `level`, `kind` or `confidence`
(`memory_scope_denied`). Links and validity (`superseded_by`, `valid_to`,
`add_sources`, `add_supersedes`, `add_contradicts`) are accepted only with
`human=True`: supersession is a human action. `create` into a protected class is
allowed (the consolidator gates it by policy).

### Path and link defences

A memory id is a token, never a path: `..`, separators, `%2e%2e` and the like
raise `MemorySecurityError` before anything is looked up. The legacy `read`
keeps its traversal checks. Writes refuse a retention directory, `.history` or a
note directory that is a symlink or a Windows junction anywhere in its chain,
and a file name that is not a plain visible `.md` name. A note reached through a
link that leaves the root (or a symlinked file) is neither indexed nor listed.

### Derived index

`<memory>/.jarvis/index.sqlite3` holds the FTS5 table (title and body, front
matter stripped) and `memory_meta` (id, retention, level, kind, scope, revision,
dates, superseded). Delete it, corrupt it, or lose it while running: the next
read recreates and refills it from Markdown, nothing durable is lost.

- **Start** is lazy: construction returns at once, a daemon thread resyncs the
  index (external edits made while Jarvis was stopped are picked up) and every
  read waits for it (60 s ceiling, logged).
- **Every mutation upserts the index** (`create`, `revise`, `append_note`,
  `promote_file`), so recall never lags a write (R3). If the upsert fails the
  write still succeeds and the index is repaired from Markdown.
- `rebuild_indexes()` (and the legacy `rebuild_index()`) refill from the files
  and return the number of notes indexed.

### Search

`search_ranked(query, limit, filters)` returns `RankedMemoryHit` (note id, path,
title, snippet, BM25 score, retention, level, kind, scope, revision, dates,
validity) best first. It has no 10-item cap (ceiling 500). `filters` is a
`MemoryFilters` (scope, retention, level, kind, `include_superseded`, default
excluded); its own `limit` and `offset` are ignored. The legacy `search` keeps
its cap of 10 and its output. Front matter is not indexed.

### Promotion

`promote_file(source_rel, target_class)` copies a note into another class as a
new note (new id, revision 1) with the same file name, so a second call is a
no-op. Its `sources` end with `{note, <source id>, now}` (a source with no stored
id is cited by its relative path); a level the target does not allow drops to
L1. The source stays. `MemoryMaintenanceWorker` uses it for notes carrying
`<!-- jarvis:retain -->`, so a promotion has provenance and reaches the index at
once. Wiring the store into Core recall is Slice 05.

### Memory root

The single root is `<data_root>/memory` (`jarvis/data_root.py`). V1
`runtime.memory_dir` defaults to it (override with `JARVIS_MEMORY_DIR` or
`runtime.memory_dir`); the old default `./data/memory` was inside the
repository. See [local-data.md](local-data.md#mémoire--une-seule-racine).

## Hybrid retrieval (Slice 03)

`HybridRetriever` (`jarvis/core/memory_hybrid.py`) is the `MemoryRetriever`. It
runs its **legs** concurrently and fuses their ranked lists. A leg is a
`RecallLeg` (`jarvis/ports/memory_retrieval.py`): `name`, `async hits(query,
limit, timeout_s) -> LegResult`, `status()`. Lexical is mandatory (it is the
deterministic fallback); semantic and the Tencent slot are optional.

| Module | Role |
|---|---|
| `jarvis/adapters/memory_lexical.py` | `LexicalRetriever`: the store's FTS5 `search_ranked` (BM25), with scope, retention, level, superseded and validity filters. |
| `jarvis/adapters/memory_semantic.py` | `SemanticIndex` (derived vector store, background embedding queue) and `SemanticRetriever` (the leg). |
| `jarvis/adapters/embedding_openai.py` | `OpenAIEmbedder`: optional remote `EmbeddingProvider` (httpx), opt-in. |
| `jarvis/core/memory_fusion.py` | Pure `rrf_fuse` and `pack_items`. |
| `jarvis/domain/memory_leg.py` | `LegHit`, `LegResult`, `LegDegraded` and the validity and text helpers shared by adapters and core. |

**Lexical-only mode** (provider `none`, the default) is `HybridRetriever([LexicalRetriever(store)])`:
no embedding, no vector file, no network, the full feature set of recall.

### Fusion

- **RRF**: `score(note) = sum over legs of 1 / (60 + rank)`, equal weights, the
  first 20 hits of each leg. The sum is `math.fsum`, so it never depends on the
  leg order.
- **Dedup** by `memory_id`, keeping the highest revision seen in any leg (its
  snippet, level and `superseded` flag represent the note). A leg counts a note
  once, at its first rank.
- **Superseded notes are excluded** (judged on that highest revision, so a leg
  with a stale vector cannot resurrect one) unless `RecallQuery.include_history`.
  Notes outside `valid_from <= at < valid_to` are excluded by the legs, again
  unless `include_history`.
- **Ties** (equal score) break by `updated_at` descending, then `memory_id`
  ascending. Ranks recorded in `rank_sources` are the positions after exclusion.
- **Items** carry `rank_sources` (`{"lexical": 1, "semantic": 3}`), `revision`,
  `provenance_ref` (`<retention class>/<memory id>`) and `why`: the legs and
  ranks, then each leg's reason (`terms atlas, budget` for lexical, `cosine 0.81`
  for semantic).

### Budgets and degradation

`pack_items` keeps fused order and applies: at most `max_items`; each snippet
clipped to `max_item_chars` (ending with an ellipsis); the snippets together
never above `max_total_chars` (the last one is clipped to what remains, then
packing stops). Defaults 6 / 400 / 3 000.

Time: lexical 150 ms, semantic 250 ms (query embedding included), Tencent slot
250 ms, overall 400 ms hard (`RecallBudget`). Each leg runs under its own
deadline and the whole recall under the overall one; a leg past its deadline
contributes nothing and adds its reason (`lexical_timeout`, `semantic_timeout`,
`tencent_timeout`), a leg still running at the overall deadline adds
`recall_timeout`. A leg that fails adds `store_unavailable`,
`semantic_unavailable` or `tencent_unavailable`; a partial leg adds its own reason
(for example `semantic_unavailable` while the index is still being built).
`recall` raises `MemoryStoreError(memory_unavailable)` only when every leg failed
outright; a timeout is never that. With an `AgentMemoryPolicy` the requested
scopes are narrowed first and no readable scope means no recall.

### Semantic index (derived)

`<memory>/.jarvis/semantic.sqlite3`: one row per chunk, float32 BLOBs (stored
normalised) keyed `(memory_id, revision, model_id, chunk_no)`, with the filter
facts (scope, retention, level, dates, superseded) and a digest of the note
text. Own `PRAGMA user_version` (1); it is not under the `_MIGRATIONS` rule
because it is never migrated: a different version, a corrupt file or a deleted
file is recreated and re-embedded from the canonical notes. Nothing durable
lives there.

- **Scan**: brute-force cosine (dot product of unit vectors) over the latest
  revision of each note. `numpy` when importable (optional extra), else stdlib
  `array` in pure Python with a deadline check every 256 chunks. The rows are
  kept in memory until the next write.
- **Capacity guard**: more than 20 000 chunks (or a build that would exceed it)
  turns the leg off with `semantic_capacity`; lexical recall continues. The
  guard is re-evaluated by the next `reconcile`.
- **Chunking**: one chunk per note below 1 500 characters of body, else
  paragraph windows of at most 1 500 characters (an oversized paragraph is cut).
  The title is prefixed to every chunk.
- **Never on the write path**: a write only calls `notify_written(memory_id)`
  (any thread, never blocks); a background task (`start()`) embeds and stores.
  The first failure parks the rest of the queue and is retried every 30 s; the
  failure is in `status()` (`semantic_unavailable`) and the log.
- **Rebuild**: a model change (`model_id`) purges the other models' vectors
  and re-embeds; a missing or damaged file is recreated and the leg reports
  `semantic_unavailable` (rebuilding) until `reconcile` completes. A note whose
  `(revision, digest)` is already stored is not re-embedded. Building 5 000 notes
  takes about a minute (it reads every note once).
- **Canonical authority**: each hit is re-read from the store. A note that no
  longer exists, left its scope, is superseded or is outside its validity window
  is dropped, and a deleted note is queued so its vectors go.
- **Cosine floor**: hits below 0.25 (`DEFAULT_MIN_SCORE`) are noise and are not
  returned, so an unrelated note never fills the list. Tune it per retriever for
  the provider in use.

### Remote embeddings and private scopes (risk R12)

`OpenAIEmbedder` is opt-in (`semantic.provider = openai`); the default sends
nothing anywhere. Its key comes from `credentials.secret_for(settings, "openai")`
at each call and never appears in an error or a log. Failure and timeout raise
`memory_unavailable`.

Private scopes never reach it unless `allow_private`: `SemanticIndex` does not
embed a `private` note (and drops any it had) and `SemanticRetriever` searches
only the non-private scopes of the query, sending no query text at all when none
is left. Consequence worth knowing: legacy notes have no front matter and are
scope `private`, so with `allow_private=false` they are found by the lexical leg
only. The query text itself is a user utterance, not stored memory.

### Evidence

`benchmarks/memory_recall.py` (`--notes`, `--queries`, `--no-numpy`, `--json`)
prints p50, p95 and max for each leg on a synthetic FR + EN vault, plus
recall@5 of lexical-only against hybrid on `tests/fixtures/memory_recall/`
(corpus, labelled queries, concept table for `tests/fakes/fake_embedder.py`).
Evidence only, not a CI gate.

## As built

Slices 01 and 02: contracts and the canonical Markdown store. `MarkdownMemoryBackend`
implements `CanonicalMemoryStore` and the legacy `MemoryBackend`; it is built by V1
(`runtime/factory.py`, `app.py` `_reindex`) and by the V2 maintenance worker
(`app.py`). Core does not use it for recall yet (retrievers: Slice 03, Core
wiring and Brain injection: Slice 05). The legacy `append_note` writes to
`short_term_memory/` (same bytes as before) instead of `notes/`.

Slice 03: hybrid retrieval. `HybridRetriever` over a lexical leg and an optional semantic leg (derived `semantic.sqlite3`), fused by RRF, with per-leg and overall time budgets and degraded reasons. Core wiring and Brain injection are still Slice 05; the Tencent leg is Slice 06.
