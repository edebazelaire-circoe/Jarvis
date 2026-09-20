# Implementation TODO

## Orchestration rule

Execute Slice 00 first. No implementation Slice may begin until Slice 00 declares `READY` and resolves a valid Workspace Task Type for that Slice.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline`. Every frontend/browser Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## Slices

- [ ] 00 — Project Manager readiness and reconciliation gate
  - Path: `slices/00-project-manager/SLICE.md`
  - Depends on: none
- [ ] 01 — Add first-class Bare Hands HUD lifecycle control
  - Path: `slices/01-main-hud-control/SLICE.md`
  - Depends on: 00
- [ ] 02 — Add right-click quick actions and clean Bare Hands Settings IA
  - Path: `slices/02-settings-context-entrypoints/SLICE.md`
  - Depends on: 01
- [ ] 03 — Move existing tools into a fixed left palette
  - Path: `slices/03-tool-palette/SLICE.md`
  - Depends on: 01, 02
- [ ] 04 — Build visual Help/Gestures and Diagnostics quick surfaces
  - Path: `slices/04-help-diagnostics/SLICE.md`
  - Depends on: 02
- [ ] 05 — Replace the calibration modal with the full-screen exercise shell
  - Path: `slices/05-calibration-shell/SLICE.md`
  - Depends on: 02
- [ ] 06 — Add calibration intro/arming phases and redesign steps 1–5
  - Path: `slices/06-calibration-steps/SLICE.md`
  - Depends on: 05
- [ ] 07 — Add real window move/resize practice and retire separate Tutorial
  - Path: `slices/07-window-stage-tutorial-merge/SLICE.md`
  - Depends on: 03, 05, 06
- [ ] 08 — Integrate, migrate, validate and document the refined Bare Hands UX
  - Path: `slices/08-integration-rollout/SLICE.md`
  - Depends on: 01, 02, 03, 04, 05, 06, 07

## Dependency graph

`00 -> 01 -> 02`

`01,02 -> 03`

`02 -> 04`

`02 -> 05 -> 06`

`03,05,06 -> 07`

`01,02,03,04,05,06,07 -> 08`

## Planning blocker

`task_type` is intentionally null in planning metadata because the Workspace Task Type vocabulary is not exposed here. Slice 00 must resolve valid existing Task Types before dispatch; do not fabricate labels.
