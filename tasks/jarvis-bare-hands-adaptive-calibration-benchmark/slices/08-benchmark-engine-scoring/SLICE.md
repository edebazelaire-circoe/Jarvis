# Slice 08 — Build deterministic Bare Hands Test benchmark and multidimensional scoring

## Goal

Measure current interaction quality without changing calibration state.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Seeded/equivalent exercise plan: target acquisition, no-click tracking, nearby targets, drag/drop into target, moving target, chained interactions.
- Metrics: acquisition time, missed/wrong/false clicks, release latency/reliability, premature drops, reacquisition count, placement error, target ambiguity, pointer stability/reactivity.
- Dimension score definitions with raw metrics.
- Weak-dimension-sensitive global aggregation, justified and tested.
- Benchmark result object suitable for before/after comparison.
- Explicit proof that benchmark never mutates settings/profile.

### Out of Scope

- Agent-driven tuning.
- User skill ranking.
- Open-ended arcade scoring.

## Dependencies

01, 02, 03, 05

## Implementation Steps

1. Define exercise generator/seed.
2. Implement pure scoring from results.
3. Build runner atop real interaction engine/adapters.
4. Add deterministic fixtures and sensitivity tests.
5. Document interpretation/limitations.

## Files Likely Touched

- new Bare Hands benchmark module(s)
- contracts/tests
- calibration/scene adapters only where reused

## Architecture Constraints

The same profile + same seed + same synthetic trace yields the same score. Raw metrics remain available; global score is not the only result.

## Automated Validation

Score changes in the expected direction when targeted defects are introduced; catastrophic weak dimension cannot be hidden by strong unrelated dimensions.

## Acceptance Criteria

Test mode provides a credible objective baseline for before/after calibration.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
