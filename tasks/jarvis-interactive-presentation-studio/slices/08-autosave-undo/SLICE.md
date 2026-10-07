# Slice 08 - Continuous Autosave and Bounded Undo/Redo

## Goal
Make the active presentation variant crash-safe while keeping only a short efficient edit history.

## Context
The user explicitly rejected durable linear snapshots. Current state should always be saved; undo is short-lived.

## Canonical Concepts
Autosave, active variant, atomic persistence, undo/redo ring, crash recovery.

## Scope
### In Scope
- Debounced/atomic autosave after committed edits.
- Restart recovery of current active variant.
- Bounded undo/redo ring for recent edits.
- Clear redo-on-new-edit semantics.
- Explicit behavior when undo history is unavailable after restart.

### Out of Scope
- Durable historical checkpoints/snapshots.
- Creative variant branches (later Slice).

## Dependencies
- `02-presentation-artifact-contract`
- `05-semantic-edit-api`

## Implementation Steps
1. Reuse existing local project-data location and atomic-write conventions.
2. Persist active state only after successful edit transaction.
3. Add bounded inverse-operation history.
4. Simulate process interruption during write.

## Files Likely Touched
Presentation persistence/edit services and tests.

## Architecture Constraints
Undo memory must have a hard bound. Autosave is durable; undo is not promised across restart.

## Automated Validation
Atomic-write, crash/restart, ring bound, undo/redo correctness, malformed recovery fixture tests.

## Acceptance Criteria
Killing/restarting Jarvis cannot revert the presentation behind the last committed autosaved state.

## Documentation Updates
Document persistence and undo guarantees.

## Handoff Notes
Use `/caveman` and `/coding-guideline`.
