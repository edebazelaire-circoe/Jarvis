# Task 13 — Migrate task UI projection to Core-owned state

## Goal

Make Control Center display the Core work-state projection while preserving existing UI capability and drill-down where provider traces remain useful.

## Context

UI currently benefits from detailed tracker state. The migration must not discard that UX, but Core must become authoritative for normalized status.

## Scope
### In Scope
- Core endpoint/event for work snapshot;
- Control Center reads normalized Core status/activity/timing;
- compatibility for task trace/drill-down that remains provider-specific;
- clear distinction between Core-normalized state and raw diagnostic trace.

### Out of Scope
- redesigning the whole Control Center UI.

## Dependencies

Tasks 11–12.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Add/read Core projection endpoint or event stream.
2. Switch task status cards/list to Core normalized snapshot.
3. Retain provider-specific trace endpoint only for diagnostic details.
4. Add revision handling so stale UI responses do not rewind state.
5. Verify elapsed-time display is derived from authoritative timestamps + current time, not separately mutated state.

## Files Likely Touched

- Core HTTP/API routes
- `jarvis/runtime/control_center.py`
- `jarvis/runtime/control_center.html`
- task UI tests

## Architecture Constraints

- UI never writes work state.
- Raw provider traces are diagnostic, not authoritative task state.

## Testing Requirements

- same Core snapshot yields same brain/UI facts;
- stale revisions ignored;
- completed/failed task display;
- trace drill-down still works where supported;
- Codex/no-subtask provider degrades cleanly.

## Acceptance Criteria

- UI task state is a projection of Core.
- No duplicate independent state machine remains in the UI path.

## Documentation Updates

Update task visualization/data-source docs.

## Handoff Notes

Keep compatibility endpoint temporarily if removal would make this task too broad; schedule deletion only after parity.
