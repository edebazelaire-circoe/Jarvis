# Slice 10 — Add diagnostics, replay traces and benchmark metrics

## Goal

Make Bare Hands tunable and comparable with reproducible traces rather than subjective threshold changes.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- deterministic Bare Hands trace/replay
- measurable input-device quality
- complete V1 pipeline and migration
- current Jarvis Control Center/Constellation contracts

## Scope

### In Scope

- Add opt-in diagnostic trace schema containing timestamps, landmarks, handedness/confidence, raw/filtered points, velocity/stillness, gesture/pinch states, target candidates, captures and outcomes.
- Add deterministic replay of a trace through alternate filter, threshold and target-resolver parameters without needing to repeat physical gestures.
- Add comparable metrics: click target success, pointer error percentiles, stationary jitter, false primary/secondary pinch and gesture events, interaction latency, hand-loss recovery, drag continuity and two-hand resize stability.
- Add parameter sweep/comparison support appropriate for development.
- Keep raw video entirely optional and separately consented; trace-only mode must be fully useful.
- Allow diagnostics to be disabled with no normal-runtime dependency.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

03, 04, 05, 06, 08

## Implementation Steps

1. Load /caveman and /coding-guideline; for browser/frontend work also load /impeccable and use Claude routing when supported.
2. Freshness-check the relevant runtime/component contracts before editing.
3. Add deterministic automated validation and preserve privacy/offline/security constraints.
4. Run the required QA composition before Human validation.
5. Record durable results/corrections in LOG.md.

## Files Likely Touched

- Bare Hands recorder/trace schema
- replay/benchmark utilities
- test fixtures
- optional diagnostic UI/CLI surface discovered by Slice 00
- privacy/documentation files

## Architecture Constraints

- Raw video is never required for normal operation.
- Diagnostic recording is explicit/opt-in.
- Measured outcomes must distinguish facts from heuristic scores.
- Current-Slice regressions are blocking.

## Automated Validation

Golden traces replay deterministically; changing a parameter produces comparable metric output; corrupted/old schemas fail or migrate clearly; diagnostics-disabled path has no recorder side effects; privacy tests ensure raw video is absent unless explicitly enabled.

## Acceptance Criteria

A developer can run the same recorded landmark session against at least two configurations and compare objective metrics. Normal Bare Hands operation does not require recording or video retention.

## Documentation Updates

Document trace schema/version, replay workflow, metric definitions, privacy defaults and how to add future tracker backends to the same benchmark.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review and runtime-validation as applicable. Regressions introduced by this Slice are blocking.
