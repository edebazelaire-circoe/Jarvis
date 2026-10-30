# Slice Execution Plan

## Gate

- [x] `00-project-manager` - mandatory readiness audit. No implementation Slice runs before `READY`.

## Initial parallel-ready set after READY

- [x] `01-atomic-layout-and-undo-contract`
- [x] `02-mouse-resize-selection-input`
- [x] `03-multi-object-viewer-shell`
- [x] `04-agent-viewer-projection`

These are intentionally parallel-safe at the planning level. Slice 00 must re-check real HEAD/file ownership before dispatch.

## Convergence

- [ ] `05-scene-integration-organize-viewer`
  - reopened 2026-10-30: observed native-dialog/fullscreen request coordination defect F2; existing-owner correction and independent runtime revalidation required.
  - hard depends on `02` because it owns the final scene-page integration after the input refactor;
  - soft requires outputs from `01`, `03`, `04` with documented fixture/fallback seams so those branches do not serialize unnecessarily;
  - all soft seams must be reconciled before Slice 05 is approved.

- [ ] `06-final-integration-e2e-qa`
  - hard depends on `01`, `03`, `04`, `05`;
  - only this Slice runs the complete repository unit/integration/E2E suite.

## Critical path

`00 -> 02 -> 05 -> 06`

Branches `01`, `03` and `04` converge before final approval without being placed on the hot-file critical path unless Slice 00 discovers a real dependency.





