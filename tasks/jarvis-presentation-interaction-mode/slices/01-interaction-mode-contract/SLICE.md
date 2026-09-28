# Slice 01 - Define interaction-mode and output-disposition contracts

## Goal
Create canonical domain vocabulary separating Jarvis product interaction mode from voice architecture and authorization mode, and define Presentation output/speech semantics before runtime wiring.

## Context
The repository already has `VoiceArchitectureId.SIMPLE` and `conversation_mode` for open-room/solo-owner authorization. Reusing either for product mode would create semantic collisions.

## Canonical Concepts
- Interaction mode: product behavior policy.
- Voice architecture: implementation architecture.
- Conversation authorization: who may control voice/actions.
- Output disposition: whether a completed turn manifests by voice and/or visual output.

## Scope
### In Scope
- Add typed `InteractionMode`; labels SIMPLE, PRESENTATION, REUNION.
- Prefer internal `assistant`, `presentation`, `meeting` unless live audit finds a stronger convention.
- Simple default; deterministic invalid handling.
- Meeting known/reserved but `implemented=false`.
- Typed `silent`, `visual_only`, `voice_only`, `visual_and_voice`.
- Presentation matrix for ambient observation, visual command, knowledge question, explicit speak, confirmations/errors, spontaneous fact-check attention.
- Contract/conformance tests.
### Out of Scope
- Persistence/API/UI wiring.
- Audio capture.
- Meeting behavior.
- Prompt implementation details.

## Dependencies
Slice 00.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`.
2. Add provider-neutral domain types.
3. Encode capability metadata so Meeting can be displayed but not activated as implemented behavior.
4. Define default/fallback rules.
5. Define output-disposition invariants enforced by runtime, not prompt alone.
6. Add tests proving no collision with voice architecture or authorization mode.
7. Document matrix in canonical docs.

## Files Likely Touched
`jarvis/domain/interaction_mode.py` or equivalent; brain/output domain contracts; architecture docs; unit tests.

## Architecture Constraints
- Core/domain imports no provider/UI implementation.
- Simple behavior remains default.
- Ambient Presentation observations never authorize actions or spontaneous speech.

## Automated Validation
Focused domain tests plus existing voice architecture/config contract tests.

## Acceptance Criteria
Interaction mode is first-class and independent; Simple default deterministic; Meeting known but not implemented; output disposition runtime-consumable; policy matrix pinned by tests.

## Documentation Updates
Raise interaction mode and response disposition to documentation Level 2+ in canonical architecture docs.

## Handoff Notes
Do not wire UI directly to string literals; later slices consume this contract.
