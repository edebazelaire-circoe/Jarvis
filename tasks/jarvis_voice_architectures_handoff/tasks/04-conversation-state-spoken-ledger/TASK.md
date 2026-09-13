# Task 04 — Add conversation state and actually-spoken ledger

## Goal

Make JARVIS own the authoritative conversation state, especially the distinction between intended speech and what the user actually heard.

## Context

The source session had multiple cases where backend text and spoken output diverged. A provider session cannot be the sole source of truth if architectures need to switch or recover.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Add state for user transcript provisional/final data, intended assistant content, actual spoken content, active speech, active tasks, speech candidates, and recent conversation context.
- Represent transcript and speech lineage with session/turn/task IDs.
- Add snapshot/rehydration data needed for architecture switching.
- Record actual spoken text from frontend events.
- Define committed versus provisional transcript semantics.

### Out of Scope
- Implementing all scheduling policy.
- Provider session switching.
- Long-term semantic memory.

## Dependencies
- Task 03 canonical contracts.

## Implementation Steps
- 1. Define state model and immutable or safely synchronized update operations.
- 2. Define how partial transcript revisions replace provisional hypotheses.
- 3. Record intended output separately from provider-reported actual spoken output.
- 4. Track whether a chunk was queued, started, completed, interrupted, or never spoken.
- 5. Implement serializable snapshot with only necessary recent context and active task references.
- 6. Add deterministic state-transition tests.

## Files Likely Touched
- New conversation state module
- State serializer/snapshot types
- State tests
- docs/state-model.md

## Architecture Constraints
- The spoken ledger is authoritative for what the user heard.
- Provider internal history is not authoritative JARVIS state.
- Partial transcripts cannot commit irreversible task actions.

## Testing Requirements
- Backend response replaced by different spoken output remains distinguishable.
- Interrupted output records only the spoken/confirmed portion available.
- Snapshot round-trip preserves active task references and recent spoken state.

## Acceptance Criteria
- Core can answer what was intended, what was spoken, what user said, and what tasks are active without reading provider session internals.

## Documentation Updates
- Create `docs/state-model.md` and link it from architecture spec.

## Handoff Notes

This state is the foundation for safe switch, replay, stale-response cancellation, and diagnostics.
