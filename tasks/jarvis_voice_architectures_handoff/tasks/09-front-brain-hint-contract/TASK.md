# Task 09 — Define Front Brain sidecar hint contract

## Goal

Specify a narrow advisory interface for a fast analysis model without making it a serial dependency in the critical audio path.

## Context

Front Brain mode pairs a realtime conversational/reflex model with a fast analysis model such as Luna. The sidecar should help intent, urgency, routing, and speech gating while remaining optional and discardable.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Define input snapshots/deltas for sidecar analysis.
- Define typed hints such as intent hypothesis, addressed-to-JARVIS confidence, urgency, likely backend need, suggested gate action, conversation phase, and confidence.
- Define revision/version and expiry semantics.
- Define failure/timeout behavior: conversation continues without the hint.
- Provide fake sidecar implementation.

### Out of Scope
- Calling Luna.
- Giving the sidecar authority to execute irreversible tasks or speak directly.

## Dependencies
- Tasks 02 config, 04 state, 06 gate.

## Implementation Steps
- 1. Choose minimal hint fields justified by current design.
- 2. Version hints against transcript/state revision.
- 3. Define late-hint rejection.
- 4. Define coalescing boundary for partial transcript updates.
- 5. Implement fake sidecar for deterministic controller tests.

## Files Likely Touched
- New front-brain sidecar contract/types
- Fake sidecar
- Contract tests

## Architecture Constraints
- Hints are advisory, not authoritative.
- No sidecar response may block a direct low-latency answer.
- Partial transcript hints cannot trigger irreversible external actions.

## Testing Requirements
- Late hint for old transcript revision is ignored.
- Sidecar timeout leaves Simple-like conversation behavior intact.
- Conflicting hint cannot overwrite committed spoken/user state.

## Acceptance Criteria
- Controller can consume or ignore hints without knowing the model/provider behind them.

## Documentation Updates
- Document hint schema and authority boundaries in architecture spec.

## Handoff Notes

Keep this contract small; avoid reproducing the entire conversation state in a second model-owned structure.
