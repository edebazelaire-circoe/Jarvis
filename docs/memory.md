# Memory contracts

Contract page of the memory, intelligence and knowledge handoff
(`jarvis-memory-intelligence-knowledge`). Slice 01 defines **contracts only**:
pure models and ports, no persistence, no wiring. The canonical store arrives in
Slice 02, retrieval in Slice 03, consolidation in Slice 04, Brain injection in
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
| **Scope** | Who may see a note: `private`, `shared`, `board:<id>`, `project:<id>`. Matched exactly, deny by default. |
| **Agent memory policy** (`AgentMemoryPolicy`) | Per-agent read and write scopes. `private` needs an explicit `allow_private`. |
| **Knowledge asset** | Wiki page, CodeGraph snapshot or Skill under `<data_root>/knowledge`. Imported or derived, never canonical memory. Always has a `SourceRef`. |
| **Loadout** | What one agent profile (plus optional role) may see: memory scopes, wiki ids, codegraph repos, skill ids. Default is nothing (`NullLoadoutResolver`). |
| **Capability state** | `ok`, `degraded`, `disabled` or `unavailable` for one leg, with a stable `reason_code` whenever it is not `ok`. |
| **Board memory** | A separate, mature system (`BoardMemoryStore`, WSP). Not merged: it is a peer source with scope `board:<id>`, read-only to the new retriever. |
| **CONTEXT_GLOBAL** | Brain bootstrap instructions (`<data_root>/CONTEXT_GLOBAL`). **Not memory**: never indexed, consolidated or recalled by memory modules. The L3 profile reaches the Brain through the per-turn memory block, never by writing into CONTEXT_GLOBAL. |
| **Legacy `MemoryBackend`** | `jarvis/ports/memory.py`, unchanged. Mixes search, read, append and rebuild. The Markdown adapter will implement it and the new ports side by side. Its `notes/` directory is an unclassified legacy class, recalled as `long_term_memory` and never moved. |

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

## Metadata schema (`MemoryNote`)

A note is a Markdown file with a flat `---` front-matter block (`key: value`
lines, values are JSON scalars or arrays; Slice 02 owns the parser). A file
without front matter is a valid legacy note: defaults are derived lazily and
written back only when the note is mutated.

| Field | Type | Rule |
|---|---|---|
| `id` | token <= 64 | stable identity, independent of the path (`new_memory_id()`, assigned by the caller of `create`) |
| `title` | one line <= 200 | required |
| `body` | text <= 64 000 | the note |
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

## Ports

| Port | Methods | Notes |
|---|---|---|
| `CanonicalMemoryStore` | `get(id)`, `list(filters)`, `create(note)`, `revise(id, patch, expected_revision)`, `history(id)`, `rebuild_indexes()` | Synchronous (disk), called through a thread. |
| `MemoryRetriever` | `async recall(query, budget)`, `status()` | One implementation per leg or hybrid. |
| `EmbeddingProvider` | `model_id`, `dim`, `async embed(texts, timeout)` | Default provider is `none`. |
| `MemoryConsolidator` | `async propose(evidence)`, `async decide(candidate_id, decision, actor)` | Idempotent per evidence hash. |
| `CandidateExtractor` | `async extract(evidence)` | Output is untrusted, schema-validated by the consolidator. |
| `KnowledgeAssetProvider` | `kind`, `status()`, `list(scope)`, `search(query, limit, scope)`, `read(id)`, `rebuild()` | `list` and `search` return assets without body. |
| `LoadoutResolver` | `resolve(profile, role)` | `NullLoadoutResolver` grants nothing until Slice 09. |
| `CapabilityReporter` | `capability_id`, `status()` | Cheap, never raises, no synchronous network probe. |

## Budgets

Defaults of `RecallBudget` (hard ceilings are the model bounds):

| Budget | Default | Range |
|---|---|---|
| items per recall | 6 | 1..50 |
| characters per item | 400 | 1..2 000 |
| characters of dynamic recall | 3 000 | up to 50 x 2 000 |
| overall recall wall clock | 400 ms | 100..1 500 |
| lexical leg | 150 ms | 1..1 500 |
| semantic leg (query embedding included) | 250 ms | 1..1 500 |
| Tencent leg | 250 ms | 1..1 500 |

Legs run concurrently. Brain injection caps (Slice 05) are `profile` 2 048,
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
| `memory_degraded` | a result is usable but partial (reported as data, see below) |
| `memory_unavailable` | disk, root, provider or sidecar in failure |

## Degraded semantics

- Degraded is data, not an exception. A leg that times out or fails does not
  fail the recall: `RecallResult.degraded` lists `DegradedReason` values
  (`lexical_timeout`, `semantic_timeout`, `semantic_unavailable`,
  `semantic_capacity`, `tencent_timeout`, `tencent_unavailable`,
  `recall_timeout`, `store_unavailable`) and the items of the legs that
  finished are used. Lexical keeps working with the provider `none`.
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

## As built

Slice 01 only: contracts. The Markdown adapter, retrievers, service and routes do
not exist yet. `MemoryBackend` and `MarkdownMemoryBackend` are unchanged.
