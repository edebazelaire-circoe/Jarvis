# Slice 00 — Readiness (agent 0)

State: **READY** (2026-10-07). Binding architecture and per-slice contracts: `docs/06-resolved-architecture.md`. Plan: 16 work items in waves W1 (01), W2 (02, 07, 08), W3 (03, 09, 10a), W4 (04, 05, 06), W5 (05b, 10b), W6 (11, 12), W7 (13, QA only), W8 (14); at most 3 concurrent agents. Decision D6: zero schema migrations in this handoff (canonical = Markdown, derived = disposable files); a v9 needs a PM amendment and a single owner. Human checks H1-H10 are in the architecture doc, section 5.

## Declared state

- Branch `task/jarvis-memory-intelligence-knowledge` from `origin/main` 5ee4345 (2026-10-07). No `dev` branch, no `docs/workflows/AGENT_TASK_LIFECYCLE.md`: Drive queue IDs from project memory used (fallback).
- Handoff origin: Drive `to-do` (`1V5doC6rNlTqIbFmjKdgwQPxS1baWHpOM`), planning snapshot `main@2ced8dd` (2026-09-12), mirrored as S0 (`00a2464`). The Human must move the folder `to-do` -> `current` (the Drive connector cannot move).
- Handoff defects: `task.json` belongs to another handoff (`jarvis-subagent-routing-continuous-self-dev`) and is ignored; SLICE.md files are generic templates (Slice 00 writes `docs/06-resolved-architecture.md` and a "Slice 00 contract" per slice); the LOG says the upload was reconstructed after a failure.
- Task Type vocabulary does not exist: gate waived on the Human's earlier precedent (settings, observability, category2, bare hands); `task_type` stays null.

## Blind audit (code and docs only, before reading handoff docs)

- Three unconnected memories: (1) V1 `MarkdownMemoryBackend` (`jarvis/adapters/markdown_memory.py`, Markdown canonical, FTS5 index `.jarvis/index.sqlite3` disposable) behind `MemoryBackend` (`jarvis/ports/memory.py`), **not wired in the V2 path**; (2) `CONTEXT_GLOBAL/` (`jarvis/adapters/global_context.py`, 12 000 chars, frozen per conversation); (3) Board memory (`BoardMemoryStore`, `FileBoardMemoryStore`, `WorkspaceService`, `jarvis-workspace` MCP, `control_center_workspace.js`), the most mature, linear-scan search.
- Retention classes: `MEMORY_CLASSES` in `jarvis/core/memory_maintenance.py`; the worker only copies `jarvis:retain` notes short -> long term, daily schedule in `v2_app.py`.
- No recall injection into the Brain prompt (the Brain calls search itself). Per-turn Board block budgets: manifest 2 048 chars, summary 2 048 bytes, work context 6 000.
- Absent from the repo: text embeddings, Wiki, CodeGraph, skill/knowledge loadouts, Tencent/MemoryCore, memory settings. Reflex/voice model has no memory write path found (Realtime tool list unverified).
- `_SCHEMA_VERSION = 8` in `sqlite_state.py`: any new state table needs migration v9 + `tests/schema/jarvis.v9.sql`. The derived semantic index is a separate disposable DB: no migration.
- Doc drift: ARCHITECTURE/SECURITY/OPERATIONS still describe the V1 memory path as live; SECURITY's "only `memory_append` mutates memory" is false for Board memory. Two possible memory roots (`runtime.memory_dir` V1 vs `data_root/memory` V2), defaults unverified.
- Reuse, do not reinvent: `MemoryBackend`/`MarkdownMemoryBackend`, `MEMORY_CLASSES`, `BoardMemoryStore` + path safety + error codes, `global_context.py`, `board_hydration.py`/`brain_context.py` budgets, `data_root.py`, `_MIGRATIONS`, "Sessions & Boards" view as the Memory Center base, `agent_routing.py`/`JarvisCatalog`.

## Baseline at 5ee4345 (re-measured, foreground chunks, `JARVIS_DATA_ROOT` scratch)

444 unit files + 73 integration files: about 13 700 passed, 10 failed, about 42 skipped. Chunk lists and raw output in the session scratchpad (`baseline.md`). **Inherited red, not the Slices' to fix:**

| file | count |
| --- | --- |
| tests/unit/test_app.py | 1 (fake settings lack `data_root`) |
| tests/unit/test_barehands_interaction_js.py | 2 (practice frame geometry) |
| tests/unit/test_brain_delegation.py | 1 (stale prompt expectation, settings section) |
| tests/unit/test_interaction_mode_hud_browser.py | 1 (reduced-motion halo, likely headless browser) |
| tests/unit/test_scene_group_drag_js.py | 1 (JS snippet not found) |
| tests/integration/test_testlab_audio_runners.py | 2 (`aec_engaged` False, host) |
| tests/integration/test_testlab_hardware_runners.py | 1 (same) |
| tests/integration/test_testlab_live_runners.py | 1 (same) |

Caveats: one chunk (`cu_02`) timed out once and passed in sub-chunks (RAM slowness, not reproduced); failures were not re-run for determinism. Any failure outside this list is a Slice's.
