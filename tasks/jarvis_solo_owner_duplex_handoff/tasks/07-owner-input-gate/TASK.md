# Task 07 — Gate active input and useful activity by owner identity

## Goal

Apply Solo Owner identity filtering even when JARVIS is not speaking, so background people never become brain turns or keep the active session alive.

## Context

Current capture gate naturally opens when JARVIS is silent. Transcript filters/addressing reduce noise but do not provide owner authorization.

## Scope
### In Scope
- In Solo Owner, non-owner speech is dropped before addressing/brain routing.
- Non-owner speech does not refresh `UsefulActivityTracker`.
- Owner speech can still become `addressed` or `uncertain` through existing addressing logic.
- Wake/background lifecycle remains separate.
- Maintain local listening needed for owner detection.

### Out of Scope
- future permissions for guest speakers.
- wake-word engine replacement.

## Dependencies

Task 06.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Identify the single earliest safe point where owner authorization can gate conversational PCM/segments.
2. Ensure filtered non-owner audio does not create provider response/reflex/brain turn.
3. Ensure activity callbacks only fire for verified owner/addressed useful speech as intended.
4. Keep `uncertain` semantics for verified owner speech outside/inside engagement windows.
5. Add explicit trace for dropped non-owner input.

## Files Likely Touched

- `jarvis/audio/duplex.py`
- `jarvis/runtime/realtime_audio.py`
- `jarvis/runtime/voice_v2.py`
- activity/addressing tests

## Architecture Constraints

- Identity gate before intent/addressing in Solo Owner.
- Do not infer owner from transcript text.
- Non-owner speech must not become Core intent.

## Testing Requirements

- continuous background conversation during active session does not reset timeout;
- owner follow-up does reset useful activity appropriately;
- non-owner transcript never submitted to brain;
- owner `uncertain` still follows existing brain ownership rule;
- mute/background transitions unchanged.

## Acceptance Criteria

- Solo Owner behaves as “only my voice constitutes a user turn”.
- Other speakers can talk indefinitely without controlling session state.

## Documentation Updates

Update Solo Owner semantics and troubleshooting.

## Handoff Notes

This task is the full realization of the user's “professional solo” behavior.
