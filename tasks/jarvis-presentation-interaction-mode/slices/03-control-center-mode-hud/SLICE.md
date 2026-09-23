# Slice 03 - Add the left-side Jarvis mode selector

## Goal
Add a compact always-visible Jarvis interaction-mode state button on the left side of Control Center, with a three-choice selector matching the truthfulness and interaction quality of the existing Bare Hands lifecycle HUD.

## Context
The user explicitly requested a state button like the existing left-side mode selector. `control_center_barehands_hud.js` is the reference: canonical state projection, no fake optimistic state, keyboard navigation, clear busy/error treatment.

## Canonical Concepts
Interaction-mode state/capabilities; labels SIMPLE / PRESENTATION / REUNION.

## Scope
### In Scope
- Dedicated host near existing left-side controls.
- Pure JS view-model plus browser binding.
- Click opens/closes three-option selector.
- SIMPLE and PRESENTATION selectable.
- REUNION visible future/unavailable with explanation.
- Collapsed button shows effective mode.
- Change calls canonical API and waits for authoritative status/revision.
- Keyboard/focus and responsive/z-index integration.
- Truthful error/busy/refusal states.
### Out of Scope
Meeting behavior; Presentation audio/runtime; duplicate Settings control unless audit says needed.

## Dependencies
Slice 02.

## Implementation Steps
1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Audit left-side z-index/spacing with Bare Hands HUD/palette and visualizer.
3. Add pure projection/interaction functions under Node tests.
4. Bind to status and mode-change API.
5. Add disabled/future Meeting affordance.
6. Ensure refresh/multi-tab follows canonical mode.
7. Add visual/manual validation checklist.

## Files Likely Touched
`control_center.html`; new interaction-mode JS or equivalent; `control_center.py` injection; JS/UI tests.

## Architecture Constraints
No second browser source of truth; do not conflate voice architecture settings.

## Automated Validation
Node logic tests, HTML/injection tests, status API tests, accessibility DOM assertions where available.

## Acceptance Criteria
Left button always shows effective mode; SIMPLE/PRESENTATION switch live; REUNION indicates future; failures leave prior canonical mode selected.

## Documentation Updates
Update canonical Control Center UI docs/help.

## Handoff Notes
Human check `HV-PRES-MODE-01` validates placement and interaction.
