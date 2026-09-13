# Task 10 — Implement Luna Front Brain sidecar with speculative transcript analysis

## Goal

Implement the initial fast analysis model for Front Brain mode and use user speaking time to prepare revisable conversational hints.

## Context

The sidecar should analyze transcript deltas while the user is still speaking, but it must not cause a request storm or sit serially between audio and response.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Implement model client/config for GPT-5.6 Luna or the exact fast model verified available in the environment.
- Consume coalesced partial transcript deltas plus bounded conversation state.
- Generate structured hints matching Task 09.
- Debounce/coalesce requests and enforce per-turn request/token budgets.
- Finalize/revise hint on committed transcript.
- Expose prompt and model selection through config registry for later Settings UI.

### Out of Scope
- Making Luna the backend task brain.
- Direct speech generation authority.

## Dependencies
- Task 09 hint contract and Task 02 capability/config registry.

## Implementation Steps
- 1. Implement sidecar adapter with injectable model client for tests.
- 2. Define bounded prompt/context projection.
- 3. Implement delta coalescing/debounce and cancellation of superseded in-flight analysis.
- 4. Parse/validate structured hint output.
- 5. Wire Front Brain mode so Realtime can continue when sidecar is slow/unavailable.
- 6. Emit latency/token/request-count diagnostics.

## Files Likely Touched
- Front Brain sidecar adapter
- Prompt registry/config hooks
- Controller composition
- Tests

## Architecture Constraints
- Parallel/advisory only; never `audio -> Luna -> conversational model` as a mandatory serial chain.
- Bound request frequency and context size.
- Discard stale partial-transcript results.

## Testing Requirements
- Long utterance produces bounded sidecar calls, not one call per delta.
- Final transcript revision supersedes speculative hint.
- Injected slow/failing sidecar does not delay direct voice response path.

## Acceptance Criteria
- Front Brain mode can run Realtime plus Luna and produces traceable hints while preserving graceful fallback.

## Documentation Updates
- Record budget/debounce defaults and prompt layer in docs/06-settings-and-prompts.md or architecture spec.

## Handoff Notes

Task05 keeps canonical provider deltas available at the frontend boundary, but its compatibility facade forwards user observations to Core only after the existing admission gate. Rejected/failed input is discarded from a bounded local item buffer. This preserves existing authority and avoids pinning ignored provisional Core records. Task10 must explicitly wire the speculative pre-admission subscription without making it a serial dependency or an action authority. If provisional records are then retained in Core, give rejected/failed/superseded groups an explicit bounded lifecycle; do not fabricate empty commits. Preserve provider input order separately from admitted application-turn order.

If exact Luna API/model name differs in repository/runtime, use verified availability and update the decision log rather than guessing.

Composition review must distinguish the new architecture from legacy execution flags. Simple is a real conversational frontend; Front Brain adds parallel advisory analysis to that conversational/reflex capability. Do not implement either new mode merely by relabelling `continuous_brain`, whose current rules forward every substantive turn to the strong backend and use verbatim result speech. Preserve existing saved compatibility behavior separately until an explicit new selection. Agree the actual mode/factory/prompt mapping before coding; Task11 owns independent long-work execution and Task17 owns safe replacement of active sessions.
