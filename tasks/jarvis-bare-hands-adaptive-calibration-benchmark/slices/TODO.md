# Implementation TODO

## Orchestration rule

Execute Slice 00 first. No implementation Slice may begin until Slice 00 declares `READY` and resolves a valid Workspace Task Type for that Slice.

## Slices

- [x] 00 — Project Manager readiness and reconciliation gate
  - Path: `slices/00-project-manager/SLICE.md`
  - Depends on: none
- [x] 01 — Define adaptive calibration, telemetry, feedback, trial and benchmark contracts
  - Path: `slices/01-contracts-session-model/SLICE.md`
  - Depends on: 00
- [x] 02 — Segment pinch episodes and measure press/release latency
  - Path: `slices/02-pinch-episodes-latency/SLICE.md`
  - Depends on: 01
- [x] 03 — Add negative examples and canonical pointing-intent gating
  - Path: `slices/03-negative-examples-pointing-intent/SLICE.md`
  - Depends on: 01, 02
- [x] 04 — Implement bounded trial profiles and expanded tunable parameters
  - Path: `slices/04-trial-profile-tuning/SLICE.md`
  - Depends on: 01, 02, 03
- [ ] 05 — Extend target preselection and calibrate assistance
  - Path: `slices/05-target-preselection-assistance/SLICE.md`
  - Depends on: 01, 03, 04
- [ ] 06 — Add the scoped calibration agent and full voice feedback loop
  - Path: `slices/06-calibration-agent-voice/SLICE.md`
  - Depends on: 01, 02, 03, 04, 05
- [ ] 07 — Rebuild calibration exercises around measure-review-adjust-retest
  - Path: `slices/07-calibration-exercises-review-loop/SLICE.md`
  - Depends on: 02, 03, 04, 05, 06
- [ ] 08 — Build deterministic Bare Hands Test benchmark and multidimensional scoring
  - Path: `slices/08-benchmark-engine-scoring/SLICE.md`
  - Depends on: 01, 02, 03, 05
- [ ] 09 — Add Test UI, mini-game presentation and before/after comparison
  - Path: `slices/09-test-ui-before-after/SLICE.md`
  - Depends on: 07, 08
- [ ] 10 — Close interaction gaps, migrate schemas, integrate and validate end-to-end
  - Path: `slices/10-interaction-polish-migration-integration/SLICE.md`
  - Depends on: 03, 04, 05, 06, 07, 08, 09

## Historical baseline

- `jarvis-bare-hands-ui-calibration-refinement` is already implemented and merged at `e684a46824a116216a2bee327de068bfcac37464`. Do not dispatch its old Slices again.
- This successor starts from current `main` after Slice 00 verifies the head.

## Planning blocker

`task_type` remains null in planning metadata because the Workspace Task Type vocabulary is not exposed to this task creator. Slice 00 must resolve real existing values before dispatch.
