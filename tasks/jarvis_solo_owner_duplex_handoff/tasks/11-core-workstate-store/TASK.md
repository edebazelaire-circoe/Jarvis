# Task 11 — Add Core WorkStateStore and provider observation ingress

## Goal

Make Core authoritative for normalized detailed work state and feed current provider task observations into it.

## Context

The provider-specific tracker should remain an adapter/observer, not the source consumed directly by every UI/brain feature.

## Scope
### In Scope
- Core service/store for normalized work snapshots;
- observation ingress port;
- revision/event publication;
- adapter from Claude `AgentTaskTracker` state/events;
- idempotency/out-of-order handling;
- bounded completed item retention.

### Out of Scope
- inventing Codex subtask formats not verified in code.
- UI migration.

## Dependencies

Task 10.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Add Core-owned store/service with in-memory implementation first.
2. Define observation ingestion semantics and revision updates.
3. Adapt `AgentTaskTracker` output/events into `WorkObservation` at the edge.
4. Publish normalized Core events.
5. Handle process stop/interruption consistently.
6. Add persistence only if existing architecture requires it now; otherwise document restart semantics separately.

## Files Likely Touched

- new `jarvis/core/work_state.py` or equivalent
- `jarvis/ports/v2.py`
- `jarvis/runtime/agent_tasks.py`
- `jarvis/runtime/claude_local.py`
- composition root (`app.py`/services)
- tests

## Architecture Constraints

- Tracker -> Core, never Core -> tracker polling as authority.
- Core event bus contains normalized public state only.
- Provider raw traces stay runtime-side.

## Testing Requirements

- duplicate observation idempotency;
- out-of-order progress cannot reopen completed task;
- process death transitions;
- bounded retention;
- event revision monotonicity;
- runtime tracker exception cannot kill brain/voice.

## Acceptance Criteria

- Core can return the detailed active/completed work snapshot independently of Control Center runtime state.
- Claude tracker is one input adapter, not a shared global authority.

## Documentation Updates

Document state lifetime and restart behavior.

## Handoff Notes

If existing `JobService` can own some of this without duplication, refactor the plan and document the choice before implementation.
