# Slice 10 - Recording controls in the existing floating left toolbar

## Goal

Add screenshot, audio recording and screen recording controls to the existing floating left Control Center tool rail while preserving Bare Hands interaction-tool semantics and scene layout safety.

## Context

On the inspected baseline, `control_center_barehands_hud.js` owns `#barehandsPalette`, a fixed vertical icon strip at the left edge under the Bare Hands lifecycle control. The current buttons are 44x44 pointer/pan/select tools derived from `BH.describeTools()` and behave like mutually-exclusive interaction choices. `control_center_scene_page.js` includes `#barehandsPalette` in `CONTROL_SELECTOR` safe-area measurement. The right `.dock` is not the requested surface.

## Required skill/routing

Load `/caveman`, `/coding-guideline`, and `/impeccable` before implementation. Use a Claude Work Agent for frontend implementation when current routing supports it.

## Scope

### In scope

- Refactor/generalize the existing left rail enough to host a separate **Capture** group while keeping the Bare Hands group intact.
- Screenshot action control.
- Audio recording toggle/control with authoritative active/stopping/error/elapsed feedback.
- Screen recording toggle/control with independent authoritative state.
- Support audio + screen recording concurrently.
- Capture controls remain available when Bare Hands is off/unavailable.
- Preserve left-rail visual language: icon geometry, focus, non-color active/error cues, compact footprint, responsive positioning.
- Update safe-area selector/geometry and browser tests for the taller/generalized rail.
- Expose useful tooltip/ARIA descriptions and keyboard operation.
- Do not use a giant central recording banner as the primary control surface. A compact supplemental active-status treatment is acceptable only if it reflects the same backend state.

### Out of scope

Adding capture actions to `BH.TOOL`, moving them to the right dock, changing capture backend semantics.

## Architecture constraints

- Bare Hands radio state and capture channel state are separate models.
- Frontend polls/subscribes to backend truth; a failed start must visibly revert rather than leaving a fake active button.
- Screenshot is momentary; audio/screen are stateful channels.
- UI remains usable at narrow viewport widths and with reduced motion/high contrast.

## Automated validation

`qa-verification` + `code-review` + `runtime-validation`. Browser/JS tests must prove left placement, group separation, concurrent channel state, Bare Hands-off availability, status-loss behavior, keyboard/ARIA semantics and scene safe-area avoidance.

## Human validation

After automated QA, visually inspect the rail in the real Control Center and exercise the three controls.

## Acceptance criteria

The user can start/stop audio and screen recording and take a screenshot from the existing floating left toolbar; states are clear without color alone; controls do not contaminate `BH.TOOL`; scene content does not overlap the enlarged rail; right dock remains unrelated.
