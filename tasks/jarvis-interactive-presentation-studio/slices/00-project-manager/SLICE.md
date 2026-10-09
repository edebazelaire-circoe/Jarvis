# Slice 00 - Project Manager Readiness Gate

## Goal
Act as Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Establish whether the task is safe and current enough to dispatch.

## Context
The live repository already contains a mature PRESENTATION interaction mode, while the Scene/Prefab foundation is an active separate task. Planning evidence also includes a legacy Tool Brain handoff whose storage location is not canonical for Jarvis. Repository reality wins.

## Canonical Concepts
Project Manager readiness, Presentation mode, Scene/Prefab foundation, Tool Brain seam, documentation levels.

## Scope
### In Scope
- Blind repository/context audit before reading the handoff's documentation-level conclusions.
- Reconcile repository state, active Drive tasks and this handoff.
- Resolve current Workspace Task Types for every Slice.
- Confirm or repair dependencies/order/scope.
- Validate the provisional live-edit-during-presentation assumption.
- Produce one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.

### Out of Scope
- Product implementation code.

## Dependencies
None.

## Implementation Steps
1. Blind-audit repository contracts, implementation, tests and docs relevant to Presentation, scene/window/prefab, UI orchestration, autosave/project artifacts and agent tools.
2. Inspect current dependent task state, especially `jarvis-scene-window-prefab-foundation`.
3. Only then read/reconcile this handoff's architecture and documentation levels.
4. Resolve valid Workspace Task Types; do not invent one.
5. Repair this task plan if repository reality makes slices stale, redundant, too broad, or incorrectly ordered.
6. Record readiness state and evidence.
7. Do not dispatch below `READY`.
8. Before every later Slice dispatch, perform a targeted freshness check for files/contracts that Slice depends on.

## Files Likely Touched
Task planning/docs only. Do not edit product code in Slice 00.

## Architecture Constraints
The Project Manager may split, reorder, supersede or add Slices, but may not silently change locked user intent.

## Automated Validation
- Dependency graph has no missing Slice IDs/cycles.
- Every implementation Slice has a valid existing Task Type before dispatch.
- Cross-task dependencies are evidence-backed.
- Terminology is aligned with the live repository.

## Acceptance Criteria
- A documented readiness state exists.
- No implementation is dispatched below `READY`.
- Current repository evidence replaces planning guesses.

## Documentation Updates
Update task docs/slice contracts when reconciliation requires it.

## Handoff Notes
This Slice is executed by the Project Manager directly.
