# Slice 02 - SessionContext persistence and workspace filesystem

## Goal

Persist the Slice 01 contract in the canonical local-data architecture and create a safe filesystem workspace for each Context.

## Context

Current `jarvis.sqlite3` uses append-only versioned migrations and schema snapshots. Data lives under the configured Jarvis data root, outside git. Context contents are intentionally agent-shaped, while lifecycle/index data is backend-shaped.

## Scope

### In scope

- Add versioned `jarvis.sqlite3` schema/repository changes for SessionContext and any Session lifecycle fields required by Slice 01.
- Add safe deterministic paths under `<data_root>/sessions/<session_id>/contexts/<context_id>/`.
- Add repository/service operations for current/active/list/get/create/activate contexts.
- Enforce one-active-context at database level where practical plus service/domain level.
- Add workspace path traversal/symlink/atomic-create defenses.
- Add minimal migration/adoption behavior for an existing open Session on upgrade without inventing fake historical Contexts.
- Update schema snapshot and local-data documentation.

### Out of scope

Agent writes/summary behavior, generic artifacts, capture runtime.

## Architecture constraints

- SQLite stores lifecycle/index metadata, not the agent's arbitrary Context document tree.
- Context workspace location derives from IDs; arbitrary absolute paths are not trusted input.
- Existing Board rows/bindings remain valid.
- Migration follows `docs/local-data.md`: append, backup, transaction, fresh/migrated convergence.

## Files likely touched

`jarvis/adapters/sqlite_state.py`, repository/ports/services selected by Slice 01, data-root helpers, `tests/schema/`, `docs/local-data.md`, persistence tests.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation` for migration/startup behavior. Test clean DB, migration from inspected current schema, interrupted folder creation, invalid paths, concurrent activation and schema snapshot.

## Acceptance criteria

A migrated and a fresh install converge on the same valid schema; an open Session has one valid active Context after adoption; workspace paths are safe and durable; no Board-scoped foreign key is required for new Context data.
