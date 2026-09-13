# Task 11 — Make back-brain work non-blocking and result-oriented

## Goal

Ensure long research/tool/sub-agent work never monopolizes the conversational path and returns typed progress/results instead of owning speech.

## Context

The price lookup took 85.7 seconds when done synchronously in the conversational brain. Later sub-agent delegation proved the capability existed.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Create/standardize async task submission from conversation controller to existing backend/agent system.
- Return task IDs immediately.
- Emit typed task progress/result/error events into conversation state.
- Keep speech decision with conversation frontend/controller.
- Add policy/rules that long or uncertain work delegates rather than blocks.
- Preserve active tasks across frontend restarts/switches.

### Out of Scope
- Rebuilding the existing agent/sub-agent framework.
- Forcing every trivial question into a sub-agent.

## Dependencies
- Task 04 state; current backend map from Task 01.

## Implementation Steps
- 1. Wrap existing backend agent entrypoints in a non-blocking task service or adapter.
- 2. Define task lifecycle events and correlation IDs.
- 3. Return immediately after scheduling long work.
- 4. Feed progress/results to Core state, not directly to speech.
- 5. Add cancellation/status operations where existing backend supports them.
- 6. Add a fake 90-second task scenario proving continued conversation.

## Files Likely Touched
- Backend/agent orchestration bridge
- Conversation controller
- Task state/events
- Tests

## Architecture Constraints
- Back brain does not decide when to seize the microphone.
- Do not duplicate the existing task/sub-agent system; adapt it.
- Conversation must remain usable while a backend task is running.

## Testing Requirements
- Simulated 90-second backend task does not block subsequent user turns.
- Completed result appears in state and can be spoken later.
- Task survives voice frontend restart/switch in synthetic test.

## Acceptance Criteria
- Long work is visible and non-blocking, with results correlated to the originating user intent.

## Documentation Updates
- Update architecture spec and implementation strategy with actual backend bridge.

## Handoff Notes

This implements the rule already identified in the source transcript: long research/work should delegate.

### Verified repository gaps (2026-09-12)

Read `docs/nonblocking-backend-integration-notes.md`. Core's `JobService.submit` already returns an independent durable job, but only a memory-maintenance worker is registered and generic job ingress is absent from the local protocol. `AgentTaskTracker` observes CLI subagents; it does not launch them. Calling the shared `/api/agent/ask` from another coroutine still waits on the same CLI conversation lock.

Extend this slice with the minimal typed submit/status/cancel transport and registered independent agent worker needed to reuse JobService. Reuse existing Claude/Codex subprocess wrappers and configured permissions, with explicit per-job process/session ownership; do not use the self-development deployment workflow for ordinary research. Preserve action/confirmation checks. Review concurrent idempotency and cancellation ordering: stop the owned process before awaiting a cancelled Codex ask that waits for process exit. Validate actual production composition, not only an isolated fake gateway.

Read `docs/live-delegation-authority-plan.md` and Decision22. Add explicit source-snapshot provenance/canonical advisory-job references for analysis originating in admitted provisional Live input; existing VoiceTaskRecord still requires a committed source turn. Do not fabricate commits to reach the backend. Separate restricted speculative analysis from already-admitted work. The former requires enforced tool/permission restrictions in the reused wrapper, not just a prompt; preserve normal configured permissions for the latter. If the selected backend cannot enforce analysis scope, report unavailable without silently switching models/providers or launching a permissive child. Verify bounded state, durable deduplication, source-dependency freshness, and production executor configuration.

Task08 review found that historical `BrainEvent.work_id` alone cannot distinguish a reused work generation or a new turn describing an older work result. Core guards old-emitter mutations using durable source epochs and retains ambiguous outcomes without authorizing their presentation. This slice must carry immutable actual Job identity and explicit source/dependency links; do not infer a new job generation from a reusable label or rewrite an outcome's original source on receipt.
