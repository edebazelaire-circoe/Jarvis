# Slice 03 — Add negative examples and canonical pointing-intent gating

## Goal

Measure what is not a click and stop drawing a pointer for ordinary hand motion.

## Context

This Slice belongs to the successor adaptive-calibration task. The prior UI refinement is already merged; work from current `main`, never from the historical task branch.

## Canonical Concepts

Bare Hands canonical contracts; current `docs/barehands-contracts.md`; current implementation and tests; current Jarvis runtime contracts

## Scope

### In Scope

- Calibration exercise: natural hand motion/aiming without clicking.
- Record false press, false secondary press, unintended wake and unintended target acquisition events.
- Define canonical pointing-intent signal separate from tracked-hand and lifecycle state.
- In SLEEP show wake cursor/progress only after credible pointing/C/pre-pinch intent.
- In ACTIVE hide pointer when no pointing intent is present, while keeping internal tracking available.
- Expose intent evidence to calibration telemetry.

### Out of Scope

- Tuning target assistance.
- Changing MediaPipe model.
- Continuous learning.

## Dependencies

01, 02

## Implementation Steps

1. Audit current token rendering and wake detector.
2. Define pure pointing-intent score/state.
3. Gate overlay rendering, not tracking.
4. Add negative-example collection.
5. Test cleanup, state transitions, low-quality hands and normal gestures.

## Files Likely Touched

- `control_center_barehands.js`
- contracts/calibration/tests
- docs

## Architecture Constraints

Never make the pointer the source of interaction truth. Hiding display must not disable internal tracking or captured interactions.

## Automated Validation

Tracked non-pointing hands render no cursor; C/pre-pinch intent renders wake feedback; false wake/click counts are measurable and reproducible.

## Acceptance Criteria

Ordinary hand movements no longer clutter the screen or masquerade as aiming.

## Documentation Updates

Update `docs/barehands-contracts.md` and relevant operational/user documentation for every changed canonical concept. Update this task LOG with durable execution decisions and evidence references.

## Handoff Notes

Baseline `qa-verification` is mandatory. Add `code-review` for code changes and `runtime-validation` for user-visible/runtime changes. Agent/runtime/control-plane changes additionally require `agent-trace-analysis` with real trace evidence. Coding work requires `/caveman` and `/coding-guideline`; frontend/browser work also requires `/impeccable` and Claude routing when supported.
