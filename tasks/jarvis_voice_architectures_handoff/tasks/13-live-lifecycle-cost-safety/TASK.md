# Task 13 — Add GPT-Live lifecycle, idle close, and orphan watchdog

## Goal

Make it difficult for a billable GPT-Live session to remain active unnoticed or orphaned.

## Context

Live is time-billed while active. Cost safety is a runtime correctness requirement, not only a UI concern.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Explicit Live lifecycle state machine such as starting/active/stopping/stopped/error/reap-required.
- Idempotent manual stop operation callable from UI and shutdown paths.
- Configurable idle auto-close policy based on validated conversational inactivity, not naive silence only.
- Watchdog/orphan reaper for sessions whose ownership/heartbeat is lost.
- Cleanup on app exit, architecture switch, fatal frontend error, and owner-requested stop.
- Track billable/active duration and close reason.
- Do not falsely display stopped state after uncertain provider close.

### Out of Scope
- Designing the visual Settings/live indicator UI.
- Exact monetary pricing hardcoded into runtime.

## Dependencies
- Task 12 GPT-Live adapter.

## Implementation Steps
- 1. Define lifecycle states and transition table.
- 2. Implement single session owner/lease or equivalent to prevent duplicates.
- 3. Implement heartbeat/watchdog and safe close retry policy.
- 4. Implement idle-close inputs based on no active speech, no imminent conversational continuation, and configured timeout.
- 5. Register process/application shutdown hooks.
- 6. Emit lifecycle and duration metrics.
- 7. Add fault-injection tests for lost socket, close timeout, app shutdown, and mode switch.

## Files Likely Touched
- Live session manager
- Lifecycle state types
- Shutdown hooks
- Metrics/tracing
- Lifecycle tests

## Architecture Constraints
- Manual stop must always be available while state is active/starting/uncertain.
- Never mark OFF solely because UI requested stop.
- Avoid auto-close while user is actively speaking or while the controller expects an immediate continuation.

## Testing Requirements
- Idle session auto-closes after configured policy.
- App exit and architecture switch attempt cleanup.
- Lost close acknowledgement enters explicit uncertain/reap-required state and watchdog retries.
- Repeated stop is safe.
- Duplicate Live owners are rejected.

## Acceptance Criteria
- No tested path leaves a silently active Live session without runtime state, timer, and reaper ownership.

## Documentation Updates
- Update docs/07-live-session-cost-safety.md with exact state machine and timeout semantics.

## Handoff Notes

Pricing may change; measure active seconds and provider usage rather than embedding a permanent cost constant in lifecycle code.

### Verified recovery limitation (2026-09-12)

Read `docs/verified-provider-contracts.md`. Successful primary closure is evidenced by `session.closed`; timeout or socket EOF alone cannot mean OFF. The official Sideband reference permits attachment to an existing session and `session.close`, so recovery may attempt known-ID attachment and close without creating a new primary session. Reattachment after loss of a primary WebSocket and replay of a missed terminal event remain unverified; attachment 404/timeout alone cannot prove OFF. Implement durable ownership, explicit uncertain state, duplicate-start blocking and supported retries. Do not invent status endpoints or certify inaccessible-session cleanup through a fake-only test.
