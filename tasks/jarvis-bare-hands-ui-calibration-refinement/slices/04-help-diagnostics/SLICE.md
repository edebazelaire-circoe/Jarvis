# Slice 04 — Build visual Help/Gestures and Diagnostics quick surfaces

## Goal

Replace dense Settings text with concise visual help and make the existing diagnostic recorder directly reachable from the Bare Hands quick menu.

## Context

The current Settings surface includes long gesture/diagnostic explanations. The user wants a small pop-up/window with spacing, icons and hand-position illustrations, while Diagnostics should remain an existing capability with better access.

## Canonical Concepts

- canonical lifecycle/gesture/pinch contracts
- bound versus recognized-but-unbound gestures
- existing diagnostic recorder/replay APIs and privacy behavior
- Control Center small pop-up/card visual language

## Scope

### In Scope

- Build the final `Help / Gestures` pop-up/card opened by Slice 02's quick menu.
- Present OFF/SLEEP/ACTIVE meaning, C wake, primary thumb-index pinch, secondary thumb-middle pinch, and current visual-feedback conventions as applicable.
- Use small simple hand diagrams/icons and generous spacing.
- Only describe actions that current contracts actually bind; recognized-but-unbound gestures must not be advertised as commands.
- Give Diagnostics a compact direct surface/entry that exposes the existing recorder controls/status without forcing the user through Experimental settings.
- Preserve existing diagnostic privacy/retention behavior exactly.

### Out of Scope

- New gesture recognition/actions.
- New diagnostic metrics/recording formats.
- Calibration visuals.

## Dependencies

02

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check gesture/pinch bindings and diagnostic APIs.
3. Build the help data model from canonical truth where practical.
4. Implement schematic SVG/CSS hand illustrations reusable by calibration if appropriate.
5. Implement/route the diagnostics quick surface to existing record/start/stop/status behavior.
6. Add accessibility/focus/escape handling and tests.

## Files Likely Touched

- `jarvis/runtime/control_center_barehands.js`
- `jarvis/runtime/control_center.html`
- possibly a reusable Bare Hands visual-help module
- diagnostic/help browser tests

## Architecture Constraints

- Help cannot drift into a second gesture contract.
- Diagnostics must not change what is recorded or retained.
- Visual hand illustrations are presentation-only and never persisted.

## Automated Validation

- Help opens from quick menu and closes cleanly.
- Bound actions are represented accurately.
- Unbound recognizers are not presented as active commands.
- Diagnostics start/stop/status calls match existing recorder behavior.
- No image/video retention policy changes.
- Keyboard/focus/escape paths work.

## Acceptance Criteria

- Gesture help is readable at a glance and no longer a wall of settings text.
- Diagnostics is easy to reach without changing its semantics.

## Documentation Updates

Update Help/Gestures and Diagnostics access documentation.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required.
