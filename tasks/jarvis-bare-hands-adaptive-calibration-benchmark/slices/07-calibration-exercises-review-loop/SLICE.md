# Slice 07 — Rebuild calibration exercises around measure-review-adjust-retest

## Goal

Turn the existing full-screen stages into interactive sessions that stop for interpretation and user validation.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Preserve current shell/INTRO/ARMED/RUNNING foundation.
- After RUNNING, enter a review/result state that never auto-advances.
- Exercise set covers tracking/stability, pointing/wake intent, primary pinch, negative movement, targeting, click-vs-drag/drag-drop, release/hold reliability and secondary pinch.
- Real scene-style stars/windows for manipulation where appropriate.
- Display measured outcomes and agent explanation without dumping raw parameter jargon.
- Actions: retry, adjust, accept stage, skip with explicit reason, quit.
- Voice and UI drive the same session state.

### Out of Scope

- Benchmark scoring.
- Open-ended game mode.

## Dependencies

02, 03, 04, 05, 06

## Implementation Steps

1. Reconcile current public 7-screen flow with new competencies.
2. Reuse full-screen shell and real window practice adapter.
3. Add review state and session state transitions.
4. Wire telemetry/agent/trial actions.
5. Add deterministic browser state-machine tests.

## Files Likely Touched

- `control_center_barehands_calibration.js`
- hand art/target/practice adapters as needed
- tests/docs

## Architecture Constraints

A failed stage does not silently advance or persist guessed values. Every displayed metric comes from the session evidence contract.

## Automated Validation

User can repeat/tune one competency until satisfied, then explicitly continue; cancel leaves accepted prior profile intact.

## Acceptance Criteria

Calibration feels like guided diagnosis rather than a fixed wizard.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
