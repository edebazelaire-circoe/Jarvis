# Slice 14 - Jarvis Presenter and Locked AV Sequences

## Goal
Allow Jarvis to present a prepared artifact itself, including exact locked voice/animation sequences where required.

## Context
Reports and some presentations should be deliverable by Jarvis without the user speaking.

## Canonical Concepts
Jarvis presenter, speech item, visual cue, locked sequence, deterministic schedule, emergency stop.

## Scope
### In Scope
- Score-driven Jarvis speech.
- Visual/motion actions synchronized with speech/score events.
- Locked deterministic sequences.
- Explicit silence periods.
- Pause/stop and safe recovery.

### Out of Scope
- New TTS provider architecture.

## Dependencies
- `12-playback-runtime`
- `10-presentation-score-cues`

## Implementation Steps
1. Reuse current speech-request/TTS path.
2. Schedule visual events from score semantics, not hard-coded sleeps scattered in UI.
3. Implement locked-sequence ownership and completion state.
4. Preserve emergency/explicit stop behavior.
5. Add deterministic fake-clock/fake-TTS tests.

## Files Likely Touched
Presentation player, speech adapter, scheduling/events, tests.

## Architecture Constraints
Do not let Presentation own a second TTS stack.

## Automated Validation
Fake-clock sequence tests, speech/visual ordering, silence, stop/recovery, TTS failure behavior.

## Acceptance Criteria
Jarvis can present a scripted section with reproducible voice/visual choreography.

## Documentation Updates
Jarvis-presenter role and locked-sequence contract.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; runtime and agent trace validation required.
