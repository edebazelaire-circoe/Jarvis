# Slice 02 — Add right-click quick actions and clean Bare Hands Settings IA

## Goal

Move frequent Bare Hands actions out of the deep Settings/Experimental path and make Settings configuration-only.

## Context

The user explicitly rejected lifecycle/tool/tutorial usage controls being buried in Settings. The main HUD button from Slice 01 becomes the lifecycle entry. Right-click on that same button becomes the quick-action entry for secondary surfaces.

## Canonical Concepts

- Control Center context-menu component/pattern
- Bare Hands Settings schema and API
- Bare Hands calibration/diagnostics entry functions
- current separate tutorial entry and persisted tutorial fields

## Scope

### In Scope

- Add right-click/context-menu behavior to the main Bare Hands button.
- Menu entries: Settings, Calibration, Help/Gestures, Diagnostics.
- Do not include activation/mode items in the right-click menu.
- Do not include Tutorial.
- Route Settings to the Bare Hands configuration surface.
- Route Calibration to the existing calibration entry point until later Slices replace its shell.
- Route Diagnostics to the current diagnostic/recording surface.
- Provide an initial Help/Gestures route that Slice 04 can refine visually.
- Remove the lifecycle/master activation control from the primary Bare Hands Settings presentation.
- Remove the Tools section from Settings presentation.
- Remove the separate Tutorial section/entry from Settings presentation.
- Keep backend fields as compatibility state where still required; do not delete persistence blindly.

### Out of Scope

- Final Help/Gestures visual card (Slice 04).
- Tool palette implementation (Slice 03).
- Calibration visual redesign (Slice 05+).
- Tutorial command migration/removal (Slice 07).

## Dependencies

01

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Reuse the current Control Center context-menu framework where possible.
3. Add a contextmenu handler/accessibility alternative on the Bare Hands HUD button.
4. Wire Settings/Calibration/Diagnostics through existing APIs rather than duplicating logic.
5. Create a stable Help entry hook for Slice 04.
6. Refactor Settings HTML so persistent configuration remains but lifecycle, Tools and Tutorial usage actions no longer occupy it.
7. Keep schema/backward compatibility intact unless a migration is explicitly required.
8. Add browser/unit tests for routing and absence of removed sections.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_barehands.js`
- `jarvis/runtime/barehands_test_mode.py` only if UI/schema migration requires it
- settings/browser tests

## Architecture Constraints

- One action path per capability: context menu entry calls the same calibration/diagnostic/settings functions used elsewhere.
- Settings remains persistent configuration, not a session command palette.
- Do not remove stored `enabled`/`tool` fields merely because the UI moved; runtime compatibility may still depend on them.

## Automated Validation

- Right-click opens exactly Settings, Calibration, Help/Gestures, Diagnostics.
- Activation and Tutorial are absent from that menu.
- Keyboard-accessible alternative invokes the same menu/actions.
- Settings no longer renders lifecycle master control, Tools section, or Tutorial section.
- Existing saved settings still load/apply without data loss.
- Calibration and Diagnostics entry points still work.

## Acceptance Criteria

- Frequent Bare Hands actions are reachable from the main HUD button.
- Settings reads as configuration rather than an interaction dashboard.
- No backend behavior is silently lost during the UI move.

## Documentation Updates

Update Bare Hands user-facing navigation documentation and settings information architecture.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required.
