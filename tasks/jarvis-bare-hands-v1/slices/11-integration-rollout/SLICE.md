# Slice 11 — Integrate, migrate, validate end-to-end and document rollout

## Goal

Assemble the complete Bare Hands V1 pipeline, remove obsolete assumptions safely, prove the locked interaction model on a standard webcam, and leave a clear future tracker extension point.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- deterministic Bare Hands trace/replay
- measurable input-device quality
- complete V1 pipeline and migration
- current Jarvis Control Center/Constellation contracts

## Scope

### In Scope

- Integrate HandTracker -> HandTrackManager -> filtering/features -> gesture/pinch -> TargetResolver -> InteractionEngine -> Jarvis components.
- Safely migrate the legacy barehands_test_mode setting/profile behavior.
- Isolate/remove obsolete immediate-click and hard-coded single-pointer assumptions once compatibility is proven.
- Ensure Control Center/Constellation object hooks cover the agreed V1 interactions.
- Verify Tools, Settings, Calibration, Tutorial and voice entry points as one product surface.
- Run full automated suite plus browser/runtime/offline/security checks.
- Preserve vendored MediaPipe/no-cloud operation and camera/resource cleanup.
- Reconfirm native clean-room separation from pinned AGPL upstream Barehands.
- Document the tracker adapter boundary for a future optional Pro backend without implementing specialized hardware.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

02, 03, 04, 05, 06, 07, 08, 09, 10

## Implementation Steps

1. Load /caveman and /coding-guideline; for browser/frontend work also load /impeccable and use Claude routing when supported.
2. Freshness-check the relevant runtime/component contracts before editing.
3. Add deterministic automated validation and preserve privacy/offline/security constraints.
4. Run the required QA composition before Human validation.
5. Record durable results/corrections in LOG.md.

## Files Likely Touched

- all Bare Hands modules
- Control Center/Constellation integration
- settings/profile migration
- voice action integration
- tests
- user/developer documentation

## Architecture Constraints

- Raw video is never required for normal operation.
- Diagnostic recording is explicit/opt-in.
- Measured outcomes must distinguish facts from heuristic scores.
- Current-Slice regressions are blocking.

## Automated Validation

Full repository test suite plus all new Bare Hands tests; browser runtime-validation; offline asset/network validation; camera cleanup/error-path validation; migration test from legacy settings; code-review; final real-webcam human validation only after machine QA is clear.

## Acceptance Criteria

Bare Hands V1 is usable inside Jarvis with a standard webcam and implements all locked interaction/calibration/tutorial rules. No permanent cursor is required, right click is distinct, bimanual geometry is stable, settings/tools are exposed, diagnostics exist, and the tracker remains replaceable.

## Documentation Updates

Publish final architecture, user guide, calibration/tutorial guide, diagnostics/replay guide, migration notes and future Pro tracker adapter notes.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review and runtime-validation as applicable. Regressions introduced by this Slice are blocking.
