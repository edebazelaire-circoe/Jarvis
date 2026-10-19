# Slice 05 — Dossier contract, projection and semantic operations

## Goal

Define and implement the canonical **Dossier** service/projection so the human and Jarvis can work on the active Board's documentary context without creating a parallel storage silo.

## Dependencies

- `01b-derived-interaction-mode` (Slice 00 rework P1: this Slice shares `jarvis/protocol/server.py`, `jarvis/runtime/control_center.py`, `docs/mcp/tool-contract.md` and `test_mcp_catalog.py` with 01b, and `docs/boards.md` with 01a/02). The former dependency on Slice 03 is removed: no wheel file is touched, so it may run beside Slices 02-04 (3-agent limit; `docs/boards.md` is a merge zone with Slice 02 — edit distinct sections and merge carefully).

## Slice 00 reconciliation (read first)

`../../docs/08-readiness-audit.md` §6 lists what already exists (reuse as-is: memory tree/stat/read/search/write/mkdir/move/delete through `WorkspaceService` + Core `/v1/workspace/boards/{id}/memory/*` + relay `/api/workspace/...` + MCP `board_memory_*`; v8 Board-artifact links and `board_artifacts` / `board_artifact_link`; artifact relations; per-Board presentation sources; `session_activity` family `board` for "what changed"; windows bound to a file via `payload.source_path`) and the five genuinely missing operations: composed Dossier listing, scene -> durable-backing resolver, composed Ranger, present-from-Dossier, agent -> UI navigation seam. No new table is needed.

Naming trap to settle in `docs/dossier.md`: a **scene artifact** (`kind=artifact` scene object: title/summary/items, `docs/scene-model.md` › *Semantic artifacts*) is not a **registry Artifact** (`artifacts` table, `docs/artifacts.md`). Ranger of a scene artifact or scene note materializes its payload once into Board memory (Markdown with provenance) through `memory_write`; Ranger of a scene object already bound to a durable source (`source_path` inside the Board's memory root, or a registry-Artifact reference) only confirms the link. A scene reference to a registry Artifact is a JSON payload key (no scene DDL; same rule as `source_path`, emitted only when set). `ScenePayload.from_payload` validates keys with `check_wire_keys` (`jarvis/domain/scene.py:688`), which refuses unknown keys: an older binary will refuse such a payload, so `docs/dossier.md` must state it in its rollback notes.

Extension point for the composed listing: `WorkspaceService.board_inspect` / `_memory_summary` (`jarvis/core/workspace_service.py:406-463`).

## Canonical context

Planning-time sources already exist:

- Board memory (`<data_root>/boards/<board_id>/memory/`)
- Artifact registry + Board links/provenance
- Workspace inspection/memory mutation API
- Scene model/links
- SessionContext (must remain separate from durable Board memory)

The existing deep Workspace manager is diagnostic/operability UI; Dossier is a new human product projection over canonical sources.

## Scope / implementation steps

1. Audit current Board memory, Artifact links, presentation/document sources, workspace API/MCP and scene links at HEAD.
2. Write a canonical Dossier contract before UI: entry identity, source locator, kind, title, preview/open capability, provenance, modification metadata and which data is human-facing vs advanced.
3. Prefer an adapter/service that composes existing Board memory + Board-linked Artifacts. Do not add a new database/table unless the audit proves a missing durable concept cannot be represented safely.
4. Define Dossier browse/tree/list/search/read operations with bounded payloads and existing path safety.
5. Define semantic `store/ranger` operation for scene content:
   - identify existing durable backing;
   - if absent and content is eligible, materialize once into Board memory or Artifact with provenance;
   - ensure association with active Board;
   - report durable locator before caller archives scene representation;
   - refuse unsupported execution-only objects rather than silently dumping them.
6. Define `present/show on Board` operation: resolve Dossier item and create/reuse a scene representation pointing at the same durable source, with requested representation/layout; do not duplicate content by default.
7. Define edit/correction operations using current Board-memory/Artifact owners. Human edits must be visible to the canonical Board context/retrieval path used by agents.
8. Define “what changed” metadata from canonical timestamps/activity where available; do not fabricate usage/read receipts.
9. Define advanced agent/provenance view inputs separately from default human content.
10. Expose the same semantic operations to manual UI and Jarvis/agent routing through the appropriate existing HTTP/MCP gateway. No arbitrary filesystem bypass.
11. Add a bounded context/retrieval rule: Dossier content is accessible/indexable, but not all documents are injected wholesale into every turn.
12. Document archive behaviour: archived Boards remain readable and write rules follow the canonical Board memory contract.

## Out of scope

- Full Dossier visual UI (Slice 07).
- Autonomous finished-task summarization.
- Replacing SessionContext with Board Dossier.
- Exposing arbitrary host filesystem paths.

## Files likely touched (verified at HEAD 2fb66040)

- `jarvis/core/workspace_service.py`, `jarvis/domain/board_memory.py`, `jarvis/adapters/board_memory_store.py`, `jarvis/adapters/sqlite_board_artifact_links.py`, `jarvis/adapters/sqlite_artifacts.py` (read side)
- Core workspace routes (`jarvis/protocol/server.py` or their routes module), relay in `jarvis/runtime/control_center.py`, MCP `jarvis/runtime/workspace_mcp.py` (+ `docs/mcp/tool-contract.md` §10.12)
- scene reference only where needed: `jarvis/domain/scene.py` (payload key), `jarvis/runtime/display_mcp.py`
- new focused `jarvis/domain/dossier.py` / `jarvis/core/dossier_service.py` if cleaner
- `docs/dossier.md` (new), `docs/boards.md`, `docs/artifacts.md`, `docs/scene-model.md`
- tests: new `test_dossier_*`, plus `test_workspace_inspection_api.py`, `test_workspace_memory_mutations.py`, `test_workspace_mcp.py`, `test_board_memory_store.py`, `test_board_memory_contract.py`, `test_board_artifact_links.py`, `test_scene_selection.py`, `test_scene_batch.py`, `test_mcp_catalog.py`

## Architecture constraints

- Canonical source content has one owner; Dossier is a projection.
- Safe Board-memory path rules remain enforced.
- Scene representation identity is not document identity.
- `Ranger` never archives the only visible/source copy until durable persistence is confirmed.
- Agent/manual commands converge on the same service semantics.
- Board boundaries are strict; no cross-Board context merge.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation` in isolated data roots
- `agent-trace-analysis` with real agent/tool traces for Dossier browse/search/edit/store/present flows
- Board memory/artifact/workspace/scene/MCP regression tests

## Acceptance criteria

- Dossier lists useful Board memory documents and linked Artifacts without duplicate canonical copies.
- Entries open through bounded/safe locators.
- Human edit updates the same durable source agents subsequently see/retrieve.
- Ranger can preserve eligible ephemeral content once and returns a durable locator.
- Ranger refusal does not discard scene content.
- Present-from-Dossier creates a scene representation pointing to the same source.
- Manual UI and agent tool path produce equivalent semantics/codes.
- Default Dossier model does not require raw debug IDs/logs.

## Documentation updates

Add/update canonical Dossier/Boards/Artifacts/MCP docs and documentation-level map.
