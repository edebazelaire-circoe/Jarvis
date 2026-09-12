# Task 12 — Feed current work state to the brain and event policy

## Goal

Ensure the strong brain can reason from the same normalized current task state the UI sees and can react to unexpected work-state changes.

## Context

The user explicitly wants JARVIS to know progress, elapsed state, failures, and state transitions—not merely display them.

## Scope
### In Scope
- bounded work snapshot in brain execution context or typed reader;
- include active status/activity/timing summaries without raw traces;
- event-driven hook for meaningful completion/failure/blocker changes;
- separate cognitive wake-up from speech decision;
- preserve existing `BrainWorkingState` public-state invariants.

### Out of Scope
- narrating every progress event;
- exposing chain-of-thought;
- making surface Realtime own task state.

## Dependencies

Task 11.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Decide staged compatibility approach: `BrainContext` aggregate or `WorkStateReader` injected into the Core-side backend adapter.
2. Avoid unbounded arrays in frequently published `BrainWorkingState.to_public_payload()`.
3. Make current work snapshot available on user turns.
4. Add a Core policy/event path for meaningful external work changes to wake the brain when needed.
5. Keep speech request generation behind existing `SpeechScheduler` contracts.

## Files Likely Touched

- `jarvis/core/brain_service.py`
- `jarvis/ports/v2.py`
- brain backend adapter(s)
- domain context types
- tests

## Architecture Constraints

- Brain gets normalized public/operational facts, never UI scraping.
- Work-state event != forced speech.
- Existing work cancellation remains explicit by `work_id`.

## Testing Requirements

- brain turn receives current active work details;
- UI and brain read same revision/snapshot source;
- failure event can trigger policy without automatic speech;
- no regression in cancellation/supersession rules;
- bounded context size.

## Acceptance Criteria

- Brain can answer “where are my tasks?” from Core state without reading Control Center.
- Unexpected normalized failure can be noticed by the cognitive/event policy.

## Documentation Updates

Update brain architecture/event docs.

## Handoff Notes

Do not solve this by injecting the entire `AgentTaskTracker` object into the brain backend.
