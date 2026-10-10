# Slice 12 - Presentation Playback Runtime State Machine

## Goal
Implement the runtime that knows exactly where the presentation is and can navigate, pause, detour and resume.

## Context
Playback must support Jarvis presentation, user sidekick and rehearsal without duplicating the generic Presentation interaction mode.

## Canonical Concepts
Playback session, active scene, active score item, cue set, auxiliary display stack, pause/detour/resume.

## Scope
### In Scope
- Load an artifact/variant into fullscreen or authoring preview.
- Track active scene and score position.
- Next/back/jump/focus/reveal operations.
- Pause and resume.
- Temporary auxiliary prefab/resource display and return.
- Runtime query for "where are we / what comes next?".

### Out of Scope
- Ambient cue matching.
- Jarvis TTS score execution.

## Dependencies
- `03-fullscreen-borderless-surface`
- `10-presentation-score-cues`
- `02-presentation-artifact-contract`

## Implementation Steps
1. Implement explicit state machine.
2. Bind score position to logical scene state.
3. Add reversible navigation/action execution.
4. Add auxiliary resource stack and deterministic recovery.
5. Emit canonical runtime events.

## Files Likely Touched
Presentation runtime/player service, scene adapter, tests.

## Architecture Constraints
Presentation runtime owns presentation-specific progression, not generic scene lifecycle.

## Automated Validation
Navigation/state tests, detour/resume, backtracking, invalid target, reload/recovery fixtures.

## Acceptance Criteria
Playback state is always inspectable and can resume predictably after a detour.

## Documentation Updates
Playback state contract and event vocabulary.

## Handoff Notes
Runtime/frontend: `/caveman`, `/coding-guideline`, `/impeccable` for user-visible player work, Claude when supported.
