# Slice 02 - Mouse resize and selection input semantics

## Goal

Make scene pointer/keyboard input behave like a conventional desktop surface: 8-way resize, Shift aspect lock, and context-menu behavior that preserves an existing multi-selection.

## Context

Current mouse resize is explicitly bottom-right only, while side-based resize math already exists for Bare Hands. Current context-menu code selects the clicked object unconditionally and therefore collapses multi-selection.

This Slice owns the low-level scene input refactor before the final organization/viewer integration Slice touches the same page controller.

## Canonical Concepts

- shared scene hold/manipulation path
- `resizeBySides()` / bounds
- pointer capture and prefab pointer shield
- selection anchor vs selection replacement
- keyboard `keyIntent()`

## Scope

### In Scope

- Four edge and four corner resize hit regions for resizable representations.
- Correct resize cursors and thin visual border / wider hit target separation.
- Shift aspect-ratio lock based on the box at gesture start.
- Mid-gesture Shift press/release with no jump.
- Preserve multi-selection on right-click of a selected member.
- Keyboard context-menu path parity.
- Low-level open intent hooks/events for Enter and double-click if needed by Slice 05, without implementing viewer orchestration here.
- Ctrl/Cmd+A scene selection intent when focus is not editable, if it can be added without final menu/viewer coupling.
- Focused JS/browser tests.

### Out of Scope

- Organization menu contents.
- Atomic layout command.
- Viewer implementation.
- Agent data projection.
- Global Ctrl/Cmd+Z transaction integration (Slice 05).
- Capsule representation redesign.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

None.

### Can Start With

Current scene interaction and page modules.

### Produces

Stable pointer/key selection and resize behavior that Slice 05 can build on without reopening the gesture refactor.

### Integration Checkpoint

Slice 05 owns final scene-page wiring after this Slice; it must preserve these tested gestures.

## Implementation Steps

1. Audit current pointer event order, selection anchoring, hold creation, pointer capture and prefab shield behavior.
2. Replace the single mouse grip concept with a side/corner descriptor while preserving accessibility and hit testing.
3. Route mouse resize through the existing side-based geometry path rather than reimplementing edge math.
4. Add aspect-ratio constraint in the shared manipulation layer and define anchor behavior for each edge/corner.
5. Rebase cleanly when Shift state changes mid-gesture.
6. Keep minimum/maximum size and viewport/control collision behavior identical to the existing hold contract.
7. Change context-menu selection logic: selected member -> keep selection and anchor it; unselected member -> replace selection.
8. Preserve Menu / Shift+F10 semantics for keyboard-composed selections.
9. Add or expose low-level Enter/double-click intent hooks if useful, without binding to a viewer implementation.
10. Add focused node/browser tests and mouse-path runtime evidence.

## Files Likely Touched

Revalidate at HEAD. Likely:

- `jarvis/runtime/control_center_scene_interact.js`
- `jarvis/runtime/control_center_scene_page.js`
- focused scene interaction/selection browser and JS tests

## Architecture Constraints

- Bare Hands keeps the same geometry owner and must not regress.
- No second pointer manipulation engine.
- Resize hit regions must not steal clicks from meaningful inner links/buttons.
- Multi-selection remains visible and stable during a context action.

## Automated Validation

Focused JS/node/browser tests for pointer resize, Shift rebase, context-menu selection and keyboard parity. Run targeted runtime-validation in an isolated Control Center harness. No full suite.

## Acceptance Criteria

- Every edge and corner resizes naturally.
- Shift preserves the starting aspect ratio and can toggle mid-gesture without jumps.
- Right-clicking a selected member does not collapse the group.
- Right-clicking an unselected member still gives intuitive single-object behavior.
- Existing group drag, selection band, Bare Hands manipulation and keyboard movement continue to work.

## Documentation Updates

Update user-facing keyboard/mouse interaction docs if they exist; otherwise add concise canonical interaction notes in the appropriate scene docs.

## Handoff Notes

This Slice is a hard predecessor of Slice 05 because both may touch the scene page hot path. Do not leave a second competing integration path for Slice 05 to merge manually.

