# Task 10 — Define normalized Core work-state contracts

## Goal

Create provider-neutral domain contracts for detailed task/work observations and snapshots.

## Context

`AgentTaskTracker` has rich runtime task details while `BrainWorkingState` mainly carries IDs/public conversational facts. Core needs a normalized shared representation.

## Scope
### In Scope
- `WorkStatus`/normalized statuses;
- `WorkObservation` and `WorkItem`/`WorkSnapshot` or equivalent;
- explicit provider external ID vs Core `work_id` mapping;
- bounded public fields;
- serialization/event payload contract.

### Out of Scope
- provider ingestion logic;
- brain prompt changes;
- UI changes.

## Dependencies

Task 00. Can run in parallel with voice tasks after orchestration approval.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Inspect existing `Job`, `JobProgress`, `BrainWorkingState`, and event contracts to avoid duplication.
2. Define minimal normalized task fields needed by brain/UI.
3. Keep raw provider trace outside domain state.
4. Define monotonic revision/ordering semantics and terminal-state rules.
5. Add serialization tests.

## Files Likely Touched

- `jarvis/domain/v2.py`
- `jarvis/ports/v2.py`
- event-contract docs/tests

## Architecture Constraints

- Core types are provider-neutral.
- Unknown provider fields are not smuggled in as arbitrary raw JSON.
- External task ID is never silently equated to brain `work_id`.

## Testing Requirements

- type validation;
- wire round-trip;
- invalid status/progress bounds;
- explicit ID mapping tests.

## Acceptance Criteria

- A Claude subtask and a generic job can both be represented without provider-specific fields.
- Contracts are bounded and safe for brain/UI projection.

## Documentation Updates

Update event/data model docs.

## Handoff Notes

Keep this task contract-only to reduce migration risk.
