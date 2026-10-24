# Slice 00 — Project Manager readiness gate

## Goal

Act as the Project Manager/orchestrator for `refonte-ui-settings`, prove that the handoff matches the live repository, resolve execution metadata, and only then dispatch implementation work.

## Context

You are the receiving Project Manager. Execute this Slice yourself; do not delegate it. The user explicitly required a real Settings UI refactor with the supplied images embedded in the handoff and page-specific UI Slices.

The task creator observed `main` at `be80ab9baed0ea3819af5e916b102f3835663ce3`, but freshness must be rechecked before dispatch.

## Canonical Concepts

- `README.md`
- `docs/00-overview.md`
- `docs/01-decision-log.md`
- `docs/06-visual-contract.md`
- `docs/07-existing-task-coordination.md`
- existing Jarvis Settings, Architecture/Agents and Memory contracts in repository/Drive

## Scope

### In Scope

- Perform an independent blind audit of current `main` before relying on this handoff's conclusions.
- Identify current Settings shell/routes/components/styles and page-specific controllers.
- Reconcile live code with this handoff and the existing Settings/Architecture/Memory tasks.
- Confirm all five image references exist and are readable.
- Resolve valid Workspace Task Types for all implementation Slices; do not invent values.
- Identify hot-file collisions and adjust Slice ownership/dependencies if necessary.
- Select one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`.
- Repair stale planning documentation or split/reorder/add Slices when evidence requires it.
- Before every later Slice dispatch, perform a targeted freshness check for the files/contracts that Slice relies on.

### Out of Scope

- Do not edit product code.
- Do not perform the visual refactor yourself.
- Do not weaken the five page-specific visual acceptance gates to speed dispatch.

## Dependencies

None.

## Implementation Steps

1. Audit current repository head, Settings entry points, routing/registry, shared styles, page modules and existing screenshot/E2E infrastructure without first using this handoff's implementation conclusions.
2. Inspect the live state of the three related Drive tasks named in `docs/07-existing-task-coordination.md`.
3. Reconcile the audit with this handoff. Record any stale paths or moved responsibilities in the task documentation before dispatch.
4. Verify `references/ui/` contains all five exact supplied images and that every page Slice points to the right file.
5. Resolve current Workspace Task Type vocabulary and update Slice `metadata.json` planning fields where required. Never fabricate a type.
6. Decide whether the five page Slices can share Slice 01 primitives without hot-file conflicts. Split shared CSS/HTML ownership if needed.
7. Return exactly one readiness state. Do not dispatch implementation below `READY`.
8. Once `READY`, dispatch Slice 01. After Slice 01 is approved, dispatch every page Slice that is dependency-ready and parallel-safe.
9. For each completed implementation Slice, require baseline `qa-verification`; code changes add `code-review`; user-visible/runtime behavior adds `runtime-validation`; runtime/agent semantic changes add `agent-trace-analysis` when applicable.
10. Treat every regression introduced by the task as blocking. Human validation happens only after machine QA is clean.

## Files Likely Touched

- Task handoff files only if planning repair is necessary.
- No product code in this Slice.

## Architecture Constraints

- The Project Manager may repair task planning but does not implement product code.
- Visual references are mandatory evidence, not optional inspiration.
- Existing runtime contracts remain the data/behavior source of truth.

## Automated Validation

- Confirm all required handoff files and Slice directories exist.
- Parse every JSON file.
- Verify every `depends_on` points to a Slice in this handoff.
- Verify Human-check IDs are globally unique.
- Verify every UI Slice includes its image path and required frontend skills.
- Verify repository HEAD and related task states are fresh enough for dispatch.

## Acceptance Criteria

- Readiness state is explicitly one of the four allowed values.
- No implementation work is dispatched below `READY`.
- Page Slices remain explicit, reference-linked and executable.
- Valid Task Types are resolved or the relevant Slice is blocked rather than assigned an invented type.

## Documentation Updates

Update handoff paths/contracts only when the blind audit proves they are stale. Record substantial out-of-scope discoveries under `Issues/`.

## Handoff Notes

The purpose of this gate is to prevent a visually ambitious task from drifting into stale file assumptions or conflicting with still-running Settings work.
