# Slice 02 - Board persistence, workspace scoping, and interaction mode

## Goal
Implement BoardStore using canonical persistence, migrate current single-workspace state to default Board, persist context/workspace references and Board-scoped interaction mode, keep Core as effective live mode owner, and make migration idempotent.

## Context
Jarvis is moving from an implicit single-workspace model to first-class persistent Boards while preserving existing voice, background work, alerts and interaction-mode behavior.

## Canonical Concepts
Board; Session; BoardConversationBinding; deterministic runtime; single speech authority; Board-attributed notifications; jarvis-console parity.

## Scope
### In Scope
Implement BoardStore using canonical persistence, migrate current single-workspace state to default Board, persist context/workspace references and Board-scoped interaction mode, keep Core as effective live mode owner, and make migration idempotent.
### Out of Scope
Galaxy/minimap visualization; global intermediary reasoning Brain; all-Boards prompt fusion; unrelated runtime rewrites.

## Dependencies
01

## Implementation Steps
Audit current owner files first; implement at canonical boundaries; preserve migration/backward compatibility; add stable errors/reasons and automated tests before exposing behavior.

## Files Likely Touched
Resolve exact files in Slice 00 freshness audit. Expected areas: domain contracts, persistence/runtime managers, Control Center, Core/Voice ownership, background events, MCP catalog/metadata, tests.

## Architecture Constraints
No global LLM Brain. No dual speech authority. No task cancellation merely from Board/session changes. UI/MCP never bypass runtime invariants.

## Automated Validation
Baseline qa-verification; code-review for code; runtime-validation for behavior; agent-trace-analysis for agent/tool/MCP/runtime changes.

## Acceptance Criteria
The behavior matches the Goal, preserves locked invariants, passes machine QA, and introduces no regression caused by this Slice.

## Documentation Updates
Update canonical Board/Session/MCP/Control Center docs affected by the Slice.

## Handoff Notes
Coding work loads /caveman and /coding-guideline. Slice 00 performs a targeted freshness check before dispatch.

## Slice 00 contract (authoritative, overrides the generic sections above)

Architecture: `docs/06-resolved-architecture.md`. Readiness: `slices/00-project-manager/READINESS.md` (inherited red tests = not yours).

- `jarvis/adapters/sqlite_state.py`: migration v3 (`work_boards`, `jarvis_sessions`, `board_conversation_bindings`), `_SCHEMA_VERSION=3`, repository methods implementing `BoardRepository`. Fix stale comment `v2_app.py:104-106`.
- `jarvis/core/board_service.py` (storage part): list/get/get_active/create/update/archive (active Board cannot be archived; archived Boards cannot be switched to), `ensure_default()` idempotent migration (section H of 06), Board-scoped interaction mode listener + restore at Core start (section F).
- Routes `/v1/boards`, `/v1/boards/{id}`, `/v1/boards/{id}/archive`, `GET /v1/boards/active` in `jarvis/protocol/server.py`; wiring in `jarvis/core/v2_app.py`.
- `docs/interaction-mode.md` + `core/interaction_mode.py:171` docstring: persisted preference now per Board.
- Tests: v2->v3 migration with backup, double run, crash mid-migration; CRUD + guards; mode survives Core restart per Board; legacy mode migrated once. `test_interaction_mode_*`, `test_sqlite_*`, `test_v2_*` stay green.
