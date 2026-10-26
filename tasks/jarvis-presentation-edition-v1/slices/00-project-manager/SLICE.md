# Slice 00 — Project Manager readiness gate

## Goal
Act as the Project Manager and orchestrator for this handoff. Execute this Slice yourself; never delegate it.

## Context
The handoff was built against `main` SHA `2d6ca879afac7a0e773598cff0872b4f819fa876`. Jarvis changes quickly and multiple Settings/Presentation tasks may overlap.

## Scope
### In Scope
- independently audit current repository/docs/runtime before trusting this handoff;
- reconcile current `main` with the locked V1 product decisions;
- inspect overlap with active/current/to-do Jarvis tasks;
- resolve valid Workspace Task Types for each implementation Slice;
- produce exactly one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`;
- repair/split/reorder/supersede/add planning Slices when evidence requires it.

### Out of Scope
- no product-code edits;
- no implementation dispatch below `READY`.

## Dependencies
None.

## Implementation Steps
1. Blind-audit current Board/product mode logic, data root, `CONTEXT_GLOBAL`, export paths, agent CLI permissions, connector runtime, Remotion local capability, setup/packaging, health, current Presentation UI and release verification.
2. Only after the blind audit, compare findings with this handoff.
3. Check current Drive queues for overlapping Presentation/Settings/storage/security tasks and identify hot files.
4. Confirm or revise documentation-level conclusions in `docs/05-documentation-levels.md`.
5. Resolve existing valid Workspace Task Types. Do not invent one.
6. Confirm the IGuard external-input boundary; other work must remain dispatchable if IGuard is not yet specified.
7. Confirm dependency/license risks that affect distributed V1, especially wake-word/model/runtime licenses.
8. Produce readiness state and initial parallel dispatch set.
9. Before every later Slice dispatch, do a targeted freshness check of its contracts/files and update the handoff if stale.

## Files Likely Touched
Task handoff only.

## Architecture Constraints
- preserve the locked AppData/`CONTEXT_GLOBAL`/export-only decisions unless new evidence creates a true conflict requiring Human escalation;
- keep one canonical product capability policy and one canonical data-root policy;
- do not solve V1 by deleting shared Assistant/Meeting code.

## Automated Validation
Repository/docs/queue reconciliation only. Do not run the full test suite in Slice 00.

## Acceptance Criteria
- exactly one readiness state recorded;
- current-main SHA and relevant overlapping tasks recorded;
- Task Types are valid existing values;
- initial dispatch set and critical path are explicit;
- no known contradiction between this task and current canonical contracts remains hidden.

## Documentation Updates
Update this handoff when current evidence invalidates planning assumptions.

## Handoff Notes
Global QA doctrine applies: every implemented Slice gets `qa-verification`; code adds `code-review`; runtime/UI adds `runtime-validation`; agent/runtime capability changes add `agent-trace-analysis` with real traces. Regressions caused by a Slice are blocking and cannot be parked in `Issues/`.
