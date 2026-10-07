# Resolved architecture (Slice 00, binding)

Binding for all slices. Slice 00 output, baseline `5ee4345`. Where this document contradicts a `SLICE.md` template, this document wins. A slice that needs to deviate stops and asks the Project Manager (PM) for an amendment. It does not improvise.

## 1. Handoff vs repo: drift list and resolutions

| # | Handoff assumption | Repo reality (verified) | Resolution |
|---|---|---|---|
| D1 | "Evolve the current MemoryBackend memory" | `MarkdownMemoryBackend` (`jarvis/adapters/markdown_memory.py:23`) is built only by the V1 path: `jarvis/runtime/factory.py:39` and `jarvis/app.py:256` (the `_reindex` command). V2 (`JarvisCoreApplication`, `jarvis/core/v2_app.py`) never instantiates it. V2 only runs `MemoryMaintenanceWorker(settings.data_root / "memory")` (`jarvis/app.py:692`, scheduled at `v2_app.py:548-559`). | Slice 02 gives V2 a real canonical store at `<data_root>/memory`. Slice 05 wires it into Core. Both paths use the same adapter. |
| D2 | One memory root | Two roots. V1 `runtime.memory_dir` defaults to `./data/memory` (`jarvis/config.py:143`), which is in the repo, and `data/memory/Jarvis-V1.md` is tracked by git. V2 uses `<data_root>/memory`. This breaks the CLAUDE.md rule that local data lives outside git. | The single canonical root is `<data_root>/memory` (`jarvis/data_root.py`). Slice 02 changes the V1 default to it and adds a one-time copy adoption of the legacy `./data/memory`, modelled on `_adopt_legacy_data_root`. The copy never deletes the source. The tracked `Jarvis-V1.md` is left alone and not the slices' to clean up. Human check H2. |
| D3 | "Add a retrieval port" | `MemoryBackend` (`jarvis/ports/memory.py:7`) mixes search, read, append and rebuild. `search` caps the limit at 10 (`markdown_memory.py:136`). It indexes the whole file, front matter included. It writes to `notes/` (`:174`), a directory outside the five retention classes. | Keep `MemoryBackend` unchanged as the legacy port. The new ports are added beside it. `MarkdownMemoryBackend` implements both (Slice 02). The `notes/` directory is treated as a legacy, unclassified class: recall treats it as `long_term_memory` and never moves it. New writes go to `short_term_memory/`. |
| D4 | "Board memory is a gap or future work" | Board memory is mature and separate: `BoardMemoryStore` (`jarvis/ports/board_memory.py`), `FileBoardMemoryStore` (`jarvis/adapters/board_memory_store.py`), `WorkspaceService`, the `jarvis-workspace` MCP, and the WSP UI (`control_center_workspace.js`, `control_center.html:1663`). It is injected per turn by `board_hydration.read_board_memory` with bounded budgets. | Board memory is NOT migrated or merged. It is a peer source: scope `board:<id>`, read-only to the new retriever, listed in the Memory Center. It keeps its own write path. The new store must not write into `boards/<id>/memory`. |
| D5 | Memory is "injected into Brain" | The Brain is a CLI agent. Core builds a `BrainContext` (`jarvis/domain/brain_context.py:1016`) in `BrainOrchestrator._run_backend` (`brain_service.py:1804-1827`). `jarvis/adapters/control_center_brain.py:101` (`_turn_context`) serialises the blocks `board`, `session_context` and `prefab_events`, and omits each when absent. | The recall block follows this exact pattern (section 2.6). |
| D6 | "State/settings need a schema" | `_SCHEMA_VERSION = 8` (`jarvis/adapters/sqlite_state.py:31`). `tests/schema/` holds `jarvis_state.v3..v8.sql`. CLAUDE.md requires a `_MIGRATIONS` entry, a bump, and `JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest tests/unit/test_schema_migrations.py`, then committing the snapshot. | **Decision: this handoff creates zero migrations.** Canonical state is Markdown. Derived state lives in separate disposable SQLite files, rebuilt when missing or when their own `PRAGMA user_version` differs. These are not covered by CLAUDE.md's schema rule because they are never migrated. Settings go in `control-center-settings.json`. Candidates, ledgers and skills are files. If a slice believes it needs v9, it stops and the PM amends. Only one slice may then own v9 (default owner: Slice 04, candidate ledger), and it must commit `tests/schema/jarvis_state.v9.sql`. |
| D7 | CONTEXT_GLOBAL is not mentioned | `<data_root>/CONTEXT_GLOBAL` (`jarvis/adapters/global_context.py`) is assembled into the system prompt at CLI launch, capped at 12 000 chars (`:25`), and frozen per conversation (`claude_local.py:994-1000`). The agent edits it freely. | It is Brain bootstrap instructions, NOT memory. It is not indexed, not consolidated, and not recalled. Memory modules never read or write it. Memory docs must say so. The L3 profile is injected through the per-turn block, never by writing into CONTEXT_GLOBAL. |
| D8 | "Reflex cannot write memory" | The Realtime tool list in `jarvis/runtime/realtime_tools.py` and `jarvis/core/v2_tools.py` contains no memory tool. The V1 `memory_append` executor (`jarvis/core/executors.py:28`) is V1 only. | The reflex stays without a memory tool. Slice 05b adds a regression test asserting the Realtime tool set contains no `memory_*` name. |
| D9 | SECURITY says only `memory_append` mutates memory | False for Board memory (`WorkspaceService` mutations). ARCHITECTURE, SECURITY and OPERATIONS still describe the V1 memory path as live. | Slice 14 corrects the docs. Slices 02 and 05 add a short "as built" note to `docs/ARCHITECTURE.md` as they land. |
| D10 | Task Types | The vocabulary does not exist. The gate was waived by the Human. | `task_type` stays null. Not re-litigated. |
| D11 | Slice dependencies in `SLICE.md` | They over-serialise. For example, 07 depends on 05, 10 on 03,04,06,07,08,09, and 08 on 07. | Replaced by section 3 (14 slices become 16 work items). |
| D12 | Baseline | 10 inherited failures (READINESS.md table). | Any red outside that list is the slice's. |

## 2. Target architecture

### 2.1 Placement

```
jarvis/domain/memory.py            frozen dataclasses, enums, error codes, budgets (no I/O)
jarvis/domain/memory_policy.py     AgentMemoryPolicy, scope rules, retention x level matrix
jarvis/domain/knowledge.py         KnowledgeAsset, AssetKind(WIKI|CODEGRAPH|SKILL), AssetScope, SourceRef, Loadout
jarvis/domain/memory_settings.py   MemorySettings dataclass, defaults, validation (pure)
jarvis/ports/memory_store.py       CanonicalMemoryStore
jarvis/ports/memory_retrieval.py   MemoryRetriever, EmbeddingProvider
jarvis/ports/memory_consolidation.py   MemoryConsolidator, CandidateExtractor
jarvis/ports/knowledge.py          KnowledgeAssetProvider, LoadoutResolver (NullLoadoutResolver default)
jarvis/ports/capability.py         CapabilityReporter -> CapabilityState(ok|degraded|disabled|unavailable, reason_code)
jarvis/adapters/markdown_memory.py            (touched) canonical store + legacy MemoryBackend
jarvis/adapters/memory_frontmatter.py         parser/writer for the metadata block
jarvis/adapters/memory_lexical.py             thin wrapper over the FTS5 ranked search
jarvis/adapters/memory_semantic.py            derived vector index (separate sqlite file)
jarvis/adapters/embedding_openai.py           optional remote EmbeddingProvider (httpx, reuses credentials)
jarvis/adapters/tencent_memory.py             optional sidecar adapter
jarvis/adapters/knowledge_wiki.py, knowledge_codegraph.py, knowledge_skills.py
jarvis/core/memory_service.py      facade: store + retrievers + consolidator + policy + budgets (Core owns it)
jarvis/core/memory_fusion.py       pure RRF + dedup + budget packing
jarvis/core/memory_context.py      per-turn builder, same pattern as board_hydration.py
jarvis/core/memory_consolidation.py   pipeline stages and state machine
jarvis/core/loadout_resolver.py
jarvis/protocol/memory_routes.py   Core /v1/memory/* (pattern: workspace_routes.py)
jarvis/runtime/memory_settings.py  tolerant-read / strict-write store (pattern: agent_routing.py)
jarvis/runtime/memory_relay.py     Control Center /api/memory* relay (pattern: workspace_relay.py)
jarvis/runtime/memory_mcp.py       "jarvis-memory" stdio MCP (pattern: workspace_mcp.py)
```

Dependency direction: `domain` has no dependencies. `ports` depend on `domain`. `adapters` implement `ports`. `core` orchestrates ports only, so the Tencent adapter and the semantic index are injected and never imported by `core`. Wiring lives in `v2_app.py` plus one factory, `jarvis/core/memory_wiring.py`, created in Slice 05. The Control Center never touches memory files. It only relays Core routes, as it already does for workspace.

### 2.2 Canonical store versus derived indexes

- **Canonical**: Markdown files under `<data_root>/memory/<class>/…`, where the retention class is the directory (the existing `MEMORY_CLASSES`). Lineage lives in front matter.
- **Candidates (proposals)**: `<data_root>/memory/_candidates/*.md`. They are human-readable, not recalled, and not auto-deleted. Directories prefixed with `_` or `.` are excluded from recall and indexing but visible in the Memory Center.
- **Derived (disposable)**:
  - `<memory>/.jarvis/index.sqlite3` (FTS5, exists).
  - `<memory>/.jarvis/semantic.sqlite3` (new).
  - `<data_root>/knowledge/**/index/*.sqlite3`.
  - The CodeGraph DB.
  - The Tencent mirror.

  The rule for every derived store is: delete it and nothing durable is lost. A test per store proves this. The existing corrupt-index recovery (`markdown_memory.py:39-45`) is the model.
- **Metadata format**: a front-matter block delimited by `---`, restricted to flat `key: value` lines where values are JSON scalars or JSON arrays. It is parsed by an in-house parser (`memory_frontmatter.py`), because the repo has no YAML dependency and must not gain one. A file without front matter is a valid legacy note, with defaults derived lazily and never written back unless the note is mutated.
- **Fields**: `id` (stable UUID, independent of path, so moves keep identity), `level` (L0..L3), `kind` (fact | preference | scenario | profile | episode), `created_at`, `updated_at`, `valid_from`, `valid_to`, `confidence` (0..1), `source` (list of `{type: turn|note|board|manual|consolidation, ref, at}`), `revision` (int), `supersedes` (ids), `superseded_by`, `contradicts` (ids), `scope`, `agent`.
- **Writes** are atomic temp-then-`os.replace` (as in `_append_note_sync`), with the existing path and symlink defences kept. A mutation never edits in place. It writes revision N+1 and keeps the prior revision as `<name>.rev<N>.md` under `<memory>/.history/`, which is canonical and git-free. History is excluded from recall.
- **Protected classes** (`traumatic_memory`, `eternal_memory`): no consolidation path may delete or rewrite them. Supersession is allowed only by human action.

### 2.3 L0-L3 versus retention classes

Two independent axes.

- **Retention class** = directory = lifetime policy. It already exists.
- **Level** = front-matter `level`:
  - L0: raw evidence (turn excerpts, note imports).
  - L1: atomic fact or preference.
  - L2: scenario or context.
  - L3: stable profile.

Allowed combinations are listed in `memory_policy.py`. L0 is only valid in `short_term_memory`. Promotion between classes changes the directory. Abstraction changes the level via consolidation. Neither implies the other. The Memory Center shows two separate columns and never merges them in one badge.

### 2.4 Hybrid retrieval

- `MemoryRetriever.recall(RecallQuery, RecallBudget) -> RecallResult`. A `RecallItem` carries `memory_id`, `title`, `snippet`, `score`, `rank_sources` (`{lexical: rank, semantic: rank, tencent: rank}`), `level`, `retention`, `provenance_ref`, `revision` and `why` (the matched terms or the vector rank). `RecallResult` carries `items`, `degraded` (reason codes) and `timings_ms`.
- **Lexical**: FTS5 `bm25()`. Slice 02 exposes `search_ranked(query, limit, filters)` on the Markdown adapter with no 10-item cap, so the cap is not a hidden constraint. The legacy `search` keeps its cap.
- **Semantic**: float32 BLOBs in `semantic.sqlite3`, keyed by `(memory_id, revision, model_id)`. The query is scored by cosine with a brute-force scan. It uses stdlib `array` and pure Python with a capacity guard at 20 000 chunks, and uses numpy only if importable (numpy is an optional extra at `pyproject.toml`). **No sqlite-vec and no new hard dependency.** Beyond the guard the semantic leg reports `degraded: semantic_capacity` and lexical continues.
- **EmbeddingProvider** adapters: `none` (default), `openai` (remote, opt-in, uses `credentials.secret_for(settings, "openai")`), and a deterministic `FakeEmbedder` (tests and CI only). Chunking is one chunk per note below 1 500 chars, otherwise paragraph windows. Embeddings are computed asynchronously after writes (a background queue), never inline on the write path.
- **Fusion**: RRF with k=60, equal weights, over top 20 per leg. The Tencent leg is a third optional list. Ties break by `updated_at` descending, then `memory_id`. Superseded items are excluded by default, and `include_history=True` is available for the Memory Center. Dedup is by `memory_id`, keeping the highest revision.
- **Time budgets** (the legs run concurrently):
  - Lexical: 150 ms.
  - Semantic leg, including the query embedding: 250 ms.
  - Tencent leg: 250 ms.
  - Overall wall clock for recall: 400 ms hard (settings range 100-1500). On timeout the legs that finished are used, with `degraded` set.
- **Count and size budgets** (defaults): at most 6 items, 400 chars per item, 3 000 chars of dynamic recall in total.
- Filters: scope (per `AgentMemoryPolicy`), retention, level, and temporal validity.

### 2.5 Provenance, versioning and contradiction handling

A recalled item always shows source, revision and timestamp, so "why is this here?" is answerable. Contradictions are explicit links (`supersedes` or `contradicts`) created only by the consolidation pipeline under policy, or by a human. A conflicting new fact never overwrites. It either supersedes (temporal, closing `valid_to` on the old note) or is flagged `contradicts` and listed for human review.

### 2.6 Bounded recall through the V2 Brain per-turn context

Reuse the board pattern exactly:

- **Domain** (`jarvis/domain/brain_context.py`): `BrainMemoryContext` with `profile` (L3 stable block), `recall` (dynamic items), `knowledge_manifest`, `degraded`, `error`. It has a `bounded()` constructor, a `to_payload()` method, and constants `MAX_BRAIN_MEMORY_PROFILE_CHARS = 2_048`, `MAX_BRAIN_MEMORY_RECALL_ITEMS = 6`, `MAX_BRAIN_MEMORY_ITEM_CHARS = 400`, `MAX_BRAIN_MEMORY_CONTEXT_CHARS = 6_000`. The 6 000 matches `MAX_BRAIN_WORK_CONTEXT_CHARS`. The 3 000-char recall cap in 2.4 is a sub-budget. The knowledge manifest has its own 1 024-char cap, and the total is clipped to the 6 000 above.
- **Core builder** (`jarvis/core/memory_context.py`): synchronous disk I/O run in a thread. It is never-raising: it returns a degraded block on failure and the turn proceeds, as `read_board_memory` does (`board_hydration.py` docstring). It is wrapped by `asyncio.wait_for(overall_timeout)`.
- **Orchestrator**: `BrainOrchestrator` gains an optional `memory_context` callable next to `board_context` (`brain_service.py:350`). A `_turn_memory(turn)` method sits beside `_turn_board` (`:1869`), emitting diagnostics `core.brain.memory_context_delivered` and `core.brain.memory_context_failed`. The data carried is counts, timings and degraded codes, never memory text. `BrainContext` gains `memory: BrainMemoryContext | None`.
- **Serialisation**: `_turn_context` (`control_center_brain.py:165`) adds `context["memory"]` only when non-empty, and an empty memory context is byte-for-byte the previous context (the repo's existing "absent = unchanged" rule, pinned by tests).
- **Recall query construction**: the user utterance, plus at most one recent turn when the utterance is under 8 words (to resolve pronouns). No LLM call, with fixed latency, and the query is not logged.
- **Stable versus dynamic**: `profile` (L3 plus L2 pinned by `kind: profile`) is rendered first and changes rarely. `recall` follows. Both travel in the same per-turn `memory` dict but under distinct keys, so a CLI-side cache can use the stable part.
- **Brain-initiated search** goes through the `jarvis-memory` MCP (Slice 05b): `memory_search`, `memory_read` and `memory_propose`, with a budget of at most 3 calls per turn recorded in the diagnostics. `memory_propose` writes to `_candidates/` only.
- The reflex and surface voice model has no memory access.

### 2.7 Consolidation

Pipeline: L0 evidence, then candidate extraction (`CandidateExtractor`, LLM-backed in production and a fake in tests), then dedup (lexical and semantic similarity), conflict detection, scoring, and a policy gate. The state machine for a candidate is `proposed -> accepted | rejected | superseded_by_newer`, and `accepted` commits to a canonical note with provenance.

- **Default mode is `manual`**: candidates wait for a human to accept them in the Memory Center. `auto` mode is opt-in and commits only candidates with `confidence >= 0.8` and no conflicts, and only into `long_term_memory` or `plastic_memory`. It never touches protected classes.
- The extractor's output is a proposal. It is schema-validated, and malformed output is dropped with a diagnostic.
- Runs are idempotent, keyed by an evidence hash.
- The existing `MemoryMaintenanceWorker` copy-on-`jarvis:retain` behaviour stays and becomes one policy rule (explicit retain marker means promote, with provenance added).

### 2.8 Optional Tencent adapter

`TencentMemoryRetriever` implements `MemoryRetriever`, and `TencentMirrorSink` pushes canonical notes outward. Transport is `httpx` to a configured sidecar URL (loopback by default), with a token from `credentials`.

- **Mapping**: team = a configured constant (default `jarvis`), user = owner, agent = the agent id. Per-scope isolation is enforced on the Jarvis side before any call.
- **Authority**: a Tencent hit that does not resolve to a canonical `memory_id` is dropped. Tencent never supplies recall text, only ranks, and the snippet is always read from canonical.
- **Degradation**: three consecutive failures open a circuit breaker for 60 s. Failures set `degraded: tencent_unavailable`. Startup never probes synchronously. Writes to canonical never wait on the mirror, which is asynchronous and loss-tolerant, and a `resync` rebuilds it.
- **No MemoryProxy.** It is excluded.
- **CI**: only a fake sidecar built on aiohttp (`tests/fakes/fake_tencent_sidecar.py`) is used. Real calls sit behind `@pytest.mark.live_tencent` plus `JARVIS_TENCENT_LIVE=1`, skipped by default. The first task of Slice 06 is to pin the sidecar API shape from upstream docs into `docs/memory-tencent.md`, noting the commit evaluated (`0468a2a`), because the upstream is moving fast. If the API cannot be pinned, the PM is told and the slice is cut to the port, fake, and config.
- **Vendoring** is not done. The licence and update policy go in the doc.

### 2.9 Wiki, CodeGraph and Skills as assets

Root: `<data_root>/knowledge/{wiki,codegraph,skills}/`, outside the memory root so they never pollute personal memory.

- **Contract** (Slice 01): `KnowledgeAssetProvider` with `kind`, `status()`, `list()`, `search(query, limit, scope)`, `read(asset_id)` and `rebuild()`. Every asset carries `SourceRef(uri, version_or_commit, fetched_at, path, line)`.
- **Wiki** (Slice 07): Markdown pages imported from allowlisted project doc paths by copy, with `source_uri` and `source_hash`. The lexical FTS5 index is a separate derived DB. A staleness check compares source mtime and hash. Semantic search is out of scope (it could reuse the Slice 03 `EmbeddingProvider` later).
- **CodeGraph** (Slice 08): the first release indexes Python through stdlib `ast` (symbols, imports, calls by name, references), plus a file and import graph for other languages. There is no tree-sitter and no language server. It is persisted in a derived sqlite file keyed by repo path and `git rev-parse HEAD`, and refreshed incrementally by file hash. Queries: `symbol`, `usages`, `neighbors`, `path`, and `impact` (reverse-reachable closure, depth and size capped). Every answer carries the snapshot commit and a `stale: bool` that is true if HEAD or the working tree differs from the snapshot. The graph is name-based (not type-resolved) and the output says so (`confidence: name_match`).
- **Skills** (Slice 09): `<knowledge>/skills/<id>/SKILL.md` with front matter `id`, `version`, `description`, `scope` (private | project | shared), `allowed_profiles`, `source`. A registry handles discovery, enable and disable, and version conflicts (the highest enabled version wins, and the loser is shown). Import is user-initiated only. There is no autonomous extraction or cross-agent publication in this handoff.
- **Loadouts**: keyed by the routing task profile (`jarvis/domain/routing.py:56`: `desktop`, `code`, `fast`, `general`) plus an optional `role` tag (`coder`, `reviewer`, `research`, set by the Brain in the sub-agent brief, with presets `coder = code`, `reviewer = code+role`, `research = general+role`). A loadout lists memory scopes, wiki ids, codegraph repos and skill ids. Default is deny-by-scope: private memory is never in a non-Brain loadout unless a policy rule explicitly includes it.
- **Delivery**:
  - Brain: the manifest (names, ids and versions, not bodies) is injected in `memory.knowledge_manifest`. Bodies are fetched on demand through the `jarvis-memory` MCP tools `knowledge_search` and `knowledge_read`.
  - Sub-agents: `jarvis/runtime/routing_hook.py` appends a loadout manifest (at most 1 024 chars) to the `Agent` tool brief, as it already signs the charter (`jarvis/domain/agent_charter.py`). It reads the loadout through a file snapshot, since the hook is a short-lived process that does not call the network.

### 2.10 Settings backend and UI

- A new top-level key `"memory"` in `control-center-settings.json` (not a new file, and no migration). `jarvis/runtime/memory_settings.py` has tolerant read and strict whole-request write, copying `agent_routing.py` (`SETTING_KEY`), and uses the existing atomic `_write_settings` (`control_center.py:2778`).
- **Defaults**:
  - `recall.enabled=true`
  - `recall.max_items=6`
  - `recall.timeout_ms=400`
  - `semantic.enabled=false`
  - `semantic.provider="none"`
  - `consolidation.mode="manual"`
  - `tencent.enabled=false`
  - `knowledge.wiki|codegraph|skills.enabled=true`
  - Loadouts default to the presets above.
- **Secrets**: stored only via `credentials`. The payload sends `has_secret: bool`, never a value (the pattern in `credentials.py`).
- **Server-described**: `_settings_payload` (`control_center.py:3414`) gets a `memory` section with `schema` (types, ranges and enums), `values`, `effective` (value plus source `default|file|env`) and `status` (a `CapabilityState` per leg with `reason_code` and a human `reason`). The UI hard-codes no provider lists.
- **Validation**: whole-request refusal, with incompatible combinations rejected (for example `semantic.enabled` with `provider=none`, `consolidation.mode=auto` without `semantic.enabled`, or `tencent.enabled` without a URL).
- **Propagation**: Core re-reads the settings file at most every 2 s per turn (mtime-cached), so changes apply on the next turn without a restart. Embedding provider changes trigger a derived-index rebuild, never a canonical change.
- **Memory Center**: a new "Memory" tab inside the existing Sessions & Boards manager (`control_center.html:1663`, `control_center_workspace.js`), with its own module `control_center_memory.js`, so Board memory and global memory are reachable from one place. Settings has a "Memory" section with quick controls and an "Open Memory Center" entry point. Memory Center data flows `UI -> /api/memory* (relay) -> Core /v1/memory/*`.
- **Center content**: browse and search with filters, detail (canonical text, provenance, revision history, links), the L0-L3 level and retention class as separate columns, candidates queue (accept and reject), knowledge assets and loadouts, derived-index and sidecar health with a safe "rebuild derived" action behind a confirmation, and a "recall sandbox" with a "why recalled" breakdown. Derived data always carries a "derived" label.

## 3. Slice contracts

Notation: *Deps* are hard predecessors. *QA* is the tier plus the extra review skills required by the handoff README (`code-review` on every code change; `runtime-validation` for user-visible behaviour; `agent-trace-analysis` where marked). Mutation testing runs only on the **critical** slices, and across the whole handoff at most 10 target modules. All coding agents use `/caveman` and `/coding-guideline`. Frontend slices use `/impeccable`.

### Dependency graph and waves (at most 3 concurrent)

```
01 -> 02 -> 03 -> 04
01 -> 07 ----------+
01 -> 08 ----------+-> 09
01 -> 10a
{01,02,03,09} -> 05 -> 05b
{01,02,03} -> 06
{05,06,07,08,09,10a} -> 10b -> 11
{02,03,04,06,07,08,09,10b} -> 12
{11,12,05b} -> 13 -> 14
```

| Wave | Slices (concurrent) | Why safe to parallelise |
|---|---|---|
| W1 | 01 | Contracts block everything. |
| W2 | 02, 07, 08 | Disjoint file sets. 07 and 08 only need the 01 contracts. |
| W3 | 03, 09, 10a | 03 needs 02. 09 needs 07 and 08. 10a needs 01 only. |
| W4 | 04, 05, 06 | 04 needs 02 and 03. 05 needs 03 and the `LoadoutResolver` port (null default). 06 needs 01 to 03. |
| W5 | 05b, 10b | 10b creates the UI and relay stub registration points. |
| W6 | 11, 12 | Separate JS files. All registration lines already exist from 10b. |
| W7 | 13 | QA-only. |
| W8 | 14 | Release gate. |

**Merge or split verdicts**:
- **Split 05 into 05 and 05b.** Injection is the highest-risk slice. Brain-initiated tools are a separate surface and run later in parallel.
- **Split 10 into 10a and 10b.** The settings model must exist before providers, but the effective status needs them.
- **Do not merge 07/08/09.** They are independent by design, once the shared contracts sit in Slice 01.
- **Slice 13 is QA-only.** It is not an implementation slice. Findings go to the owning slice (or a new rework slice), and 13 carries no product code.
- Total work items: 16 (01-09, 05b, 10a, 10b, 11-14).

---

### Slice 01 - Memory contracts
**Slice 00 contract**
- **Create**:
  - `jarvis/domain/memory.py`
  - `jarvis/domain/memory_policy.py`
  - `jarvis/domain/knowledge.py`
  - `jarvis/domain/memory_settings.py` (dataclass and validation only)
  - `jarvis/ports/memory_store.py`
  - `jarvis/ports/memory_retrieval.py`
  - `jarvis/ports/memory_consolidation.py`
  - `jarvis/ports/knowledge.py` (includes `LoadoutResolver` and `NullLoadoutResolver`)
  - `jarvis/ports/capability.py`
  - `tests/unit/test_memory_contracts.py`
  - `docs/memory.md` (terminology plus the L0-L3 versus retention matrix)
- **Touch**: nothing existing. `jarvis/ports/memory.py` and `jarvis/domain/results.py` are unchanged.
- **Interfaces** (exact):
  - `CanonicalMemoryStore`: `get(id)`, `list(filters)`, `create(note)`, `revise(id, patch, expected_revision)`, `history(id)`, `rebuild_indexes()`.
  - `MemoryRetriever`: `recall(query, budget)`, `status()`.
  - `EmbeddingProvider`: `model_id`, `dim`, `embed(texts, timeout)`.
  - `MemoryConsolidator`: `propose(evidence)`, `decide(candidate_id, decision, actor)`.
  - Models: `MemoryNote`, `Provenance`, `RecallQuery`, `RecallBudget`, `RecallItem`, `RecallResult`, `Candidate`, `Loadout`, `CapabilityState`.
  - Stable `StrEnum` error codes: `memory_not_found`, `memory_conflict_revision`, `memory_scope_denied`, `memory_degraded`, `memory_unavailable`.
- **Deps**: 00. **Parallel**: none.
- **QA**: standard. `code-review`. No runtime or trace review (no behaviour).
- **Tests**: construction and validation, frozen and bounded fields, error-code stability, protocol conformance by fakes, a legacy adapter-shape test showing `MemoryBackend` stays importable and unchanged.
- **Docs**: `docs/memory.md`, a link from `docs/ARCHITECTURE.md`.
- **Out of scope**: any persistence, any I/O, any UI, any wiring.

### Slice 02 - Canonical store and provenance
**Slice 00 contract**
- **Create**: `jarvis/adapters/memory_frontmatter.py`, `tests/unit/test_memory_frontmatter.py`, `tests/unit/test_memory_store_canonical.py`.
- **Touch**:
  - `jarvis/adapters/markdown_memory.py`: implements `CanonicalMemoryStore`, strips front matter before indexing, and adds `search_ranked(query, limit, filters)` with no 10 cap. It keeps the legacy `MemoryBackend` behaviour, and the ctor rebuild (`:48`) moves to a lazy or threaded start so V2 startup is not blocked.
  - `jarvis/config.py` (`memory_dir` default to `<data_root>/memory`, plus legacy `./data/memory` copy adoption).
  - `jarvis/core/memory_maintenance.py`: only to write provenance when promoting, and to share `MEMORY_CLASSES`.
  - `tests/unit/test_memory.py` (extended).
- **Interfaces**: `CanonicalMemoryStore` implemented. `.history/` revisions. Legacy note lazy defaults.
- **Deps**: 01. **Parallel**: with 07 and 08.
- **QA**: **critical**. Mutation targets: `memory_frontmatter.py` and the path guard plus revise logic in `markdown_memory.py`. `runtime-validation`: not needed (no UI). No trace review.
- **Tests**: round-trip, legacy notes without front matter, unknown-key tolerance, a corrupt block falling back to body-only (the note is never dropped), traversal and symlink and junction cases (re-run the existing ones), atomic-write failure mid-revise leaves the old revision intact, optimistic concurrency (`memory_conflict_revision`), protected-class guard, delete derived index then recover with no loss, legacy `notes/` still readable, the migration copy of `./data/memory` is idempotent and does not delete the source.
- **Docs**: `docs/memory.md` metadata schema, `docs/local-data.md` (single memory root), `docs/ARCHITECTURE.md` "as built" note.
- **Out of scope**: consolidation decisions, the semantic index, V2 wiring (05), any v9 migration.

### Slice 03 - Hybrid retriever
**Slice 00 contract**
- **Create**: `jarvis/adapters/memory_lexical.py`, `jarvis/adapters/memory_semantic.py`, `jarvis/adapters/embedding_openai.py`, `jarvis/core/memory_fusion.py`, `tests/fakes/fake_embedder.py`, `tests/fixtures/memory_recall/` (FR and EN fixture corpus plus labelled queries), tests `test_memory_fusion.py`, `test_memory_semantic_index.py`, `test_memory_recall_fixtures.py`, `tests/benchmarks/` or `benchmarks/memory_recall.py` (p50 and p95 report).
- **Touch**: `markdown_memory.py` only via the `search_ranked` already exposed by Slice 02 (no edit expected). `pyproject.toml`: no new hard dependency (numpy stays optional).
- **Interfaces**: `LexicalRetriever`, `SemanticRetriever`, `HybridRetriever(MemoryRetriever)`, and `rrf_fuse(lists, k=60) -> list`. The recall budgets are those in 2.4.
- **Deps**: 01, 02. **Parallel**: with 09 and 10a.
- **QA**: **critical**. Mutation targets: `memory_fusion.py` (RRF, dedup, budget packing).
- **Tests**:
  - Deterministic RRF with ties.
  - Lexical-only with provider `none` is fully functional.
  - Embedder timeout and exception leave lexical results intact, with `degraded` populated.
  - Model change invalidates and rebuilds embeddings, and a deleted semantic DB rebuilds.
  - The capacity guard triggers.
  - Superseded notes are excluded by default.
  - Scope filter.
  - Fixture quality: hybrid recall@5 is at least the lexical baseline on the fixture set.
  - Latency evidence: lexical p95 under 60 ms at 5 000 notes on the dev machine (reported, not a flaky CI gate), with the numbers recorded in the slice log.
- **Docs**: `docs/memory.md` retrieval, fusion and budgets.
- **Out of scope**: the Brain wiring, consolidation, Tencent, a remote embedding being on by default.

### Slice 04 - Consolidation pipeline
**Slice 00 contract**
- **Create**: `jarvis/core/memory_consolidation.py`, `jarvis/adapters/memory_extractor_llm.py` (behind `CandidateExtractor`; reuse the existing back-brain or agent execution, with the model chosen by routing profile `fast`), `tests/fakes/fake_extractor.py`, tests `test_memory_consolidation_*.py`.
- **Touch**: `jarvis/core/memory_maintenance.py` (worker calls the pipeline in addition to the retain rule, the daily schedule at `v2_app.py:548-559` is unchanged), `jarvis/adapters/markdown_memory.py` (candidate directory helpers only if Slice 02 did not already cover it).
- **Interfaces**: `MemoryConsolidator` implemented. The `Candidate` state machine from 2.7. Policy knobs `mode` (`manual|auto`), `auto_min_confidence`, `max_candidates_per_run`.
- **Deps**: 01, 02, 03. **Parallel**: with 05 and 06.
- **QA**: **critical**. Mutation targets: the state machine and policy gate. `agent-trace-analysis` with a real extractor trace (the extractor is an LLM-backed prompt).
- **Tests**: dedup of repeated evidence (no duplicate notes), temporal supersession keeps history (`valid_to`, `superseded_by`), an unresolved contradiction is flagged and never overwritten, protected classes untouched in `auto`, malformed extractor output dropped with a diagnostic, idempotent re-run, `manual` mode commits nothing, `auto` threshold boundaries, provenance on every commit, a crash between commit and ledger update is recoverable.
- **Docs**: `docs/memory.md` consolidation state machine and knobs.
- **Out of scope**: UI, Tencent, any LLM prompt tuning beyond a working default, any DB table (file candidates only; v9 only by PM amendment).

### Slice 05 - V2 Brain memory integration (recall injection and Core service)
**Slice 00 contract**
- **Create**: `jarvis/core/memory_service.py`, `jarvis/core/memory_context.py`, `jarvis/core/memory_wiring.py`, `jarvis/protocol/memory_routes.py` (read routes: list, get, search, status, recall-explain, plus candidate list), tests `test_memory_context.py`, `test_memory_brain_injection.py`, `test_memory_routes.py`.
- **Touch**:
  - `jarvis/domain/brain_context.py` (`BrainMemoryContext`, the `BrainContext.memory` field).
  - `jarvis/core/brain_service.py` (the `memory_context` constructor parameter, `_turn_memory`, the call in `_run_backend`).
  - `jarvis/core/v2_app.py` (build the store, the retriever, the service, and the routes).
  - `jarvis/adapters/control_center_brain.py` (`_turn_context`: the `memory` key).
  - `jarvis/ports/v2.py` only if `ContextAwareBrainBackend` needs an annotation.
- **Interfaces**: `BrainMemoryContext`, `MemoryService.recall_for_turn`, Core `/v1/memory/*` (read-only plus candidate accept/reject delegating to the consolidator).
- **Deps**: 01, 02, 03 (and the `LoadoutResolver` port from 01, null by default). **Parallel**: with 04 and 06. 09 plugs in later.
- **QA**: **critical**. Mutation targets: budget clipping and the `bounded()` constructor in `memory_context.py`. `runtime-validation` (a real Core turn). `agent-trace-analysis` with real traces: an empty memory turn, a hit turn, a degraded turn.
- **Tests**:
  - A context with no memory is byte-identical to before.
  - Budget truncation on a UTF-8 boundary (reuse `clip_utf8`).
  - Timeout turns return degraded and the turn still completes.
  - A store exception does not block the turn.
  - The recall query is not logged.
  - Provenance labels are present.
  - A superseded note is never injected.
  - Private scope is never leaked when policy forbids it.
  - Startup with the memory root unreadable does not block Core.
  - The Realtime tool set has no memory tool.
- **Docs**: `docs/ARCHITECTURE.md` Brain context section and diagram, `docs/memory.md` injection budgets, the SECURITY.md memory-mutation paragraph (partial fix, completed in 14).
- **Out of scope**: Brain-initiated tools (05b), Tencent, the Wiki and CodeGraph injection (via the loadout resolver in 09), UI.

### Slice 05b - Memory tools MCP (new split)
**Slice 00 contract**
- **Create**: `jarvis/runtime/memory_mcp.py` (`jarvis-memory` stdio server with `memory_search`, `memory_read`, `memory_propose`, `knowledge_search`, `knowledge_read`), `tests/unit/test_memory_mcp.py`.
- **Touch**: the MCP catalog wiring where `workspace_mcp` is registered (see `jarvis/runtime/settings_mcp.py` and the `--mcp-config` writer), `jarvis/__main__.py` (subcommand `memory-mcp`), `docs/mcp/tool-contract.md`.
- **Interfaces**: the 5 tools, each calling Core `/v1/memory/*` (add write route `POST /v1/memory/candidates` in `memory_routes.py`, which is owned by this slice for that route only). Per-turn tool-call budget of 3, enforced Core-side.
- **Deps**: 05 (plus 09 for the `knowledge_*` tools: land the two knowledge tools in Slice 09's wave-5 tail or here if 09 is merged, and the PM decides at dispatch). **Parallel**: with 10b.
- **QA**: standard. `agent-trace-analysis`: a real brain trace using the tools. `runtime-validation`: a live MCP call.
- **Tests**: tool schemas, scope enforcement (the tool cannot read outside the caller's policy), `memory_propose` can only create candidates, the budget cap, Core down gives a clean tool error with the stable code.
- **Out of scope**: direct durable writes from any tool, any reflex or voice exposure.

### Slice 06 - Tencent MemoryCore adapter
**Slice 00 contract**
- **Create**: `jarvis/adapters/tencent_memory.py`, `tests/fakes/fake_tencent_sidecar.py`, `tests/unit/test_tencent_memory_adapter.py`, `tests/integration/test_tencent_live.py` (marker `live_tencent`, skipped unless `JARVIS_TENCENT_LIVE=1`), `docs/memory-tencent.md`.
- **Touch**: `jarvis/core/memory_wiring.py` (register the retriever only when enabled; this file is created in 05, so 06 adds a registration hook in 05's wave, and the PM sequences the one-line merge) and `jarvis/runtime/credentials.py` (a `tencent` provider id).
- **Interfaces**: `TencentMemoryRetriever`, `TencentMirrorSink`, `CapabilityReporter` for health, a circuit breaker.
- **Deps**: 01, 02, 03. **Parallel**: with 04 and 05. The `memory_wiring.py` hook needs 05's file, so 06 exposes a `register_retriever()` hook in its own module and 05 calls it by name (the PM resolves the merge order, with 05 first).
- **QA**: **critical** (identity isolation and degradation). Mutation targets: identity mapping and the circuit breaker. No live network in CI.
- **Tests**:
  - Identity mapping isolates team, user and agent.
  - Hits that do not resolve to canonical ids are dropped.
  - The sidecar is down, slow, or returns malformed output: lexical recall is unaffected and `degraded` is set.
  - The circuit breaker opens and closes.
  - Canonical writes succeed with the sidecar down.
  - Resync is idempotent.
  - Disabled by default means zero network calls (asserted with a socket guard).
  - Secrets never appear in the diagnostics.
- **Docs**: `docs/memory-tencent.md` (API pin, licence, update policy), `docs/OPERATIONS.md` (sidecar runbook).
- **Out of scope**: MemoryProxy, vendoring, mirroring Wiki or CodeGraph assets, a live benchmark in CI.

### Slice 07 - Wiki knowledge assets
**Slice 00 contract**
- **Create**: `jarvis/adapters/knowledge_wiki.py`, tests `test_knowledge_wiki.py`, `docs/knowledge-assets.md`.
- **Touch**: nothing in the Brain path. Ingestion is exposed through the provider, and Core routes are added by Slice 10b or 12 as needed (read routes for browse are part of 12's relay). The provider registers through `memory_wiring.py` in Slice 09.
- **Interfaces**: `WikiProvider(KnowledgeAssetProvider)`. Import from allowlisted paths only (default: the repo `docs/` tree). Own FTS5 derived index.
- **Deps**: 01. **Parallel**: with 02 and 08.
- **QA**: standard. `code-review`. A runtime check of an actual import. No trace review until 09.
- **Tests**: import and update and delete, then rebuild (the index deleted, nothing lost), stale detection by hash, path-allowlist traversal and symlink defence, scope isolation (a private page invisible to a project loadout), source and version always present.
- **Docs**: `docs/knowledge-assets.md` (asset contract, lifecycle).
- **Out of scope**: semantic search, the Brain injection (09), CodeGraph, Skills, any remote fetch (URLs are recorded as `source_uri` but never fetched in this handoff).

### Slice 08 - CodeGraph
**Slice 00 contract**
- **Create**: `jarvis/adapters/knowledge_codegraph.py`, `tests/fixtures/codegraph_repo/` (a tiny Python fixture repo), `tests/unit/test_knowledge_codegraph.py`.
- **Touch**: `docs/knowledge-assets.md` (a section; coordinate with 07 by appending only, with the PM merging).
- **Interfaces**: `CodeGraphProvider`; queries `symbol`, `usages`, `neighbors`, `path`, `impact`; snapshot `{repo, commit, indexed_at, stale}`.
- **Deps**: 01 (not 07). **Parallel**: with 02 and 07.
- **QA**: standard, with extra weight on the query correctness tests. `code-review`.
- **Tests**: a known fixture graph (expected edges, an exact answer for "where is X used" and "what is impacted by changing X"), incremental refresh touches only the changed files, a stale snapshot is flagged after an edit or a new commit, size and depth caps, a syntax-error file is skipped with a diagnostic, a rebuild from scratch equals the incremental result, and a performance bound on this repo (record the time, no hard CI gate).
- **Docs**: schema, refresh rules, query semantics, the name-match limitation.
- **Out of scope**: a language server, type resolution, non-Python symbol extraction, Brain injection.

### Slice 09 - Skills and agent loadouts
**Slice 00 contract**
- **Create**: `jarvis/adapters/knowledge_skills.py`, `jarvis/core/loadout_resolver.py`, `tests/unit/test_knowledge_skills.py`, `tests/unit/test_loadout_resolver.py`, `docs/skills-and-loadouts.md`.
- **Touch**: `jarvis/runtime/routing_hook.py` (append the manifest to the `Agent` brief; the hook must stay network-free and silent on failure), `jarvis/core/memory_wiring.py` (register the Wiki, CodeGraph and Skills providers and the real resolver, replacing `NullLoadoutResolver`), and `jarvis/core/memory_context.py` only through the resolver port (a small edit owned by 09 after 05 lands; the PM sequences it).
- **Interfaces**: `SkillRegistry`, `LoadoutResolver.resolve(profile, role) -> Loadout` (an effective loadout with the reason each asset is included), the manifest renderer (at most 1 024 chars).
- **Deps**: 01, 07, 08. **Parallel**: with 03 and 10a. The edit to `memory_context.py` and the wiring file happens in W4 or W5 once 05 exists. If 09 finishes before 05, it ships the resolver and hook and the integration step moves to 05b's wave.
- **QA**: **critical** (isolation). Mutation targets: `loadout_resolver.py`. `agent-trace-analysis`: real traces for a `code`, a `reviewer` and a `research` sub-agent.
- **Tests**: resolution per profile and role, a conflicting skill version (the highest enabled wins and the loser is reported), a private memory scope never appears in a shared loadout, a disabled skill is absent, the hook failing leaves the `Agent` call untouched, the manifest cap, and the effective loadout is inspectable via the route.
- **Docs**: `docs/skills-and-loadouts.md` (lifecycle, loadout policy, agent matrix).
- **Out of scope**: autonomous skill extraction, cross-agent publication of private memory, skill execution beyond delivering the instructions.

### Slice 10a - Memory settings model and persistence
**Slice 00 contract**
- **Create**: `jarvis/runtime/memory_settings.py`, `tests/unit/test_memory_settings.py`, `docs/settings/memory.md`.
- **Touch**: `jarvis/domain/memory_settings.py` (created in 01, extended here), `docs/settings/INDEX.md`.
- **Interfaces**: `read_memory_settings(raw) -> MemorySettings` (tolerant), `validate_memory_settings_write(raw) -> MemorySettings` (strict, whole-request), `describe_memory_settings() -> schema`. It is not yet registered in `control_center.py` (that is 10b).
- **Deps**: 01. **Parallel**: with 03 and 09.
- **QA**: **critical** (validation and secret handling). Mutation targets: the validators.
- **Tests**: defaults, round trip, env precedence, corrupt file tolerated on read, invalid combination refused with no partial write, ranges, a secret never in any payload, unknown keys preserved on write.
- **Docs**: `docs/settings/memory.md` (schema and compatibility matrix).
- **Out of scope**: endpoints, status, UI.

### Slice 10b - Memory settings endpoints and effective state
**Slice 00 contract**
- **Create**: `jarvis/runtime/memory_relay.py`, stub JS files `jarvis/runtime/control_center_memory_settings.js` and `jarvis/runtime/control_center_memory.js` (registered and served, near-empty), `tests/unit/test_memory_settings_endpoints.py`.
- **Touch**: `jarvis/runtime/control_center.py` (`_settings_payload` at `:3414` gets the `memory` section, `save_settings` at `:4623` validates and persists it, and the relay and JS routes are registered), `jarvis/runtime/control_center.html` (script tags and an empty mount point in Settings and in the WSP manager), the Core settings reader (an mtime-cached read in `memory_wiring.py`), and a `/v1/memory/status` that aggregates every `CapabilityReporter`.
- **Interfaces**: the `memory` settings payload (`schema`, `values`, `effective`, `status`), the relay routes, and the diagnostics.
- **Deps**: 05, 06, 07, 08, 09, 10a. **Parallel**: with 05b.
- **QA**: standard. `code-review`. `runtime-validation` (a real settings round trip).
- **Tests**: payload shape, a disabled or degraded reason surfaces per leg (semantic with no key, Tencent unreachable, a wiki with no sources), a secret is absent in every response, a restart-free change applies to the next turn, an invalid combination is a 4xx with a stable code, and the existing settings endpoint tests are unaffected.
- **Docs**: `docs/settings/memory.md` (endpoints), `docs/ARCHITECTURE.md`.
- **Out of scope**: visual design.

### Slice 11 - Memory settings UI
**Slice 00 contract**
- **Create**: tests `tests/unit/test_memory_settings_ui.py` (pattern: `test_routing_settings_screen.py`).
- **Touch**: `jarvis/runtime/control_center_memory_settings.js` (filled in), CSS in `control_center.html` for the section only, `docs/settings/memory.md` (user guide).
- **Interfaces**: renders only from the server payload (`schema`, `values`, `status`). Toggles, selectors and budgets. Each degraded or disabled state shows its reason and the consequence. An "Open Memory Center" entry point.
- **Deps**: 10b. **Parallel**: with 12.
- **QA**: standard. `/impeccable` and a Claude work agent per the handoff rule. `runtime-validation` in a real browser. Accessibility (keyboard and labels).
- **Tests**: DOM and JS unit tests, no hard-coded provider lists (a grep-style test), an enabled-but-not-working state can never display as plain "on", keyboard operation, narrow viewport, and a round trip against a live Control Center.
- **Docs**: the user settings guide.
- **Out of scope**: memory browsing (12).

### Slice 12 - Memory Center UX
**Slice 00 contract**
- **Create**: tests `tests/unit/test_memory_center_ui.py`, a realistic seed script under `tests/fixtures/memory_center/` (never touching a real data root), `docs/memory-center.md`.
- **Touch**: `jarvis/runtime/control_center_memory.js` (filled in), `jarvis/runtime/control_center_workspace.js` and `control_center.html` only for the "Memory" tab hook, `jarvis/runtime/memory_relay.py` and `jarvis/protocol/memory_routes.py` for any read route missing (browse, detail, history, recall-explain, rebuild-derived action, candidate accept and reject).
- **Interfaces**: the views in 2.10. A destructive or expensive action ("rebuild derived", "reject candidate") requires a confirmation. Canonical content is never editable from the sandbox. Edits go through `revise` with an optimistic revision.
- **Deps**: 02, 03, 04, 06, 07, 08, 09, 10b. **Parallel**: with 11.
- **QA**: standard, with the heaviest runtime and trace evidence of the UI slices. `/impeccable`. `runtime-validation` with browser flows. `agent-trace-analysis` for the recall sandbox's "why recalled".
- **Tests**: browse, search, filter, detail, history, candidate decision, rebuild with a confirmation, recall sandbox, empty, error and degraded states, a derived item always labelled, L0-L3 and retention in separate columns, a large corpus of 5 000 notes stays responsive (paginated, with the budget stated), keyboard and responsive checks.
- **Docs**: `docs/memory-center.md` (user guide and UX decisions).
- **Out of scope**: a prescribed graph visualisation, editing derived data, Board memory editing (it stays in the WSP Board view).

### Slice 13 - Critic-agent user validation (QA-only)
**Slice 00 contract**
- **Create**: QA reports under `qa/` or the task's `slices/13-critical-user-agent-validation/` (evidence only). No product code.
- **Touch**: nothing in the product. Findings route to the owning slice (11, 12, 10b, 05) or to a new rework slice.
- **Interfaces**: personas and task scripts that do not reveal UI paths. Journeys: enable semantic recall and read the degraded explanation, browse and search memory, inspect provenance and a conflict, accept a candidate, run a recall test and read why, view the Wiki, CodeGraph and Skills loadouts, and disable Tencent.
- **Deps**: 11, 12, 05b. **Parallel**: none.
- **QA**: this is the QA. `runtime-validation` plus `agent-trace-analysis` on the critic's own run. Blocking findings are closed and re-tested before 14.
- **Tests**: not applicable. The acceptance criterion is a critic run with zero blocking misleading-state findings.
- **Docs**: journeys, findings and decisions recorded in the slice log.
- **Out of scope**: self-review by an implementing agent, and screenshot-only review.

### Slice 14 - End-to-end validation, rollout and documentation
**Slice 00 contract**
- **Create**: `tests/integration/test_memory_e2e.py` (conversational recall, consolidation, Tencent on and off with the fake sidecar, loadouts), `docs/memory-operations.md` (backup, rebuild drill, rollback, sidecar outage runbook), the final evidence report.
- **Touch**: `docs/ARCHITECTURE.md`, `docs/SECURITY.md` (the "only memory_append mutates memory" fix), `docs/OPERATIONS.md`, `docs/ACCEPTANCE_STATUS.md`, `docs/context-global.md` (cross-reference only, the boundary in D7).
- **Interfaces**: none new.
- **Deps**: 05, 05b, 06, 07, 08, 09, 10b, 11, 12, 13.
- **QA**: standard. This slice verifies. The full suite is compared against the READINESS.md baseline (any new red is blocking), `runtime-validation`, and `agent-trace-analysis` on a full conversation.
- **Tests**: the rebuild drill (delete every derived store, then rebuild and compare recall), the sidecar outage drill, a backup and restore drill (copy `<data_root>/memory` to a clean data root and recall), the p50 and p95 comparison of local-only versus enriched modes, and a private-scope leakage sweep across every loadout.
- **Docs**: as listed.
- **Out of scope**: unrelated Jarvis features, fixing the 10 inherited failures.

## 4. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Recall latency on the voice path. | Hard 400 ms budget (range 100-1500), parallel legs, degraded flag, async embedding. p50 and p95 recorded in 03, 05 and 14. |
| R2 | Prompt bloat. | The 6 000-char cap with sub-budgets, UTF-8-safe clipping, tests for truncation. |
| R3 | Index staleness. `MemoryMaintenanceWorker` copies files without touching the index. | The ctor-time rebuild exists, but V2 runs long. Slice 02 adds an upsert hook on every store mutation and the worker uses the store API for promotion. |
| R4 | Startup cost. `MarkdownMemoryBackend.__init__` rebuilds synchronously (`:48`). | Lazy or threaded start (Slice 02) and a Core startup test with 5 000 notes. |
| R5 | Silent corruption of canonical truth by the extractor. | `manual` default, validated proposals, revisions in `.history/`, protected classes excluded. |
| R6 | Private memory leaking into sub-agent loadouts. | Deny by scope, a resolver test matrix, and a leakage sweep in 14. |
| R7 | Tencent API drift or an unpinned contract. | The Slice 06 API pin, a narrow port, a fake sidecar only in CI, and a fallback cut of the slice to the port and fake. |
| R8 | Shared-file merge conflicts. | The `control_center.html/.py`, `memory_wiring.py` and `brain_service.py` edits are assigned to one slice each, and 10b pre-registers the UI stubs. |
| R9 | The V1 memory root move touches user data. | Copy only, never delete, tested for idempotency, Human check H2. |
| R10 | Windows file-replace races and long paths. | Reuse `replace_with_retry` semantics. Slice 02 tests run on Windows. |
| R11 | CodeGraph precision (name-based). | The `confidence: name_match` label, `stale` flag, and documentation of the limit. |
| R12 | Embeddings send memory text to a remote provider. | Off by default, an explicit opt-in with a disclosure line in the UI, and per-scope exclusion (private scopes are not sent unless the user allows it, `semantic.allow_private=false`). |
| R13 | The inherited red tests mask a regression. | The READINESS.md file list is the only tolerated set. Each QA reports a diff against it. |
| R14 | A hidden need for migration v9. | The zero-migration decision (D6) plus the single-owner rule. |

## 5. Human-validation checks

Asked only after machine QA, agent traces and the Slice 13 critic run are clean.

- **H1**: the Drive handoff folder is moved from `to-do` to `current` (the connector cannot move it).
- **H2**: confirm the memory root unification. The V1 default moves from `./data/memory` to `<data_root>/memory`, the legacy copy is acceptable, and the tracked `data/memory/Jarvis-V1.md` should stay or be untracked (a decision for the Human, not a slice).
- **H3**: confirm consolidation defaults to `manual`, and what `auto` may commit.
- **H4**: confirm the embedding disclosure. Remote embeddings are opt-in, the memory-text exposure is acceptable, and private scopes are excluded by default.
- **H5**: real voice session. The felt latency with recall on versus off, and one conversation where a remembered fact is used correctly.
- **H6**: real Tencent sidecar (optional, manual only). The enable and disable round trip, and that the local recall is unchanged while it is down.
- **H7**: a Memory Center walk-through. A non-author can say what is canonical versus derived, where a memory came from, and how to undo an accepted candidate.
- **H8**: loadout sanity on a real sub-agent run (`code` and a reviewer), including that a private memory is not visible to them.
- **H9**: backup and restore on a second data root.
- **H10**: sign off the Wiki import allowlist (which project docs enter the Wiki).
