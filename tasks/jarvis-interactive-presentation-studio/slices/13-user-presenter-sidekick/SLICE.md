# Slice 13 - User Presenter Sidekick and Armed Cue Following

## Goal
Let Jarvis follow the user's live presentation speech and trigger only pre-authorized score actions at the right moments.

## Context
This is the key bridge between existing non-authoritative ambient speech and the new score-driven presentation behavior.

## Canonical Concepts
Armed cue, ambient transcript tail, cue match, reversible bound action, explicit-address preemption.

## Scope
### In Scope
- Arm only the finite current/near-next cue set.
- Match ambient transcript to semantic/phrase cues.
- Fire the bound reversible action by cue ID.
- Conservative ambiguity handling.
- Explicit address preempts cue automation immediately.
- Pause/re-arm around detours and resume.

### Out of Scope
- General ambient commands.
- Editing from ambient speech.

## Dependencies
- `12-playback-runtime`
- `10-presentation-score-cues`
- Existing PRESENTATION ambient lane/working set.

## Implementation Steps
1. Add cue-matcher input adapter over the fresh ambient transcript path.
2. Make the output only `cue_satisfied(cue_id, evidence refs)`; never raw tool intent.
3. Gate actions through the active score and playback state.
4. Add ambiguity/duplicate/debounce handling.
5. Integrate explicit-address priority/preemption.

## Files Likely Touched
Presentation runtime, ambient consumer integration, cue matcher, tests.

## Architecture Constraints
Ambient words cannot authorize an action not already present in the armed score.

## Automated Validation
Adversarial transcript tests, unarmed-cue refusal, ambiguous-cue no-fire, explicit-address preemption, repeat/debounce, trace privacy.

## Acceptance Criteria
Jarvis can follow a real presenter without converting room speech into arbitrary commands.

## Documentation Updates
Document armed-cue authority exception and failure behavior.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; requires `agent-trace-analysis` and runtime validation.
