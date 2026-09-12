# Task 05 — Make owner confirmation authoritative for Solo Owner barge-in

## Goal

In `solo_owner`, stop JARVIS only after local owner confirmation; arbitrary near-end speech must not duck or cut playback.

## Context

Current main uses two-step barge-in: near-end -> duck to 30% -> provider `speech_started` -> cut. That is good for open-room behavior but rejected for Solo Pro.

## Scope
### In Scope
- Preserve existing current behavior for non-Solo modes.
- In Solo Owner, remove raw near-end audible duck/cut authority.
- On local owner confirmation, immediately call local `stop_output()` and mark interruption.
- Provider cancel/truncate remains best-effort follow-up.
- Provider `speech_started` may be correlated/advisory but is not required for local stop.

### Out of Scope
- Silent-JARVIS input gating (Task 07).
- final provider benchmark.

## Dependencies

Task 04.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Isolate current barge-in trigger policy from output-stop mechanism.
2. Add mode-aware trigger: open/current behavior unchanged; Solo Owner requires owner-confirmed signal.
3. Reuse existing exact playback cursor, `_received_outputs`, interrupted output accounting, cancel/truncate degradation.
4. Make provider speech-start order irrelevant to local stop after owner confirmation.
5. Ensure non-owner near-end events do not alter gain in Solo Owner.

## Files Likely Touched

- `jarvis/runtime/realtime_audio.py`
- `jarvis/audio/duplex.py`
- bridge tests

## Architecture Constraints

- Do not rewrite playback concurrency architecture.
- Local physical stop precedes provider calls.
- Interruption never cancels Core work.

## Testing Requirements

- non-owner near-end does not duck/cut in Solo Owner;
- owner confirmed stops output even if provider event is delayed/absent;
- provider event before/after confirmation does not double-cut;
- cancel/truncate failure does not kill voice;
- open/current mode regression unchanged.

## Acceptance Criteria

- Solo Owner barge-in authorization is local owner identity.
- Network/provider event is not on critical stop path.

## Documentation Updates

Update voice-duplex behavior docs and rollback description.

## Handoff Notes

Do not delete the current path globally; preserve it for non-Solo behavior until product decisions change.
