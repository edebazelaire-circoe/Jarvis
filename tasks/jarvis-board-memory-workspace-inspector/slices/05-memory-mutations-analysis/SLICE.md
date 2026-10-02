# Slice 05 — Board memory mutations and explicit historical analysis

## Goal
Add safe semantic mutation operations for Board memory and make explicit historical analysis practical for agents without switching the active Board.

## Context
The user wants Jarvis to freely maintain Board memory and send an agent to inspect old work.

## Canonical Concepts
Board memory workspace, explicit target Board, historical inspection.

## Scope
### In Scope
- API/service operations for create/write/update/mkdir/move/rename/delete inside Board memory.
- Explicit target Board requirement for inactive Board writes.
- Bounded text reads/search suitable for analysis.
- Optional snapshot/hash/version metadata if existing infrastructure supports it cleanly.
- Activity/audit events for mutations.
- Delegated-agent use case fixtures/tests at service boundary.

### Out of Scope
- Generic arbitrary-host filesystem tools.
- Automatic semantic rewriting of dormant Boards.
- Full version-control system for Board memory.

## Dependencies
Slices 02 and 04.

## Implementation Steps
1. Define mutation semantics and conflict/error behavior.
2. Implement against safe workspace adapter.
3. Emit canonical activity records where applicable.
4. Add bounded search/read outputs.
5. Prove inactive Board operations do not affect active Board/binding.

## Files Likely Touched
Workspace service/adapter, routes, activity integration, tests.

## Architecture Constraints
Destructive deletes are explicit; writes cannot escape root; inactive Board mutation is never implicit.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation`. Path-safety/property tests and multi-Board concurrency/integration tests.

## Acceptance Criteria
Jarvis can maintain Board memory through semantic operations and analyze old Boards by explicit ID while the user's foreground Board remains unchanged.

## Documentation Updates
Board-memory operation contract and error semantics.

## Handoff Notes
If binary files are needed later, add an artifact workflow rather than turning text-memory endpoints into arbitrary blob upload.
