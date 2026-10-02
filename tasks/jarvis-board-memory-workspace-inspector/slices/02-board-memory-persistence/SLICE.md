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
