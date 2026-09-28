# Slice 02 — Segment pinch episodes and measure press/release latency

## Goal

Replace frame-population bias with per-gesture measurements and expose timing evidence.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Segment primary and secondary intentional pinches into open/closing/minimum/opening/open episodes.
- Compute per-episode minima, baselines, duration, opening/closing velocity, travel, quality, press latency and release latency.
- Preserve current channel separation/world veto semantics unless evidence requires a later trial parameter.
- Derive personalized thresholds from episode aggregates rather than raw all-frame quantiles.
- Keep strict fallback/refusal semantics when episodes are insufficient/non-separable.

### Out of Scope

- Voice agent.
- Target assistance.
- Benchmark UI.

## Dependencies

01

## Implementation Steps

1. Freshness-check current deriveHysteresis and detector.
2. Add pure episode segmenter.
3. Integrate calibration collection without changing ordinary runtime first.
4. Add deterministic traces for fast/slow clicks and multiple FPS.
5. Replace/extend profile derivation only after parity tests.

## Files Likely Touched

- `control_center_barehands_calibration.js`
- `control_center_barehands.js` pure helpers if needed
- profile/contracts/tests

## Architecture Constraints

Per-frame tracking remains deterministic. Episode boundaries must not depend on the LLM. Existing press < release invariants remain enforced.

## Automated Validation

Fast 50–100 ms pinch and slow pinch both calibrate sensibly; repeated episodes dominate equally rather than by frame count; latency metrics match synthetic ground truth.

## Acceptance Criteria

A rapid-click user no longer needs exaggerated held pinches to produce stable calibration evidence.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
