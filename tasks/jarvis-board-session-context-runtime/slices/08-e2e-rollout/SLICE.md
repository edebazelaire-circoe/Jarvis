# Slice 08 - End-to-end proof, rollout, and close-out

## Goal
Prove the complete prototype across legacy migration, multiple Boards, multiple Sessions, direct Voice ownership, background work, interaction-mode restoration, UI/MCP parity, notifications, restart, and documentation.

## Context
The feature crosses persistence, Core/Brain/Voice, Control Center, MCP and background events. Unit tests alone cannot prove the user-facing context boundary.

## Canonical Concepts
Full Board/Session runtime contract; single speech authority; Board-scoped mode; global Board-attributed notifications; UI/MCP parity.

## Scope
### In Scope
E2E scenarios for default-Board migration, create Board B, A->B->A in one Session, start a new Session on A, background task completion on inactive Board, restart/absence, Board mode restoration, MCP/UI parity, archive guards, switch failure rollback, and trace proof of one speech authority. Finalize canonical docs and link the 2026-09-28 new-session idea to this implemented task according to repo conventions.
### Out of Scope
Galaxy/minimap/cosmos Board navigation or deep semantic inter-Board Brain querying.

## Dependencies
01, 02, 03, 04, 05, 06, 07.

## Implementation Steps
Build a scenario matrix; run baseline QA + code review + runtime validation + agent-trace analysis; capture real traces for switch/new-session/background-work flows; perform Human checks only after machine QA is clean; reconcile all docs/UI/MCP wording; record only genuinely deferred discoveries in Issues.

## Files Likely Touched
Integration/runtime tests, canonical docs, MCP docs, Control Center help/indexes, `idees/2026-09-28-nouvelle-session-a-la-voix.md`, and small fixes required by validation.

## Architecture Constraints
Do not weaken invariants or merge Board contexts merely to make validation pass. Existing background work must survive Board/session transitions.

## Automated Validation
Full relevant test suite; migration/restart proof; A/B/A and new-Session scenarios; real runtime traces showing exactly one speech authority; notification persistence; UI/MCP parity; voice/scene/mode/task-alert regressions.

## Acceptance Criteria
All machine QA passes; old state migrates; Voice never has dual Board authority; new Session gives a clean conversation without changing Board/task state; background work survives; Board modes restore; notifications survive absence; UI and MCP expose the same V1 semantics; Human acceptance passes.

## Documentation Updates
Finalize Board/Session architecture, migration notes, MCP contract, Control Center help, and idea/task linkage.

## Handoff Notes
Use the valid testing/close-out Task Type resolved in Slice 00. Human acceptance follows maximal machine validation.
