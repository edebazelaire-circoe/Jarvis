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
  `recall_timeout`, `store_unavailable`, `leg_busy`) and the items of the legs that
  finished are used. Lexical keeps working with the provider `none`.
- A candidate decided as `superseded_by_newer` is decided by the system, not a
  person: the system actor is `system.consolidation` in `decided_by` (any actor
  starting with `system.` is a system actor and `ConsolidationPipeline.decide`
  refuses it, in any case: `System.consolidation` is a system actor too), while `accepted` and `rejected` carry the human actor, or
  `system.consolidation` for an `auto` commit.
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
| `jarvis/adapters/memory_leg_pool.py` | `LegPool`: a leg's own bounded thread pool, `leg_busy` when saturated. |
| `jarvis/adapters/embedding_openai.py` | `OpenAIEmbedder`: optional remote `EmbeddingProvider` (httpx), opt-in. |
| `jarvis/core/memory_fusion.py` | Pure `rrf_fuse` and `pack_items`. |
| `jarvis/domain/memory_leg.py` | `LegHit`, `LegResult`, `LegDegraded` and the validity and text helpers shared by adapters and core. |

The optional Tencent sidecar leg (`jarvis/adapters/tencent_memory.py`) is specified in [memory-tencent.md](memory-tencent.md).

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
(for example `semantic_unavailable` while the index is still being built, or
while a note the provider refuses is left out). A leg whose previous calls are
all still running is skipped with `leg_busy` (see below).
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
  kept in memory and **moved forward by each write** (copy-on-write, no rebuild
  from the file), so a recall never pays for a write. Measured with
  `benchmarks/memory_recall.py --snapshot`, 512 dimensions, search right after
  one write: 2 000 chunks 78 ms before, 1.5 ms after (numpy), 115 ms before and
  43 ms after (pure Python); 20 000 chunks 1 135 ms before, 12.9 ms after
  (numpy), 1 563 ms before and 451 ms after (pure Python). The pure-Python scan
  of 20 000 chunks at 512 dimensions is over the 250 ms leg budget and reports
  `semantic_timeout`: install numpy (or lower the dimension) for a large vault.
- **Capacity guard**: more than 20 000 chunks (or a build that would exceed it)
  turns the leg off with `semantic_capacity`; lexical recall continues. The
  flag clears by itself when removals bring the chunk count back to the
  capacity (a reconcile is then owed to refill what was refused) and at the
  start of every `reconcile`.
- **Chunking**: one chunk per note below 1 500 characters of body, else
  paragraph windows of at most 1 500 characters (an oversized paragraph is cut).
  The title is prefixed to every chunk.
- **Never on the write path**: a write only calls `notify_written(memory_id)`
  (any thread, never blocks); a background task (`start()`) embeds and stores.
  A note the provider refuses (an error, a zero or non-finite vector) is
  parked and the others go on; it is retried later with a doubling delay (30 s,
  1 min, ... one hour) and at once when it is written again. A run of three
  failures, or no success at all, means the provider is down: the pass stops
  and is retried every 30 s. Either way the failure is in `status()`
  (`semantic_unavailable`), in `RecallResult.degraded` and in the log.
- **Damage while running**: a garbled, truncated or empty file (found on the
  next read or write) is recreated and a full reconcile is owed; the leg
  reports `semantic_unavailable` until it completes. Nothing durable is lost.
- **Threads**: each leg owns a small bounded pool (2 workers). A store call that
  hangs never starves the loop's shared executor, and once both workers of a leg
  are still busy the next recalls skip that leg with `leg_busy` instead of
  queueing behind them. A cancelled recall cancels its leg tasks.
- **Rebuild**: a model change (`model_id`) purges the other models' vectors
  and re-embeds; a missing or damaged file is recreated and the leg reports
  `semantic_unavailable` (rebuilding) until `reconcile` completes. A note whose
  `(revision, digest)` is already stored is not re-embedded. Building 5 000 notes
  takes about a minute (it reads every note once).
- **Canonical authority**: each hit is re-read from the store. A note that no
  longer exists, left its scope, is superseded or is outside its validity window
  is dropped, and a deleted note is queued so its vectors go.
- **Cosine floor**: hits below 0.18 (`DEFAULT_MIN_SCORE`) are noise and are not
  returned, so an unrelated note never fills the list. The value is deliberately
  low: short queries against `text-embedding-3-small` often score 0.25 to 0.45
  for relevant notes, and a higher floor would cut real recall. It is a
  constructor parameter of `SemanticRetriever`. It is a starting point, not a
  calibration: measuring it on a real model is a human-validation item
  (H4/H5), with `JARVIS_MEMORY_REAL_EMBED=1 python benchmarks/memory_recall.py
  --real-embed`.

### Remote embeddings and private scopes (risk R12)

`OpenAIEmbedder` is opt-in (`semantic.provider = openai`); the default sends
nothing anywhere. Its key comes from `credentials.secret_for(settings, "openai")`
at each call and never appears in an error or a log. Failure and timeout raise
`memory_unavailable`. The answer is read as a stream and refused above 16 MiB;
an answer with a missing or duplicate `index`, a boolean where a number is
expected, a wrong size or a non-finite value is refused. A zero vector from any
provider is refused too (it has no direction).

Private scopes never reach it unless `allow_private`: `SemanticIndex` does not
embed a `private` note (and drops any it had) and `SemanticRetriever` searches
only the non-private scopes of the query, sending no query text at all when none
is left. Consequence worth knowing: legacy notes have no front matter and are
scope `private`, so with `allow_private=false` they are found by the lexical leg
only. The query text itself is a user utterance, not stored memory.

### Evidence

`benchmarks/memory_recall.py` (`--notes`, `--queries`, `--no-numpy`, `--json`,
`--snapshot`, `--real-embed`) prints p50, p95 and max for each leg on a
synthetic FR + EN vault, plus recall@5 of lexical-only against hybrid on
`tests/fixtures/memory_recall/`. Evidence only, not a CI gate.

**What the recall fixtures prove.** The corpus, the labelled queries and the
concept table of `tests/fakes/fake_embedder.py` (which places chosen synonyms and
translations together) check the **wiring**: the vector leg is queried, fused,
hydrated and filtered, and lexical recall is not hurt. They do not measure the
semantic quality of a real model. Controls: with an empty concept table the
paraphrase gain is zero, and a held-out set (`queries_heldout.json`) shows no
gain for words outside the table. Quality on a real model is measured by the
opt-in `--real-embed` run (network, an OpenAI key), which prints the cosine of
relevant against irrelevant pairs and recall@5 per cosine floor.

## Consolidation (Slice 04)

Code: `jarvis/core/memory_consolidation.py` (pipeline, state machine, policy gate),
`jarvis/adapters/memory_candidates.py` (file-backed candidate store, port
`jarvis/ports/memory_candidates.py`), `jarvis/adapters/memory_extractor_llm.py`
(LLM extractor), `jarvis/core/memory_maintenance.py` (the daily worker). Tests:
`tests/unit/test_memory_consolidation_*.py`, fakes `tests/fakes/fake_extractor.py` and
`tests/fakes/consolidation_harness.py`.

### Pipeline

```
L0 evidence (turn excerpt, short-term note)
  -> CandidateExtractor            LLM in production, a fake in tests; output is UNTRUSTED
  -> schema validation             strict; one bad proposal is dropped with a diagnostic, the rest go on
  -> dedup                         lexical (Jaccard >= 0.8) + semantic (optional) vs durable notes and pending candidates
  -> conflict detection            related note of the same kind (Jaccard >= 0.5, or embedding cosine >= 0.9)
  -> scoring                       extractor confidence, capped at 0.4 when the evidence reads like an injection
  -> policy gate                   manual: a human decides; auto: threshold + no conflict + allowed class
```

- **Idempotence.** The unit is one evidence item, keyed by a hash of (scope, text, source type and ref); the time
  is not part of it. A run marker (`_candidates/.runs/<hash>.json`) records what an item produced, so only unseen
  evidence reaches the extractor. Candidate ids and committed note ids are derived from content, so a replay
  converges instead of duplicating. An extractor failure leaves the evidence unmarked: it is retried next run.
- **Scope.** The candidate's scope is the evidence's scope, always. Evidence is extracted per scope, so private
  evidence never yields a shared note and never reaches an extraction that holds shared evidence. An extractor
  that names a `scope` is dropped (`unknown_fields`). Dedup and conflicts compare inside one scope only.
- **Short-term notes are the evidence pool.** Dedup and conflict detection compare against durable classes
  (`long_term`, `plastic`, `traumatic`, `eternal`), so a candidate extracted from a short-term note is not a
  "duplicate" of its own source.
- **Batches.** Evidence goes to the extractor in batches of at most 40 items and 60 000 characters (the adapter refuses more, so nothing is cut silently); each batch is marked processed on its own, so a failed batch is the only one retried.
- **Cap.** `max_candidates_per_run` bounds the candidates a run writes, best confidence first. Proposals beyond it are **kept for the next run**, not lost: the batch is left unmarked, the next run extracts again and the candidates already written are recognised by id and not counted. Later groups are deferred, unmarked.
- **Neighbours.** Dedup and conflicts compare with the newest 200 durable notes, plus the best full-text matches (`search_ranked`, 30) and the retriever's top 30, so an old near-duplicate is not missed behind newer notes.
- **Diagnostics.** Every drop, duplicate, refusal, commit and recovery is an event on the injected sink
  (`memory.consolidation.*`; counts and ids, never evidence or proposal text) and in `ConsolidationReport`.

### Extractor schema (untrusted Mappings)

Allowed keys: `title`, `body`, `kind`, `level`, `retention`, `confidence`, `supersedes` (hints), `reason`. Anything
else drops the proposal (`unknown_fields`): an extractor cannot set a scope, id, state, decision or commit id.
`title` is one printable line of at most 200 chars and not path-like; `body` at most 4 000 chars, no NUL;
`confidence` a finite number in 0..1; `level` L1..L3 (L0 is evidence); `retention` one of `short_term_memory`,
`long_term_memory` (default), `plastic_memory` and a level its class allows (`check_level_retention`). `traumatic`
and `eternal` are refused (`protected_class`). `supersedes` is a list of at most 8 note ids that are **hints only**:
each must exist, share the scope and be neither protected, short-term evidence nor superseded, and then only adds a conflict (a human still decides). The extractor is shown the ids it may cite: up to 8 related durable notes of the **same scope** (id, title, one-line snippet; never protected, never a private note in a shared context) go into the prompt as data (`CandidateExtractor.extract(evidence, related)`, `RelatedNote`). The model is asked to write `title`, `body` and `reason` in the language of the evidence; keys and enumerated values stay English.

### Candidate state machine

```
            decide(accept)  -> accepted             (commits one canonical note, with provenance)
proposed -- decide(reject)  -> rejected
            newer pending   -> superseded_by_newer  (system actor)
```

`accepted`, `rejected` and `superseded_by_newer` are final (`CANDIDATE_TRANSITIONS`). A retry of the same decision
returns the decided candidate; any other decision on a decided candidate is `memory_conflict_revision`; an unknown
id is `memory_not_found`. `decided_by` is the human actor, or `system.consolidation` for `superseded_by_newer`, an
`auto` commit, and a duplicate found at the gate (rejected). Candidates are Markdown files, `_candidates/<id>.md`
(front matter + `# Title` + body), editable by hand before a decision, never recalled, never auto-deleted.

### Policy gate and knobs

| Knob (`consolidation.*`) | Default | Effect |
|---|---|---|
| `mode` | `manual` | `manual`: nothing is committed; every candidate waits for `decide`. `auto`: opt-in, see below. |
| `auto_min_confidence` | 0.8 | `auto` commits only `confidence >= auto_min_confidence`, and never below the hard floor 0.5. |
| `max_candidates_per_run` | 20 | cap per run (1..100). |

`auto` commits a candidate only when all hold: `confidence >= max(auto_min_confidence, 0.5)`, no conflict (re-checked
against the store at the gate), retention in `long_term_memory` or `plastic_memory`, a level that class allows,
at least one source. It never writes a protected class, never rewrites or supersedes a note, and a duplicate found at
the gate is rejected, not committed. The policy reads the candidate and the settings only, never the evidence text.
`auto` settles only the candidates **created by the current run**: switching `manual` to `auto` never commits a waiting backlog, which stays `proposed` until a human decides (an explicit settle-backlog call may be added later). If a commit fails in a run, that evidence stays unmarked so the next run settles those candidates again.

**`auto` needs dedup.** With neither a retriever nor an embedder wired, `auto` refuses to commit: the run still proposes (as `manual`), and the report says `degraded: ["auto_needs_dedup"]` with a `memory.consolidation.auto_refused` event.

**Prompt injection.** The evidence is JSON data inside random-keyed markers, the system prompt says it is untrusted,
the output must be one strict JSON object, and the consolidator validates every field. Evidence that matches
instruction-like patterns ("ignore previous instructions", "set confidence", "auto-accept", ...) caps the resulting
scores at 0.4, which is under the auto floor: such a candidate waits for a human. The pattern list is a heuristic
(defence in depth), not the safety mechanism; the gate is.

### Conflicts and temporal supersession

A candidate is a **conflict** with a durable note of the same scope and kind that is related (Jaccard >= 0.5 after
stopword removal, or embedding cosine >= 0.9) but not a duplicate (Jaccard >= 0.8, or cosine >= 0.97 with Jaccard >=
0.5), or that an extractor hint named. Semantic similarity only widens review; it never drops a candidate alone,
because an embedding cannot tell "dark mode" from "light mode". A conflicting candidate stays `proposed` with
`conflicts` listing the notes, in every mode.

On a human `accept`, per conflicting note (all rules in `ConsolidationPipeline._plan_links`):

| Situation | Result |
|---|---|
| kind `preference` or `profile`, old note not protected, evidence not older than the old note | **supersession**: the new note carries `supersedes`, `valid_from`; the old note gets `valid_to` (closed at the evidence time), `superseded_by`, revision N+1 and its revision N stays in `.history/`. It leaves recall; `include_superseded` still shows it. |
| any other kind, or evidence older than the old note | **contradiction**: both notes get `contradicts` links and both stay valid; a human resolves it later. |
| old note protected (`traumatic`, `eternal`) | one-way `contradicts` link on the new note; the protected file is never touched, not even by a human accept. |

Nothing is ever overwritten. Two pending candidates of a temporal kind in the conflict band: the one with the
newer evidence wins (the other becomes `superseded_by_newer`); a late arrival with older evidence is dropped
(`stale_vs_pending`). Other kinds stay side by side.

### Crash safety

Order of a commit: (1) write `_candidates/.intents/<id>.json` (decision and actor), (2) create the note (id derived
from the candidate id), (3) close the superseded notes and link the contradicted ones, (4) mark the candidate
`accepted`, (5) remove the intent. A crash anywhere is finished by `recover()` (run at the start of every `run`, and
callable) with the original actor, or by repeating `decide`: the existing note is reused, so no duplicate. A crash
between writing candidates and the run marker converges on the next run (same ids; a reworded proposal is absorbed
by dedup against the pending candidate). Tested by failing every mutating call in turn.

### Degraded results

`run` and `propose` do not raise for a refused path (a symlink or junction in the memory root): the report carries
`degraded: ["memory_unavailable"]` and `errors: ["memory_security:MemorySecurityError"]`. `decide` turns it into
`memory_unavailable`, and a malformed candidate id into `memory_not_found`.

### Maintenance worker

`MemoryMaintenanceWorker(root, store, consolidator=None)` runs the `jarvis:retain` rule first (one policy rule,
explicit marker, provenance added by `promote_file`), then, when a consolidator is wired, offers the newest 100
short-term notes as evidence (`short_term_evidence`) to `ConsolidationPipeline.run`. A pipeline failure is logged and
reported as `{"consolidation": {"error": ...}}`; it never undoes the retain rule. The daily schedule is unchanged.

### LLM extractor

`LlmCandidateExtractor(TextModel)`: prompt builder, strict response parser (`parse_response`), and a seam
(`TextModel.complete`). `CliTextModel` reuses the existing CLI agent (`back_brain_worker.create_job_agent`) with the
`speculative_analysis` profile, which the CLI enforces as zero tools; the model is the routing policy's `fast` profile
(`resolve_profile_model`). If the host CLI cannot run that profile it fails closed. **Not exercised against a real
model in this slice** (no network in tests): the prompt is a working default and needs an `agent-trace-analysis` pass
on a real trace.

### Wiring (for Slice 05's `memory_wiring`)

Core must not import adapters (`test_v2_architecture`), so the adapters are built where adapters may be imported
(today `jarvis/app.py` builds the worker) and the pipeline is handed to Core by injection:

```python
store = MarkdownMemoryBackend(memory_root)                      # one store, shared with the retriever
candidates = FileCandidateStore(memory_root)
extractor = LlmCandidateExtractor(CliTextModel(
    settings=lambda: agent_execution,                           # AgentExecutionSettings, as for back_brain
    model=lambda: resolve_profile_model("fast", routing_policy(), routing_candidates()),
))
pipeline = ConsolidationPipeline(
    store=store, candidates=candidates, extractor=extractor,
    settings=lambda: current_memory_settings().consolidation,   # mtime-cached read, applies on the next run
    retriever=hybrid_retriever,                                 # `auto` needs a retriever or an embedder
    sink=lambda event, data: journal.emit(event, event, data=dict(data)),
)
workers["memory_maintenance"] = MemoryMaintenanceWorker(memory_root, store, pipeline)
```

Routes (`POST /v1/memory/candidates/<id>/decision`, 05/05b/12) delegate to the pipeline:
`await pipeline.candidates(state)` (list), `await pipeline.candidate(id)` (get),
`await pipeline.decide(id, CandidateDecision(decision), actor)`. Map `memory_not_found` to 404,
`memory_conflict_revision` (already decided) to 409, `memory_scope_denied` (system actor, protected class) to 403,
`ValueError` (bad actor token) to 400, `memory_unavailable` to 503. The actor is the authenticated human, never a
`system.*` name.

## Injection into the Brain context (Slice 05)

Core builds a bounded `memory` block for every Brain turn and the Control Center
renders it in the agent's brief. Same pattern as the Board block
(`jarvis/core/board_hydration.py`): the Brain stays the only context authority,
nothing is proxied, and the reflex / voice model has **no memory tool**
(`tests/unit/test_memory_brain_injection.py` pins the Realtime tool set). Not
`CONTEXT_GLOBAL`: that file is Brain bootstrap instructions, never memory, never
indexed or recalled (decision D7).

```
user turn
  -> BrainOrchestrator._call_backend
       |-- work / board / session_context / prefab_events   (existing blocks)
       '-- _turn_memory (task, concurrent) -> MemoryTurnContext(turn)
                |- settings   CachedMemorySettings (file, re-read <= every 2 s)
                |- query      utterance (+ previous user turn if < 8 words)
                '- MemoryService.recall_for_turn
                       |- profile  store.list(L3, L2 kind=profile)   (thread)
                       '- recall   HybridRetriever (lexical || semantic || tencent)
       -> BrainContext.memory (BrainMemoryContext)
  -> control_center_brain._turn_context   context["memory"] only when non-empty
  -> control_center.build_agent_brief     "[Mémoire à long terme]" block
```

Block (`BrainMemoryContext`, `jarvis/domain/brain_context.py`), keys omitted when empty:

| Key | Content | Budget |
|---|---|---|
| `profile` | stable block: notes of level L3 and L2 `kind: profile`, newest first, each with `[<class>/<id> r<revision>]` | 2 048 chars |
| `recall` | up to 6 items `{id, title, text, level, retention, source, revision, why}`; `source` is the canonical address `<class>/<id>` | 400 chars per item, 3 000 chars of text |
| `omitted` | items dropped by a budget (whole items, never half) | |
| `knowledge_manifest` | names and ids of the Brain loadout (wiki, codegraph, skills), never bodies; empty with `NullLoadoutResolver` | 1 024 chars |
| `degraded` | stable codes: `recall_timeout`, `index_syncing`, `store_unavailable`, `profile_unavailable`, `semantic_timeout`, `semantic_unavailable`, `semantic_capacity`, `lexical_timeout`, `tencent_*` | 8 codes |
| `error` | `memory_failed` (a defect in the builder) or a store code | |

The whole block is at most 6 000 characters of compact JSON (the same as the work
block, a separate budget). `BrainMemoryContext.bounded` cuts every text on a whole
character (ending with an ellipsis), keeps items whole in order while the item
count, the 3 000 characters of recall text and the 6 000 characters of block hold,
counts the rest in `omitted`, and shortens the profile last. The settings range
`recall.max_items` 1..10 is capped at 6 by the injection ceiling.

Rules:

- **Query**: the user utterance, plus at most one recent user turn (300 characters)
  when the utterance has fewer than 8 words. No LLM call. The query is never logged,
  never put in a diagnostic, never in the block.
- **Time**: the whole build runs under `recall.timeout_ms` (default 400 ms, range
  100..1 500). The retriever's own wall clock is 50 ms shorter, so it answers with
  its partial result and `degraded` codes before the backstop fires; the backstop
  yields `degraded: ["recall_timeout"]`. Blocking disk I/O is in a thread. The
  memory task runs concurrently with the other per-turn blocks: it adds nothing
  to their sum.
- **Failure isolation**: a store that is missing, refused or slow, a failing
  profile listing, a defect in the builder: the turn goes on with a degraded or
  error block (or none). Nothing raises into the orchestrator.
- **Index sync (amendment A2)**: while the store's start-up index sync runs
  (about 1.3 s warm / 10 s cold for 2 000 notes) a turn recall is *not* attempted
  and the block says `index_syncing`; a turn never parks a thread on that wait.
- **Settings**: `memory.recall.enabled=false` turns the whole block off (no
  profile either) from the next turn; timeout and item count too. File re-read at
  most every 2 s, parsed again only when it changed. Turning semantic recall on
  or off, or changing its provider, applies at the next Core start.
- **Scopes**: the Brain policy reads `private` and `shared` (`brain_policy()`).
  Deny by scope: a policy that grants nothing recalls and lists nothing; a private
  note is never injected when the policy forbids it, and never embedded unless
  `semantic.allow_private`. A superseded note or one outside its validity window
  is never injected (profile included).
- **Trace**: Core diagnostics `core.brain.memory_context_delivered` and
  `core.brain.memory_context_failed` carry counts (`items`, `omitted`,
  `profile_chars`, `manifest_chars`), `degraded` codes and timings, never a memory
  text. The Control Center trace keeps only the size of the memory block
  (`mask_room_text`).
- **Rendering** (`jarvis/runtime/memory_brief.py`): the block is framed as
  information held by Jarvis (possibly old, possibly from automatic
  consolidation), not instructions; a line that looks like a brief header or a
  delimiter is neutralised; a degraded recall is said to the agent so it does not
  conclude nothing was said. An absent, empty or out-of-contract block gives no line:
  the brief is byte-identical to before.

Measured on 2 000 legacy notes, lexical only, dev machine
(`tests/unit/test_memory_context.py`, run with `-s`): index sync 10.9 s cold;
recall block alone p50 9 ms, p95 10 ms, max 14 ms; turn wall time with a concurrent
150 ms builder p50 155 ms, p95 157 ms (the recall hides behind the slowest builder).

## Core wiring (Slice 05)

`jarvis/core/memory_wiring.py` is the single composition: `build_memory_wiring(data_root,
settings_path, adapters, ...)` builds the store (`<data_root>/memory`), the lexical leg, the
optional semantic index and leg, `HybridRetriever`, `MemoryService` and
`MemoryTurnContext`. The concrete adapters arrive as an injected `MemoryAdapters`
(`core` imports no adapter and nothing from the runtime layer, enforced by
`tests/unit/test_v2_architecture.py`); `jarvis/runtime/memory_composition.py`
(`build_default_memory_wiring`) binds the real ones. `jarvis/app.py` builds it once, passes the same store to
`MemoryMaintenanceWorker` and the wiring to `JarvisCoreApplication(memory=...)`
(Core without it, as in most tests, has no block and answers `memory_unavailable`).

- A root that cannot be opened (a file in its place, a refused disk) gives a wiring
  without store: Core starts, every turn carries `degraded: ["store_unavailable"]`,
  the routes answer `memory_unavailable` 503, the maintenance worker is not mounted;
  `core.memory.unavailable` is journaled. It is built again at the next start.
- Every store mutation (`create`, `revise`, `promote_file`) notifies the semantic
  index (`notify_written`); embeddings are computed in the background. A listener
  that fails never fails the canonical write.
- Hooks for later slices: `register_retriever(leg)` (Slice 06, the Tencent leg;
  the hybrid is rebuilt, a duplicate name is refused), `register_write_listener(cb)`
  (mirror sink), `register_knowledge(provider)` and `set_loadout_resolver(resolver)`
  (Slice 09: replaces `NullLoadoutResolver`; the manifest then fills).

## Core routes (Slice 05)

Token-protected (`jarvis/protocol/memory_routes.py`). Read-only except `POST /v1/memory/candidates`, which
only writes a candidate. The Control Center relay is Slice 10b; the Brain tools' relay (`/api/memory/brain/*`)
is Slice 05b.

| Method | Route | Answer |
|---|---|---|
| GET | `/v1/memory/notes[?scope&retention&level&kind&include_superseded&limit&offset]` | latest revisions with an excerpt, newest first |
| GET | `/v1/memory/notes/{memory_id}` | one note whole: body, sources, links, revision |
| GET | `/v1/memory/search?q=[&scope&retention&level&limit]` | lexical BM25 hits over every scope (derived, labelled so) |
| GET | `/v1/memory/status` | one state per leg (`store`, `lexical`, `semantic`, `tencent`, `knowledge:*`) with `status`, `reason_code`, `reason` |
| GET | `/v1/memory/recall-explain?q=[&scope&max_items]` | what the Brain would be given for `q`: rank per leg, `why`, timings, `degraded`, budget |
| GET | `/v1/memory/candidates` | `{"candidates": [], "available": false}` until the consolidation slice supplies a provider |
| POST | `/v1/memory/candidates` | **Slice 05b.** The Brain's `memory_propose`: body `{title, body?, kind?, level?, retention?, confidence?, reason?, scope?}`; creates one `proposed` candidate (201, or 200 `already_proposed`), never a note |
| GET | `/v1/memory/brain/search?q=[&limit]` | **Slice 05b.** Brain recall on demand: canonical text with source and revision, narrowed by the Brain policy, superseded never offered |
| GET | `/v1/memory/brain/notes/{memory_id}` | **Slice 05b.** One note for the Brain (text up to 6 000 characters); a scope outside the policy is `memory_scope_denied` |
| GET | `/v1/memory/brain/knowledge/search?q=[&kind&limit]` | **Slice 05b.** Wiki, CodeGraph and skills hits limited to the Brain loadout |
| GET | `/v1/memory/brain/knowledge/{kind}/{asset_id}` | **Slice 05b.** One loadout asset (text up to 8 000 characters, version, `stale`) |

`notes`, `search` and `status` serve the owner (the Memory Center) and are not
narrowed by the Brain policy; `recall-explain` is. Errors are `{"error": {"code",
"message"}}`: `memory_not_found` 404, `memory_scope_denied` 403,
`memory_conflict_revision` 409, `memory_unavailable` 503, `invalid_request` 400,
`core_unavailable` 503, `memory_failed` 500; each is journaled as
`core.memory.read_failed` with its code, never with the query.

### Brain tools (Slice 05b)

The `jarvis-memory` MCP server (`docs/mcp/tool-contract.md` section 10.15) calls the five Brain routes above through the
Control Center. `BrainMemoryTools` (`jarvis/core/memory_tools.py`) holds the rules: 3 tool calls per Brain turn
(`429 memory_tool_budget_exceeded`, reset by `MemoryService.begin_turn()` from the context builder on a user turn), reads under
the Brain policy, knowledge under the Brain loadout, and `propose` = one `proposed` candidate in `_candidates/` (confidence
capped at 0.6, scope must be one the Brain reads, default `shared`). A refused call (bad schema, denied scope) still counts
against the budget of the turn.

## As built

Slices 01 and 02: contracts and the canonical Markdown store. `MarkdownMemoryBackend`
implements `CanonicalMemoryStore` and the legacy `MemoryBackend`; it is built by V1
(`runtime/factory.py`, `app.py` `_reindex`) and by the V2 maintenance worker
(`app.py`). Core recalls from it since Slice 05 (retrievers: Slice 03, Core
wiring and Brain injection: Slice 05). The legacy `append_note` writes to
`short_term_memory/` (same bytes as before) instead of `notes/`.

Slice 03: hybrid retrieval. `HybridRetriever` over a lexical leg and an optional semantic leg (derived `semantic.sqlite3`), fused by RRF, with per-leg and overall time budgets and degraded reasons. Core wiring and Brain injection: Slice 05 (below); the Tencent leg is Slice 06.

Slice 04: consolidation pipeline (see Consolidation above). Default `manual`; `auto` is opt-in. Core wiring (`memory_wiring`, routes) is Slice 05; the real-model extractor trace is still to do.

Slice 05: Core wiring and Brain injection (*Injection into the Brain context*, *Core wiring*, *Core routes* above). `MemoryService` (`jarvis/core/memory_service.py`), `MemoryTurnContext` (`jarvis/core/memory_context.py`), `build_memory_wiring` (`jarvis/core/memory_wiring.py`), `/v1/memory/*` (`jarvis/protocol/memory_routes.py`), `BrainMemoryContext` and `BrainContext.memory`, `BrainOrchestrator(memory_context=...)`, `jarvis/runtime/memory_brief.py` for the agent brief. Open points: the settings range 1..10 of `recall.max_items` is capped at 6 by the injection ceiling; `RecallItem` carries no `updated_at`, so an injected item shows source, revision, level and class but no timestamp; board-scoped memory (`board:<id>`) is not part of the Brain policy yet; semantic on/off and provider changes need a restart.
