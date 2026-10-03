# Slice 02 — Board memory persistence and safe filesystem access

## Goal
Implement durable Board-scoped free-form memory storage plus the persistence/indexing needed to discover it safely across restarts.

## Context
The agent needs freedom inside a Board workspace, while clients must never gain arbitrary host filesystem access.

## Canonical Concepts
Board workspace root, local data root, path safety, Board persistence.

## Scope
### In Scope
- Board memory root creation and lookup under the configured local data root.
- Safe tree/stat/read/search primitives.
- Safe create/write/mkdir/move/delete primitives.
- Path normalization, traversal rejection and symlink-escape protection.
- Migration/defaults for existing Boards and optional `board_kind` persistence.
- Structured metadata/index needed by the manager without mirroring every file body into SQLite.
- Restart/reopen behavior and orphan/partial handling.

### Out of Scope
- Agent hydration.
- MCP/UI.
- Artifact payload copying.

## Dependencies
Slice 01.

## Implementation Steps
1. Re-audit local-data conventions from prerequisite implementation.
2. Implement backend-derived Board workspace roots.
3. Implement bounded memory file operations and errors.
4. Add persistence/migration/index changes.
5. Add activity events where the prerequisite canonical ledger calls for them.
6. Test crashes/partial writes where practical.

## Files Likely Touched
Local-data adapters, Board repository/migrations, filesystem workspace adapter/service, tests, docs/local-data equivalents.

## Architecture Constraints
Large/free-form memory stays in files. SQLite stores identity/index/management data. Never follow a symlink outside the Board root.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation` for persistence/restart behavior. Unit/integration tests for path safety, mutation semantics and migration.

## Acceptance Criteria
Pre-existing and new Boards have safe durable memory roots; files survive restart; no supported operation can escape the Board root; existing Board state remains readable.

## Documentation Updates
Document Board workspace location, retention and safety model in canonical local-data/Boards docs.

## Handoff Notes
Prefer atomic replace/write patterns already used in Jarvis where applicable.

## Slice 00 contract (agent 0, 2026-10-02)

Binding over the generic sections above; source: `docs/06-resolved-architecture.md`.

- Migration v8 exactly as R2 (`board_artifact_links`), snapshot `tests/schema/jarvis_state.v8.sql`, CLAUDE.md migration procedure. Only this Slice writes a migration.
- Store adapter for links + auto-link of new artifacts to the Session's active Board in the same transaction as the artifact insert (`origin='active_board'`).
- Filesystem adapter `jarvis/adapters/board_memory_store.py` (name may vary): root via `safe_folders.ensure_folder_tree(data_root, ("boards", board_id, "memory"))`; read-side ops tree/stat/read/search with every path re-checked with `safe_folders` (lstat each component, refuse links/junctions); atomic writes (temp + replace) for create/replace/append; limits from R4.
- Tests must include a real junction/symlink escape attempt on Windows (skip with reason only if creation is impossible), `..` traversal, absolute path, reserved names, size limits, migration v7->v8 on a copy of a v7 DB with rows.
- `docs/local-data.md` gains `boards/<board_id>/memory/`.
