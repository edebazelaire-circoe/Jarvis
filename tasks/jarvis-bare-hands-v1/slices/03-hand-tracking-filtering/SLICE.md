# Slice 03 — Stabilize hand identity, filtering and motion feature extraction

## Goal

Make the raw hand stream stable enough for real two-hand capture and precise target intent.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture and contracts
- current native MediaPipe implementation
- stable hand/capture identity
- semantic interaction events rather than raw mouse-only emulation

## Scope

### In Scope

Implement stable frame-to-frame handTrackId association using geometry with handedness as a hint; replace fixed smoothing-only behavior with adaptive filtering (One Euro or equivalent); expose raw/filtered pointer/manipulator positions, velocity/stillness and tracking quality; keep lost-hand grace/cancel semantics deterministic.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

01

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; if this Slice changes browser/frontend UI also load /impeccable and use Claude routing when supported.
2. Freshness-check the exact files/contracts named below before editing.
3. Implement the smallest reusable contract/mechanism that satisfies the Slice.
4. Add or update deterministic automated tests before relying on webcam manual checks.
5. Preserve failure cleanup, offline operation and existing security boundaries.
6. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- Bare Hands pure JS core/modules
- MediaPipe adapter
- Node unit tests

## Architecture Constraints

- MediaPipe-specific data must not leak across the tracker abstraction boundary unnecessarily.
- Per-hand and per-capture state must be explicit and testable.
- User-visible behavior must follow the decision log rather than legacy mouse-only assumptions.
- Unknown current repository component names must be discovered, not invented.

## Automated Validation

Synthetic sequences must cover hand order swaps, temporary loss, crossing paths, left/right ambiguity, stationary jitter and fast motion lag. Benchmark helpers compare raw vs filtered error.

## Acceptance Criteria

Two simultaneously visible hands retain stable IDs across ordinary reorder/jitter; filter reduces stationary jitter without unacceptable motion lag; all features are observable for calibration/diagnostics.

## Documentation Updates

Document filter/track identity contract and tunable parameters.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review for code changes and runtime-validation for user-visible/runtime behavior. Regressions introduced by this Slice are blocking.
