# Task 17 — Implement safe architecture and model switching with state rehydration

## Goal

Allow benchmark/test switching between Simple, Front Brain, and Duplex without losing JARVIS task state or orphaning provider sessions.

## Context

A switch should be a controlled session transition, not an assumption that one provider socket can hot-swap into another model family.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Snapshot authoritative conversation state before switch.
- Stop old frontend and confirm/track uncertain close state.
- Start selected new frontend/config.
- Seed bounded recent spoken/user context and active task summaries.
- Keep backend tasks running independently.
- Record architecture/model/prompt revision transition in trace.
- Support same-architecture model restart when provider requires new session.

### Out of Scope
- Seamless audio continuation in the middle of one phoneme.
- Migrating provider-internal hidden state that JARVIS cannot access.

## Dependencies
- Tasks 04 state, 05/10/12 frontend modes, 13 Live lifecycle.

## Implementation Steps
- 1. Implement switch coordinator with explicit phases and rollback/failure states.
- 2. Snapshot Core conversation/task state.
- 3. Stop old frontend using lifecycle contract.
- 4. Instantiate new frontend from architecture config.
- 5. Project only necessary recent context and active task summaries into new session.
- 6. Resume input/output and emit switch metric.
- 7. Handle partial failure: old stopped/new failed, old close uncertain, new started with degraded context.

## Files Likely Touched
- Voice composition/switch coordinator
- Conversation snapshot/rehydration
- Frontend factory
- Tests

## Architecture Constraints
- Never start a second billable Live session while ownership of an old one is unresolved unless explicit recovery policy permits it.
- Backend task identity survives frontend switch.
- Actual-spoken ledger is not rewritten during rehydration.

## Testing Requirements
- Simple -> Front Brain -> Duplex -> Simple synthetic switch sequence.
- Active backend task completes across switch.
- Old Live close failure prevents silent duplicate billing.
- Prompt/model revision recorded on each new session.

## Acceptance Criteria
- Architecture selection can be changed predictably between sessions/conversation turns with preserved JARVIS-owned state and no orphaned frontend.

## Documentation Updates
- Update architecture spec with switch state machine and context projection rules.

## Handoff Notes

Treat mid-conversation switching as a test/benchmark feature first; polish UX after correctness.
