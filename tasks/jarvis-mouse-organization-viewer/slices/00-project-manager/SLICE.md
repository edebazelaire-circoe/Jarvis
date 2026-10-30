# Slice 00 - Project Manager readiness gate

## Goal

Act as Project Manager/orchestrator, independently verify the current Jarvis repository and active task context, reconcile this handoff with reality, and return one readiness state before any implementation dispatch.

## Context

The planning baseline is `main` at `c0858a8000e2ca23b57231edb8f46c643080ad07`. Nearby active work includes window/prefab foundation, presentation studio, unified chat/Board drop and memory work. This task intentionally reuses their ownership rather than cloning it.

The user explicitly chose Workspace Task Type `Feature`; verify that it is still a valid current type before dispatch, but do not invent a replacement if the workspace vocabulary changed.

## Canonical Concepts

- `docs/scene-selection-batch.md`
- scene domain / reducer / page interaction code
- Work State and Mission History
- artifact/Board links
- true fullscreen contract
- active task handoffs in Drive and repository

## Scope

### In Scope

- Blind audit current `main` from the mission before trusting planning-time path conclusions.
- Verify scene pointer/multi-selection/resize/context-menu behavior.
- Verify atomic selection command capabilities and identify the minimum missing arbitrary-layout contract.
- Verify current viewer/fullscreen/prefab/document display surfaces.
- Verify Work State, Mission History, artifact relation and cancellation/Ask seams for the agent viewer.
- Inspect active and queued tasks for overlapping ownership and hot files.
- Confirm `Feature` Task Type and frontend agent routing.
- Adjust the Slice graph when fresh evidence proves a dependency/conflict.
- Return `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- No product code edits.
- No implementation dispatch before READY.
- No full test suite.

## Dependencies

### Hard `depends_on`

None.

### Soft `requires`

None.

### Can Start With

This handoff, live GitHub access and Jarvis Drive task folders.

### Produces

- audited reuse/ownership map;
- resolved hot-file conflicts;
- confirmed Task Type/routing;
- corrected dependency graph if needed;
- explicit readiness state.

### Integration Checkpoint

Before any implementation Slice dispatch.

## Implementation Steps

1. Audit the repository from the user-visible goals without first assuming this handoff's file map is correct.
2. Compare findings to `docs/07-current-reuse-map.md`.
3. Inspect `task/to-do`, `task/current`, repository task folders and recent changes for overlap.
4. Verify true fullscreen vs in-app overlay ownership.
5. Verify canonical agent cancellation and question/communication paths.
6. Verify whether any public structured plan/step contract already exists. If not, preserve the degraded no-published-plan design; do not create chain-of-thought exposure.
7. Re-check file ownership boundaries for Slices 01-04 and convergence ownership for Slice 05.
8. Confirm `Feature` is valid and the required frontend Work Agent routing is available or document the approved fallback.
9. Record corrections in task docs and return one readiness state.
10. If READY, dispatch all hard-dependency-ready, parallel-safe Slices 01-04 rather than serializing them.

## Files Likely Touched

Planning/handoff state only. No product code.

## Architecture Constraints

The PM may split, merge, reorder or supersede Slices when current evidence requires it. Preserve the locked product decisions unless a real implementation impossibility requires human escalation.

## Automated Validation

Evidence consistency, task conflict checks and contract/read-model inspection only. Do not run the full test suite.

## Acceptance Criteria

- Readiness state is explicit.
- Current scene/viewer/agent seams are evidence-backed.
- Overlapping active task ownership is reconciled.
- Task Type and frontend routing are resolved.
- Parallel-safe initial Slices are identified from current HEAD, not assumptions.
- No implementation was dispatched before READY.

## Documentation Updates

Update decision/architecture/strategy docs only when fresh evidence invalidates the planning baseline.

## Handoff Notes

The PM executes Slice 00 itself and does not delegate it. The PM never edits product code directly.

