# Slice 00 — Project Manager Readiness Gate

## Goal

Act as the Project Manager and orchestrator for this handoff. Establish whether the current Jarvis repository is ready for the planned implementation before delegating any product-code Slice.

## Context

The handoff was created from project conversations and an existing Drive task, but the Jarvis GitHub repository was not accessible to the task-creation connector. Repository reality therefore outranks every implementation assumption in this handoff.

## Canonical Concepts

Scene ownership, window families, prefab definition, prefab instance, Session/Board/Context boundaries, Presentation interaction mode.

## Scope

### In Scope

- Perform an **independent blind repository/context audit before reading `docs/05-documentation-levels.md` conclusions**.
- Find canonical repository docs, existing prefab/runtime code, scene/window code, tests, and any Rework FENETRES artifacts.
- Inspect the existing Presentation task only to establish boundaries/dependencies, not to merge scopes.
- Reconcile the audit with this handoff.
- Resolve valid existing Workspace Task Types for every Slice.
- Split/reorder/supersede/add Slices when repository evidence requires it.
- Produce one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- Editing product code.
- Implementing a Slice on behalf of a Work Agent.

## Dependencies

None.

## Implementation Steps

1. Audit current repository architecture without first relying on this handoff's documentation-level table.
2. Locate the real scene/window/prefab contracts and implementations.
3. Locate existing tests and frontend architectural constraints.
4. Recover prior Rework FENETRES decisions from durable repository/task evidence.
5. Identify overlap/conflict with current Presentation implementation work.
6. Reconcile findings with all docs and Slice contracts in this handoff.
7. Resolve each Slice's valid Task Type from the current Workspace vocabulary.
8. Record readiness state and required planning changes.
9. Before each later Slice dispatch, perform a targeted freshness check for files/contracts that Slice will touch.

## Files Likely Touched

Handoff planning/docs only. No product code.

## Architecture Constraints

Repository evidence is authoritative. Never create a second prefab runtime or second scene contract if a canonical one already exists.

## Automated Validation

- Verify all Slice IDs/dependencies remain valid after reconciliation.
- Verify no two Slices claim ownership of the same canonical contract without an explicit dependency.
- Verify Task Types resolve to existing Workspace values.

## Acceptance Criteria

- Blind audit is documented.
- Handoff drift is reconciled.
- Every planned Slice is implementable against the current repository.
- Task Types are resolved or a real blocker is recorded.
- Readiness state is explicit.
- No implementation Slice is dispatched unless state is `READY`.

## Documentation Updates

Update handoff docs/Slices where the audit proves them stale. Do not rewrite product docs speculatively.

## Handoff Notes

You are the Project Manager. Execute this Slice yourself; do not delegate it.

QA doctrine for all later Slices: baseline `qa-verification`; code adds `code-review`; user-visible/runtime adds `runtime-validation`; agent/tool/runtime changes add `agent-trace-analysis`. Machine validation precedes Human checks.
