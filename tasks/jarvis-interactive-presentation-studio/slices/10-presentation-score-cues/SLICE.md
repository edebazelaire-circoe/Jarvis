# Slice 10 - Presentation Score, Tracks, Cues and Timing

## Goal
Implement the mandatory multi-track presentation score and its validation model.

## Context
The score must align speech, visuals, animations and silence. Most flow is cue-driven; exact sequences can be locked.

## Canonical Concepts
PresentationScore, score item, presenter role, cue, soft timing, locked sequence, recovery point.

## Scope
### In Scope
- User speech/intention track.
- Jarvis speech track and explicit silence.
- Visual/motion action references.
- Cue definitions and armability.
- Soft target timing.
- Locked deterministic sequence segments.
- Recovery/resume metadata.
- Validation against scene/action IDs.

### Out of Scope
- Live ambient matching implementation.
- TTS playback implementation.

## Dependencies
- `02-presentation-artifact-contract`
- `01-contract-audit`

## Implementation Steps
1. Define score schema and timing policies.
2. Validate references to logical scenes and reversible visual actions.
3. Explicitly encode who may speak and when.
4. Model locked sequence boundaries and allowed interruption policy.
5. Add deterministic fixtures.

## Files Likely Touched
Presentation score domain/model/validator and tests.

## Architecture Constraints
A score cue may reference a pre-authored action; it may not embed unrestricted tool instructions.

## Automated Validation
Schema/reference tests, silence behavior, locked-sequence determinism, invalid cue/action tests.

## Acceptance Criteria
A full presentation can be represented as an inspectable score without relying on a wall-clock-only video timeline.

## Documentation Updates
Canonical score/cue contract.

## Handoff Notes
Use `/caveman` and `/coding-guideline`.
