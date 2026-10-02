# Slice 04 — Workspace relationship and inspection API

## Goal
Expose a coherent backend/API read model for Sessions, Boards, bindings/conversations, memory, artifacts/provenance and activity without forcing activation.

## Context
The human manager and MCP should consume one shared truth instead of each reconstructing relationships independently.

## Canonical Concepts
BoardRepository/services, Session history, BoardConversationBinding, SessionContext, Artifact registry, canonical activity ledger.

## Scope
### In Scope
- List/get historical Sessions.
- Inspect one Session and its Board/context/binding relationships.
- Inspect one Board with memory summary/tree metadata and refs.
- Inspect bindings/conversation/agent lifecycle.
- List/search/filter artifacts by Board/Session/Context/time/kind.
- Inspect artifact provenance.
- Bounded activity/trace references useful for debugging.
- Stable JSON schemas/errors/pagination/bounds.

### Out of Scope
- File mutation.
- UI rendering.
- MCP wrappers.

## Dependencies
Slices 02-03; prerequisite Artifact registry/activity ledger.

## Implementation Steps
1. Define typed inspection DTOs/read models.
2. Add service methods reusing canonical stores.
3. Add Control Center/Core routes at the correct owner boundary.
4. Ensure reads are side-effect free.
5. Add pagination/bounds for histories and trees.

## Files Likely Touched
Core workspace/Board services, artifact service, Control Center routes, DTO/schema modules, tests.

## Architecture Constraints
No UI-specific reconstruction in backend. No duplicate artifact records. Reads must never call Board switch.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation`. Integration tests over real SQLite/local-data adapters with multiple Sessions/Boards/artifacts.

## Acceptance Criteria
One API can explain the Session/Board/binding/context/artifact/memory relationships accurately and safely for current and historical state.

## Documentation Updates
Canonical API/Boards/artifact docs with bounds and side-effect guarantees.

## Handoff Notes
Design outputs for both human debug UI and model consumption, but do not optimize one by hiding necessary IDs from the other.

## Slice 00 contract (agent 0, 2026-10-02)

Binding over the generic sections above; source: `docs/06-resolved-architecture.md`.

- `WorkspaceService` reads per R4 (session_list/get for closed Sessions too, board_inspect, relations, artifact_list by board via v8 links, artifact_relations reuse, activity for any Session).
- Core `/v1/workspace/*` routes + Control Center `/api/workspace/*` relay; `/api/boards*` responses gain `board_kind`.
- Side-effect-free proof: tests that snapshot `active_board_id`, foreground binding, speech authority and `jarvis.sqlite3` row counts before/after every read.
- Pagination (opaque cursor, limit <= 100) and bounds on every list.
