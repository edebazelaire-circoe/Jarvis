# Slice 08 — Implement calibration overlay, profile derivation and persistence

## Goal

Create a short explicit calibration flow that measurably adapts Bare Hands thresholds/mapping to the user while remaining safe, optional and privacy-preserving.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture/contracts
- calibration profile versus tutorial state
- derived parameters only by default
- existing Jarvis voice-command and UI architecture discovered by Slice 00

## Scope

### In Scope

- Reusable full-screen dark/blurred overlay shell for calibration.
- Calibration steps: neutral/show hands, C pose, repeated thumb-index pinch, repeated thumb-middle pinch, known screen-target aim/pinch, short drag, and small bimanual resize.
- Derive internal per-hand values where useful while exposing one simple profile.
- Derive primary/secondary press/release and hysteresis, jitter/stillness, click-vs-drag motion threshold, spatial correction/mapping and quality/confidence metrics.
- Allow comfortable non-fully-closed pinch positives, but refuse thresholds that make neutral and pinch states insufficiently separable.
- Support partial success: failed functions retain standard defaults while successful functions save.
- Explicit apply/save and reset-to-default behavior.
- No continuous auto-learning during normal usage.
- Persist only derived parameters and quality metrics by default; no raw frames/video.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- continuous self-learning
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

03, 04, 05, 06, 07

## Implementation Steps

1. Load /caveman and /coding-guideline; for browser/frontend work also load /impeccable and use Claude routing when supported.
2. Freshness-check current settings, overlay and voice-command integration points.
3. Implement explicit state/data separation and deterministic tests before webcam/manual checks.
4. Preserve privacy defaults, camera cleanup and offline operation.
5. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- calibration/profile modules
- Control Center overlay/UI
- Bare Hands settings persistence/API
- target/filter/gesture integration
- unit/browser tests

## Architecture Constraints

- Calibration may modify only the explicit profile after user-run calibration.
- Tutorial must never mutate calibration.
- No raw images/video are retained by default.
- Current repository APIs must be discovered rather than invented.

## Automated Validation

Fixture-based derivation tests; profile schema/version/migration tests; spatial-fit tests; separability/fallback tests; partial-success tests; privacy assertion that default profile contains no raw landmarks/images/video; runtime test that profile applies only after successful explicit calibration.

## Acceptance Criteria

Calibration can complete quickly, produces a stable profile, handles per-function failure gracefully, changes only intended tunables, and can be reset. Default storage is derived data only.

### Implementation notes (Slice 08, as shipped)

- The seven stages ship as scoped: `neutral`, `c_pose`, `pinch_primary`,
  `pinch_secondary`, `aim`, `drag`, `resize`. **`c_pose` verifies rather than
  calibrates**, and that is deliberate: the wake band is read by the SLEEP
  watcher, before a hand has any identity or handedness, so a per-hand
  threshold would have no reader (decision 28 keeps one visible profile). The
  stage answers the question the user actually asks — "does my C wake it?" —
  and its answer lives in the per-stage report.
- **Profile schema raised to version 2**, with v1 migrated rather than refused.
  The new `travelSlopNorm` settles the pixels-vs-palms residue Slice 04 left
  open; `stages` carries decision 31's per-stage report.
- **Three new dangerous pairs** refused at construction
  (`stageTimeoutMs <= stageHoldMs`, `pressAt >= releaseAt`,
  `travelSlopMin >= travelSlopMax`) — the ninth, tenth and eleventh on this
  task.
- Persistence lives on its own key and routes (`/api/barehands/profile`),
  deliberately not widened into `/api/barehands`: a profile is a measurement,
  not a choice, and it versions on its own clock.

## Documentation Updates

Document calibration algorithm, profile schema/version, stored fields, privacy policy, fallback behavior and reset semantics.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review and runtime-validation as applicable. Regressions introduced by this Slice are blocking.
