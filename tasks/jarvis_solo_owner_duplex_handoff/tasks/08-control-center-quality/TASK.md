# Task 08 — Expose Solo Owner quality/degraded settings in Control Center

## Goal

Make owner-verification status and quality-critical controls observable without turning UI into the source of truth.

## Context

The project already exposes VAD/AEC/noise/ack settings in `voice_stack.py` and Control Center.

## Scope
### In Scope
- conversation mode;
- verifier mode/engine/profile status;
- owner threshold/evidence duration if useful for R&D;
- owner buffer duration;
- AEC availability/degraded status;
- current effective values/origin;
- warnings when Solo Owner cannot enforce identity.

### Out of Scope
- embedding/profile data display.
- complex biometric management UI.

## Dependencies

Tasks 01–07.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Follow existing registry-driven settings architecture.
2. Read runtime/Core effective state; do not create a second hidden config path.
3. Expose degraded warnings and shadow/enforce state.
4. Keep advanced tuning fields clearly labelled R&D where appropriate.
5. Add endpoint/UI validation tests.

## Files Likely Touched

- `jarvis/runtime/voice_stack.py`
- `jarvis/runtime/control_center.py`
- `jarvis/runtime/control_center.html`
- settings tests

## Architecture Constraints

- UI projects state; it does not own audio identity decisions.
- No private biometric material in HTML/API payloads.

## Testing Requirements

- settings round-trip;
- incompatible/missing profile warning;
- shadow/enforce display;
- regression of existing VAD/AEC fields.

## Acceptance Criteria

- Operator can tell whether Solo Owner is truly enforced or degraded.
- Effective engine/profile status is visible without exposing sensitive data.

## Documentation Updates

OPERATIONS screenshots/text if project practice uses them.

## Handoff Notes

Keep the UI thin; diagnostic depth belongs in runtime events/logs.
