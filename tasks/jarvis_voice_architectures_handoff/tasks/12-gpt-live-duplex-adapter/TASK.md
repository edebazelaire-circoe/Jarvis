# Task 12 — Implement GPT-Live 1 Duplex adapter with client delegation

## Goal

Add the principal Duplex frontend using GPT-Live while retaining JARVIS ownership of backend tasks, permissions, and durable conversation state.

## Context

GPT-Live client delegation matches the desired split: Live manages spoken conversation; JARVIS dispatches backend work and chooses what task results/context to send back.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Implement GPT-Live session adapter behind `VoiceFrontend`.
- Use client delegation, not managed delegation, as the primary architecture.
- Map input/output transcript deltas and final state into canonical events.
- Map delegation requests into JARVIS backend tasks.
- Map quiet context/results to Live using supported thinking/context semantics and user-facing results using commentary/spoken semantics where appropriate.
- Map instructions/behavior updates through adapter.
- Record actual output transcript into spoken ledger.
- Emit usage/session lifecycle diagnostics.

### Out of Scope
- Live session watchdog/UI controls; Task 13/16.
- Replacing JARVIS backend with OpenAI managed backend.

## Dependencies
- Tasks 03-04 contracts/state and Task 11 non-blocking backend.

## Implementation Steps
- 1. Confirm current GPT-Live API event names/requirements from official docs at implementation time.
- 2. Implement session creation/configuration with client delegation.
- 3. Translate Live input/output transcript events into canonical state.
- 4. Translate delegation event into task request with bounded context projection.
- 5. Feed backend progress/result back as quiet or speakable context according to controller decision.
- 6. Implement adapter stop and error-state reporting.
- 7. Add provider-fake integration tests before live API smoke test.

## Files Likely Touched
- New GPT-Live adapter/client module
- Voice composition root
- Live config/prompt layer
- Provider fakes
- Integration tests

## Architecture Constraints
- JARVIS retains permissions, records, task state, and durable context.
- Provider event types stay inside adapter.
- Do not assume an append ACK means content was actually spoken; spoken ledger follows output transcript/events.
- All model/API specifics must be rechecked against current official docs during implementation.

## Testing Requirements
- Delegation request creates JARVIS backend task without blocking Live session.
- Backend result can be injected quietly without forced speech.
- Speakable result is correlated and actual output transcript is recorded.
- Adapter stop closes session and reports terminal state.
- Live API smoke test behind explicit environment flag/credentials.

## Acceptance Criteria
- Duplex mode completes an end-to-end conversation with backend delegation and no direct backend ownership of the microphone.

## Documentation Updates
- Update docs/10-openai-api-notes.md with exact API version/events used and any drift from design notes.

## Handoff Notes

GPT-Live is the principal expected Duplex implementation, but the contract must allow future duplex providers.

### Verified contract constraints (2026-09-12)

Read `docs/verified-provider-contracts.md` before implementation. Live primary WebSocket has no authoritative transcript-final event or exact output text/audio alignment. Preserve revisable transcript intervals and explicit unknown playback evidence. `session.delegation.created` carries metadata only; do not invent task text or treat its timestamp as consent. Use existing application action validation. Do not reuse Realtime event/commit schemas.

Read `docs/live-delegation-authority-plan.md` and Decision22. Delegation must use Task11's restricted advisory job/provenance path when source input is provisional. Flush/apply relevant received canonical observations before capturing the Core source projection; keep the socket reader non-blocking and pending triggers bounded. A first-session delegation with admitted deltas must support useful analysis without a fake user commit. Action proposals do not call CoreToolRouter merely because a model requested them: that router assumes upstream explicit-request admission. Wire an actual application admission boundary for supported actions and preserve existing confirmation requirements; otherwise retain proposals as pending. Preserve original delegation identity for same-session result injection, never reuse it in a replacement session. “Final state” and “spoken ledger” above do not authorize invented provider transcript finals or generated-text-as-heard claims.
