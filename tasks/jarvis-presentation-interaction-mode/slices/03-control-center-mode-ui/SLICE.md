# Slice 03 — Control Center interaction-mode UI

## Goal

Expose the canonical interaction mode clearly in the existing Control Center without inventing a second settings surface.

## Context

The user needs to deliberately choose Presentation mode. Existing Control Center conventions and UI/MCP parity should be preserved.

## Canonical Concepts

Control Center, effective interaction mode, UI/MCP parity, SIMPLE, PRESENTATION, REUNION reserved state.

## Scope

### In Scope

- Reuse or complete the existing mode control.
- Show current effective mode and mode-change feedback.
- Keep SIMPLE and PRESENTATION clearly selectable.
- If REUNION already exists in product UI, keep it visibly reserved/disabled/coming rather than inventing behavior.
- Ensure Jarvis can perform the same supported mode switch through the canonical MCP/settings surface if parity rules require it.

### Out of Scope

- Reworking the entire Control Center.
- Meeting/reunion behavior.

## Dependencies

- `02-interaction-mode-contract`

## Implementation Steps

1. Inspect current mode control implementation.
2. Extend existing visual language and accessibility semantics.
3. Bind directly to canonical mode state/actions.
4. Add UI state/error/loading behavior.
5. Add UI/MCP parity tests where applicable.

## Files Likely Touched

Existing Control Center HTML/JS/CSS, settings/MCP facade, frontend/runtime tests.

## Architecture Constraints

Extend existing controls; do not create a parallel settings panel or direct frontend-owned truth.

## Automated Validation

Frontend unit tests, integration tests against canonical mode state, MCP parity checks, visual/runtime regression pass.

## Acceptance Criteria

The user can enter/leave PRESENTATION from the existing Control Center and the UI reflects authoritative runtime state.

## Documentation Updates

Update interaction-mode Control Center docs/help text.

## Handoff Notes

Frontend coding Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when host routing supports it.


## Slice 00 contract (binding)

Scope in:
- Verify the existing selector (`runtime/control_center_interaction_mode.js`) against `/api/status.interaction_mode` (`control_center.py:2092`). It must stay non-optimistic, refuse a reserved REUNION, and offer no second settings surface.
- Render the live Presentation status from `/api/status.presentation` (published by Slice 10, P7) **inside the existing selector host**. Show:
  - a short state line or tooltip: listening / deaf (transcription unavailable) / refused (continuous voice required) / entry failed / inactive;
  - the failure code in `title`.
  - The block is null when Voice is offline.
- Load `/impeccable`; use a Claude agent.

Scope out: new settings, routes or panels; Board-kind suggestions; changing the mode semantics.

Files: `jarvis/runtime/control_center_interaction_mode.js`, `tests/unit/test_interaction_mode_hud_js.py`, `tests/unit/_interaction_mode_browser.mjs`, `tests/unit/test_interaction_mode_hud_browser.py`, `docs/interaction-mode.md` (HUD section).

Acceptance:
- JS (node): `test_presentation_status_line_per_state` (5 states + null). `test_status_never_optimistic_after_click` stays green.
- `test_no_new_settings_surface`: static check that no new `/api/` route and no new settings key appear in the diff.
- Browser (real CC over CDP, as 2026-09 Slice 03):
  - switching SIMPLE↔PRESENTATION reflects within one poll;
  - a forced `.voice_presentation` `{state:"deaf"}` shows the deaf line;
  - keyboard and screen-reader labels intact;
  - screenshot evidence.
- Existing `test_interaction_mode_hud_*` green.

QA tier: ui. Passes: qa-verification + code-review + runtime-validation (browser). Human check: HV-PRESENTATION-MODE-UI-01 (supersedes HV-PRES-MODE-01), only after machine QA is green.

Not yours: publishing the status (10); the cue (10).

Depends on: 02, 10.

Documentation: HUD section of `docs/interaction-mode.md` Level 3.
