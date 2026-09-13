# Task 08 — Add freshness-aware semantic speech scheduler

## Goal

Replace strict FIFO speech playback with cancellable semantic chunks whose relevance is re-evaluated as the conversation changes.

## Context

A response like `take your time` was ready quickly but played 35.9 seconds later. Voice output cannot be treated as a text-chat queue.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Define speech chunk object with source turn/task, priority, freshness, status, and optional expiry/supersession key.
- Schedule chunks by conversational relevance rather than creation order alone.
- Cancel unstarted stale chunks on newer user input when policy says they are superseded.
- Allow important asynchronous task results to remain available without forcing immediate interruption.
- Replan between chunks and after user barge-in.

### Out of Scope
- Advanced linguistic chunk generation quality beyond minimum semantic boundaries.
- Long-term notification policy.

## Dependencies
- Tasks 04 state and 06 reflex gate.

## Implementation Steps
- 1. Define typed speech candidate/chunk state.
- 2. Implement scheduler with cancellation and supersession.
- 3. Make user-turn arrival trigger freshness evaluation.
- 4. Keep backend results as available state until chosen for speech.
- 5. Integrate actual spoken/interrupt completion back into state.
- 6. Add deterministic fake-clock tests for the 29-36 second stale queue cases.

## Files Likely Touched
- Speech scheduler/queue module
- Conversation state extensions
- Voice controller
- Scheduler tests

## Architecture Constraints
- A queued text is not a promise to speak it.
- Once speech has begun, interruption policy owns cancellation; do not rewrite already-heard content.
- Never lose a completed backend result solely because its immediate speech chunk became stale.

## Testing Requirements
- `take your time` queued then new user turn -> never spoken later.
- Older task result remains retrievable but does not interrupt unrelated conversation unless priority warrants it.
- Interrupted chunk records spoken state and pending tail is cancelled/replanned.

## Acceptance Criteria
- Replay no longer emits stale conversational filler tens of seconds late.
- Queue state is inspectable and correlated to turns/tasks.

## Documentation Updates
- Update architecture and testing docs with scheduler semantics.

## Handoff Notes

This is one of the highest-value fixes independent of which frontend model is selected.

Read `docs/08-scheduler-review-plan.md` before implementation. Inventory found that the existing scheduler already prioritizes speech; the missing behavior is source-aware freshness, including old results arriving after a new intent and selection-to-first-write races. Preserve that scheduler and reuse Task06 admission and Task07 device evidence.

Ordinary conversational backend summaries currently live only in `BrainWorkingState`; unlike `Job.result`, unspoken summaries are lost on Core restart. This slice must retain completed ordinary outcomes through a minimal Core-owned repository projection before presentation can discard/defer their speech candidates. Store outcomes separately from heard history; do not manufacture assistant turns or jobs. Task11 retains ownership of the independent executor and generic job ingress.

Use an explicit originating intent/dependency reference, never equality against the global brain or canonical state revision. Unknown or stale provenance defers speech while keeping the result available. Exercise a real multi-chunk production path, exact text/provenance preservation, bounded queue/tombstones and independent first-write invalidation. Existing tests that equate a true result with mandatory immediate speech must be updated to the new policy while preserving result retention and interruption evidence.
