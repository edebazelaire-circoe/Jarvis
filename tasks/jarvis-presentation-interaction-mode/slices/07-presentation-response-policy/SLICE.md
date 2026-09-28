# Slice 07 - Enforce Presentation response/speech policy

## Goal
Make silence a first-class successful outcome in Presentation and prevent speaking after every addressed action.

## Context
User rejects filler TTS for visual commands. Genuine knowledge questions may receive useful spoken synthesis with caveats. Enforce this in runtime contracts, not only prompt prose.

## Canonical Concepts
Output disposition; ambient vs addressed Presentation turn; speech scheduling as separate manifestation decision.

## Scope
### In Scope
- Carry interaction mode/turn role into brain context/admission.
- Determine/receive typed response disposition.
- Enforce ambient -> no spontaneous speech; visual command -> silent/visual by default; genuine question/explicit speak -> voice allowed.
- Brain completion with zero SpeechRequest is normal/observable.
- Suppress acknowledgement/backchannel/filler reflexes in Presentation except hearing repair/required clarification.
- Preserve useful error/confirmation safety semantics.
- Update prompts while retaining runtime enforcement.
- Preserve Simple behavior.
### Out of Scope
Fact-check floating UI; ambient speculative execution.

## Dependencies
Slices 01, 02, 06.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Inspect brain result, SpeechRequest/Scheduler, prompt registry/runtime, Front Brain reflexes and Duplex controls.
3. Add smallest typed disposition path across architectures.
4. Default Presentation to silence unless semantics allow speech.
5. Decouple display execution from speech.
6. Disable filler reflexes without breaking hearing repair/clarification.
7. Trace disposition with non-content metadata.
8. Add cross-architecture tests.

## Files Likely Touched
Brain result contracts, `brain_service.py`, `control_center_brain.py`, prompt runtime/registry, `speech_scheduler.py`, Front Brain/Duplex seams, tests.

## Architecture Constraints
Prompt cannot be only enforcement; ambient Presentation never spontaneously speaks in V1; Simple unchanged.

## Automated Validation
Brain/orchestrator, prompt wiring, speech scheduler/outcome, Simple/Front Brain/Duplex composition tests.

## Acceptance Criteria
“Show me X” succeeds with no TTS; genuine question can speak/display; ambient cannot speech-request; no generic filler; Simple remains green.

## Documentation Updates
Document output matrix and enforcement boundary.

## Handoff Notes
Human check `HV-PRES-SPEECH-01` validates perceived behavior.
