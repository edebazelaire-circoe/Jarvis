# Slice 07 - Dynamic Presentation Edit Inspector

## Goal
Provide an optional human edit surface generated from the same semantic controls Jarvis uses.

## Context
Voice is central, but the user wants useful sliders/selectors/controls for tactile iteration such as colors, gradients, spacing and motion timing.

## Canonical Concepts
Control inspector, selected scene/element, preview, commit, voice/GUI parity.

## Scope
### In Scope
- Contextual inspector for selected scene/control group.
- Dynamic widgets from control metadata.
- Preview and commit through the semantic edit API.
- Current value, reset/default and error display.
- Hide inspector entirely in clean presentation playback.

### Out of Scope
- General-purpose visual page builder.

## Dependencies
- `05-semantic-edit-api`
- `06-scene-hot-reload`

## Implementation Steps
1. Build inspector from discovered control schema.
2. Wire every mutation through semantic edit operations.
3. Support continuous preview for safe controls and discrete commit where needed.
4. Ensure keyboard/focus behavior does not conflict with presentation navigation.

## Files Likely Touched
Control Center/presentation authoring frontend and tests.

## Architecture Constraints
No inspector-only persistence path.

## Automated Validation
Component tests, control rendering from schema, edit parity, keyboard/focus tests, runtime preview tests.

## Acceptance Criteria
A user can visually tune declared parameters and obtain the exact same durable result as an equivalent Jarvis edit command.

## Documentation Updates
Document edit mode UI and control rendering rules.

## Handoff Notes
Frontend Slice: `/caveman`, `/coding-guideline`, `/impeccable`, Claude when supported.
