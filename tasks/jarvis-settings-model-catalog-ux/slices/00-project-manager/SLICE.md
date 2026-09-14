# Slice 00 — Project Manager readiness and orchestration gate

## Goal

Act as Project Manager. Reconcile the Settings/catalog redesign with the live Control Center, routing implementation, model/CLI catalogs, and voice configuration contracts before dispatch.

## Context

The inspected `main` already contains routing backend/UI, live provider catalogs, CLI catalogs, and a large Control Center settings surface.

## Canonical Concepts

- Control Center settings IA
- routing policy vs user-facing routing UI
- ModelCatalog
- CLI catalog
- voice stack settings
- Workspace Task Type vocabulary

## Scope

### In Scope

- Blind audit current Control Center nav/settings schemas, routing UI and APIs, catalog fields, CLI/sub-agent semantics, voice options and tests.
- Determine exact current semantics of duplicated sub-agent mode if it exists; do not guess.
- Coordinate turn-taking settings with the voice-arbitration task.
- Resolve Task Types and baseline QA.

### Out of Scope

- Product code edits.
- Deleting runtime routing because the UI name is removed.

## Dependencies

None.

## Implementation Steps

1. 1. Before reading `docs/05-documentation-levels.md` conclusions, perform an independent blind audit of the live repository against this task's goals.
2. 2. Inspect current `main`, git status/worktrees, active parallel branches, relevant canonical docs, implementations, and narrow tests. Record the live SHA.
3. 3. Reconcile the blind audit with this handoff. Correct stale file predictions, split/reorder/add/supersede Slices when necessary, but do not change locked user intent silently.
4. 4. Resolve every implementation Slice to a valid current Workspace Task Type. If no valid type exists, keep that Slice blocked and escalate instead of inventing a type.
5. 5. Establish baseline automated validation and likely integration/conflict zones.
6. 6. Declare exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
7. 7. Dispatch nothing unless the state is `READY`.
8. 8. Immediately before every later Slice dispatch, perform a targeted freshness check of that Slice's dependencies and affected code.

## Files Likely Touched

- (handoff planning files only)

## Architecture Constraints

- Live provider/CLI availability remains authoritative for usability.
- Do not silently discard saved routing preferences during UI migration.

## Automated Validation

- Identify current settings/catalog/routing/control-center tests and release verifier.
- Identify UI runtime validation path.

## Acceptance Criteria

- New IA is reconciled with live backend capabilities.
- Auto/Dupliqué semantics are located or explicitly marked as a new contract.
- One readiness state declared.

## Documentation Updates

Repair planning docs and dependencies when live code differs.

## Handoff Notes

Frontend Slices require `/impeccable` and Claude routing when supported.

Mandatory QA doctrine for every implemented Slice:
- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine QA; escalate machine validation to the maximum reasonable level first.
