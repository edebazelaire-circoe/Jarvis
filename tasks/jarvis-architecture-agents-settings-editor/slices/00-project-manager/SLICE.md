# Slice 00 - Project Manager readiness gate

## Goal

Act as Project Manager/orchestrator, independently verify the repository and project context, reconcile this handoff, and produce a readiness state before any implementation dispatch.

## Context

This task refines the Jarvis Settings reorganization and supersedes only its old Agents/models Slice 04. The handoff intentionally separates six parallel-ready implementation branches and one shared integration convergence.

## Canonical Concepts

- `docs/ARCHITECTURE.md`
- `docs/subagent-roles.md`
- current Settings IA docs/task
- Tool Brain ownership/runtime contracts
- current routing/model catalog contracts

## Scope

### In Scope

- Blind audit current `main` from task goals, before trusting file paths in this handoff.
- Confirm actual current brains/endpoints and their legal runtime connections/mutability.
- Confirm seven-role registry or record any live changes.
- Confirm routing/model catalog/current Settings shell state.
- Inspect active/queued overlapping tasks.
- Mark old `jarvis-settings-ui-reorganization` Slice 04 superseded/blocked from concurrent execution.
- Resolve valid Workspace Task Type for every implementation Slice; do not invent values.
- Adjust Slice graph if fresh repository evidence invalidates ownership assumptions.
- Return one readiness state.

### Out of Scope

- Do not edit product code.
- Do not dispatch implementation before `READY`.

## Dependencies

### Hard `depends_on`

None.

### Soft `requires`

None.

### Can Start With

This handoff, repository access, Drive task context and the two reference images.

### Produces

- audited current architecture/role/routing facts;
- resolved Task Types;
- confirmed/safely adjusted dependency graph;
- one readiness state.

### Integration Checkpoint

Before any implementation Slice dispatch.

## Implementation Steps

1. Perform a blind search/audit from the task mission.
2. Compare findings to `docs/08-current-reuse-map.md` and `docs/06-functional-spec.md`.
3. Verify actual Voice/Core/Tool Brain/runtime ownership and connection invariants.
4. Verify Settings shell/task overlap and prevent concurrent obsolete Slice 04 work.
5. Verify file conflict boundaries for Slices 01-06.
6. Resolve Task Type and frontend Work Agent routing.
7. Return `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
8. If `READY`, dispatch every hard-dependency-ready parallel-safe Slice, not only one.

## Files Likely Touched

Planning/handoff state only; no product code.

## Architecture Constraints

The PM may split/merge/reorder/supersede Slices when fresh evidence requires it. Preserve the core product decisions unless a direct repository impossibility requires human escalation.

## Automated Validation

Review evidence consistency and conflict boundaries. **Do not run the unit test suite in Slice 00.**

## Acceptance Criteria

- Readiness state is explicit.
- Current real graph baseline and edge mutability are evidence-backed.
- Old conflicting Slice 04 is not concurrently executable.
- Every implementation Slice has a valid existing Task Type before dispatch.
- Initial ready set is dispatched concurrently where safe.

## Documentation Updates

Record any plan corrections in the task decision/strategy docs before dispatch.

## Handoff Notes

The PM executes this Slice itself and never delegates it. The PM never edits product code directly.
