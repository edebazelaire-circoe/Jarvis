# Slice 09 — Add Test UI, mini-game presentation and before/after comparison

## Goal

Expose the benchmark as a short, understandable, game-like test separate from calibration.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Add `Tester` next to/near the existing Calibration entry without reviving Tutorial.
- Full-screen short benchmark experience using controlled exercises.
- Show interaction-quality dimensions and concise explanation of weak areas.
- Store/compare benchmark summaries sufficiently to show before vs after within policy.
- Offer navigation to relevant calibration competency when a weak dimension is detected.
- Use equivalent randomized layouts on retest.

### Out of Scope

- Automatic recalibration.
- Playground/arcade product.
- Calling the score “user precision/skill”.

## Dependencies

07, 08

## Implementation Steps

1. Reuse calibration visual language where useful but keep state machines distinct.
2. Add Test entry/action routing.
3. Render exercises and report.
4. Add comparison view.
5. Add accessibility and reduced-motion handling.

## Files Likely Touched

- HUD/context menu / Bare Hands UI modules
- new benchmark UI
- tests/docs

## Architecture Constraints

Benchmark is read-only with respect to calibration/settings. Test and Calibration entry points are visibly distinct.

## Automated Validation

User can run a short benchmark, see dimension results, recalibrate, rerun an equivalent benchmark and compare improvements/regressions.

## Acceptance Criteria

A tester can finally verify whether calibration actually helped.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
