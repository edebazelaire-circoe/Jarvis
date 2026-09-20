# Slice 06 — Add calibration intro/arming phases and redesign steps 1–5

## Goal

Make calibration readable before it becomes interactive, and give the first five exercises clear schematic demonstrations with feedback that matches the actual gesture being measured.

## Context

The current calibration starts its stage timer as soon as the step appears, causing the user to lose time while reading. The visual instructions also need a much clearer hand demonstration, especially C pose and target pinch.

## Canonical Concepts

- current `STEPS` and `createCalibration` state machine
- `stageTimeoutMs`, `stageHoldMs`, watchdog rules and partial-fallback semantics
- current primary/secondary pinch and C-pose measurements
- target/spatial profile derivation

## Scope

### In Scope

- Add explicit step phases `INTRO`, `ARMED`, `RUNNING`, `RESULT` (or equivalent names with the same semantics).
- Add a minimum reading/demo delay before a step can start.
- Do not consume active measurement timeout during INTRO.
- For rest/C/pinch steps, remain ARMED indefinitely while the user is inactive; transition to RUNNING only on meaningful relevant hand engagement.
- Step 1 visual: simple open schematic hand, natural rest/stability.
- Step 2 visual: thumb + index clearly form a C; avoid a generic curled whole-hand interpretation.
- Step 3 visual: thumb-index pinch closing/reopening, with repetition feedback.
- Step 4 visual: same grammar but thumb-middle, clearly distinct from Step 3.
- Step 5 visual: spatial targets across the usable screen and a clear thumb-index pinch-on-target demonstration; no pointing-finger-only metaphor.
- Reveal Step 5 targets after intro delay and start/validate on actual target engagement.
- Use subtle blue progress/feedback and brief green success confirmation.
- Keep current partial success/fallback profile rules.

### Out of Scope

- Window manipulation step (Slice 07).
- New gesture recognition algorithms.
- Changing target resolver semantics.

## Dependencies

05

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check current stage state machine and timer/watchdog tests.
3. Separate reading/arming time from active measurement time with explicit state transitions.
4. Define deterministic “meaningful engagement” predicates from existing measurements/events; do not invent new gesture models.
5. Build simple schematic hand demonstrations for steps 1–4.
6. Build target exercise presentation for step 5 using current target/spatial calibration data path.
7. Add success/error/partial-result feedback and preserve skip/cancel behavior.
8. Extend deterministic unit/browser tests around timers, idle behavior and exercise transition.

## Files Likely Touched

- `jarvis/runtime/control_center_barehands_calibration.js`
- `jarvis/runtime/control_center_barehands.js` measurement seam only if needed for arming signals
- calibration/profile tests

## Architecture Constraints

- Reading time is not measurement time.
- Idle users are not punished by a hidden countdown.
- Engagement detection must use existing tracking/gesture/pinch signals.
- The demonstration hand is not input and is never persisted.
- Target calibration continues to derive spatial behavior from the canonical profile path.

## Automated Validation

- INTRO delay is deterministic and active timeout remains untouched during it.
- ARMED step can wait with no hand indefinitely without failing.
- Valid engagement starts RUNNING.
- Invalid incidental movement does not prematurely complete a step.
- Primary and secondary pinch visuals/logic remain distinct.
- Target step shows targets only after intro and records actual primary pinch engagement.
- Existing profile derivation tests still pass.

## Acceptance Criteria

- User has time to read every instruction before measurement starts.
- C, primary pinch and secondary pinch are visually unambiguous.
- Target exercise clearly teaches/uses pinch-to-click.
- No calibration quality or privacy regression is introduced.

## Documentation Updates

Document the calibration phase state machine and exercise-start semantics.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required.
