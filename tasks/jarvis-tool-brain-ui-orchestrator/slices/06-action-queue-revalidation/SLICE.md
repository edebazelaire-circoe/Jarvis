# Slice 06 — Action Queue, Scheduling and Revalidation

## Goal

Implement Tool Brain's mutable UI action queue with speech/event scheduling, precondition validation, cancellation/replacement and immediate replan on stale state.

## Context

A major value of Tool Brain is timing. It must be able to prepare actions for future speech while remaining safe when the user interrupts or the UI changes.

## Canonical Concepts

Queued action, trigger, priority, precondition, invalidation, supersession, replan.

## Scope

### In Scope

- Queue data model and runtime ownership.
- Immediate, event-based and speech-chunk/progress triggers.
- Optional absolute-delay trigger only when no semantic trigger fits.
- Add/cancel/replace/reprioritize/reschedule operations.
- Snapshot/revision-based preconditions.
- Executor handoff and typed results.
- Stale/invalid action rejection.
- `action_invalidated` -> fresh perception -> immediate replan loop.
- Aggressive cancellation of obsolete response-bound actions on interruption.

### Out of Scope

- New domain mutation APIs.
- Cross-restart persistence unless Slice 00 proves a canonical requirement.

## Dependencies

- `05-tool-brain-runtime`
- `02-ui-tool-choice-contract`

## Implementation Steps

1. Define queue/action/trigger schemas.
2. Implement deterministic ordering and supersession.
3. Integrate speech-progress and general runtime-event triggers.
4. Revalidate tool args/preconditions immediately before execution.
5. Emit typed completion/failure/invalidation events.
6. Wake Tool Brain immediately on invalidation with fresh state.
7. Add interruption and Board-authority invalidation rules.
8. Add deterministic replay tests.

## Files Likely Touched

New queue/scheduler/executor coordination modules plus event schemas and tests.

## Architecture Constraints

The queue stores intentions to mutate, not authoritative UI state. Runtime owners always revalidate before mutation.

## Automated Validation

- Correct action ordering and cancellation.
- Speech-bound action fires only on matching live response/chunk.
- Interrupted response actions never execute afterward.
- Stale revision rejects and replans.
- Invalid fabricated ID never reaches a mutation owner.

## Acceptance Criteria

- Tool Brain can plan ahead without causing stale delayed UI actions.
- Failure/invalidation is visible and recoverable rather than silent.

## Documentation Updates

Promote queue, trigger and invalidation contracts to Level 3.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. Runtime behavior requires real `agent-trace-analysis` and `runtime-validation`.
