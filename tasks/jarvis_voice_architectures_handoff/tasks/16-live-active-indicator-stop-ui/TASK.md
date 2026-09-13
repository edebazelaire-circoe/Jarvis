# Task 16 — Add prominent GPT-Live active indicator, timer, Stop control, and cost awareness

## Goal

Make active billable Duplex sessions unmistakable and always stoppable from the user interface.

## Context

The user explicitly requires a strong marker, elapsed-time counter, and stop control so a background Live process cannot keep billing unnoticed.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Global/high-visibility `GPT-Live active` state while runtime is starting/active/stopping/uncertain.
- Elapsed active/session timer driven by runtime lifecycle truth.
- Manual Stop action available wherever active state is visible.
- Show idle auto-close status/countdown when meaningful.
- Show session usage/cost estimate only from configurable/current pricing metadata or provider usage; label estimates.
- Surface close failure/reap-required state and retry/action instead of falsely hiding it.

### Out of Scope
- Implementing lifecycle state machine itself (Task 13).
- Hardcoding permanent pricing into UI.

## Dependencies
- Task 13 lifecycle manager; Task 14 Settings shell.

## Implementation Steps
- 1. Design minimal persistent indicator location in current Control Center UI.
- 2. Bind indicator directly to lifecycle state service.
- 3. Implement elapsed timer from authoritative start/active timestamps.
- 4. Wire Stop to idempotent runtime stop operation and show pending/failed state.
- 5. Add optional estimated cost display using pricing/config source.
- 6. Add accessibility and UI state tests.

## Files Likely Touched
- Control Center/global status UI
- Settings/voice session UI
- Lifecycle view-model binding
- UI tests

## Architecture Constraints
- UI is never the owner of the Live session; runtime owns truth.
- A failed close cannot render as OFF.
- Stop should not be buried only inside Settings.

## Testing Requirements
- Active session visibly shows marker/timer/Stop.
- Stop transitions through stopping and eventually off only after runtime confirms.
- Injected close failure shows warning/retry state.
- Mode switch cannot leave indicator stale.

## Acceptance Criteria
- A user cannot reasonably mistake an active or uncertain GPT-Live session for an inactive one, and can request stop immediately.

## Documentation Updates
- Update cost-safety doc with UI/runtime responsibility split.

## Handoff Notes

Visual design should follow existing project conventions; function and state truth take priority over decoration.
