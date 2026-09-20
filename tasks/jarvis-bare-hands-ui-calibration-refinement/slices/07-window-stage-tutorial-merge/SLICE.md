# Slice 07 — Add real window move/resize practice and retire separate Tutorial

## Goal

Replace the generic drag/two-hands calibration exercises with one real Jarvis window-manipulation exercise, and remove the competing standalone Tutorial product flow.

## Context

The current calibration has separate `DRAG` and `RESIZE` steps, while `control_center_barehands_tutorial.js` teaches interactions separately. The user now wants calibration to do both jobs. Step 6 must look and behave like a real Jarvis frame/window: one captured border/corner moves it; two distinct compatible captures resize it.

## Canonical Concepts

- frame BODY vs edge/corner target regions
- latched capture semantics
- one-zone move and two-zone constrained resize
- `control_center_scene_interact.js` geometry (`manipulateBox`, `rebaseManipulation`, min-size/no-inversion)
- scene frame/window rendering conventions
- current calibration drag-travel profile derivation
- current tutorial module and tutorial voice/MCP command

## Scope

### In Scope

- Replace user-facing generic Step 6/7 drag/resize exercises with one **Manipulation de fenêtre** step containing sub-steps 6A and 6B.
- 6A: present an ephemeral practice Jarvis frame; user captures one edge/corner with one hand and moves the whole frame.
- 6B: same practice object; user captures two different compatible zones with two hands and resizes larger/smaller.
- Reuse canonical target resolution, capture combination and scene geometry. Do not create a second simplified resize algorithm.
- Keep the practice object sandboxed/ephemeral; it must not persist in the real scene model.
- Preserve/use existing drag-travel calibration samples where technically valid.
- Make completion/report the seventh public screen.
- Remove the separate user-facing Tutorial entry/overlay/state.
- Migrate `tutorial_seen` or equivalent stale settings safely.
- Apply Slice 00's chosen compatibility plan for existing `tutorial` voice/MCP command; preferred behavior is deprecated alias to calibration with no distinct tutorial UI/state.
- Update tests and contracts so only one guided flow exists.

### Out of Scope

- Redefining real scene window move/resize rules.
- Changing frame visuals globally outside the practice representation needed for fidelity.
- Adding new tutorial-only gestures.

## Dependencies

03, 05, 06

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check scene window rendering/adapters, Bare Hands capture engine, and calibration measurement seam.
3. Design an ephemeral practice-window adapter that can participate in the real target/capture/geometry path without entering persistent scene state.
4. Implement 6A move validation using a one-zone capture.
5. Implement 6B resize validation using two distinct compatible zones, including min-size/no-inversion and release behavior inherited from production code.
6. Feed useful drag/click separation measurements through the existing calibration profile path where applicable.
7. Remove/deactivate the standalone tutorial UI/module loading path and Settings/menu entry points.
8. Migrate tutorial persistence/command compatibility explicitly.
9. Add unit/browser/runtime/command-trace tests.

## Files Likely Touched

- `jarvis/runtime/control_center_barehands_calibration.js`
- `jarvis/runtime/control_center_barehands_tutorial.js` (retired/removed or reduced to compatibility shim if required)
- `jarvis/runtime/control_center_barehands.js`
- `jarvis/runtime/control_center_barehands_contracts.js`
- `jarvis/runtime/control_center_scene_page.js` and/or a safe practice-frame adapter
- `jarvis/runtime/control_center_scene_interact.js` only if an adapter hook is genuinely missing; do not duplicate geometry
- `jarvis/runtime/barehands_test_mode.py`
- `jarvis/runtime/control_center_barehands_commands.js`
- `jarvis/domain/barehands_command.py` if command vocabulary/version changes
- calibration/tutorial/interaction/command tests

## Architecture Constraints

- Real window semantics are reused, not approximated.
- Practice frame never persists into scene storage.
- Existing BODY/zone/bimanual rules remain canonical and unchanged.
- There is one guided user flow after this Slice: Calibration.
- Legacy compatibility must not expose a second overlay/state machine.

## Automated Validation

- 6A requires a valid one-zone capture and proves move semantics.
- 6B requires two distinct compatible zones and proves resize semantics.
- Duplicate/incompatible zones do not falsely complete the step.
- Practice frame respects min size/no inversion and surviving-hand behavior from production engine.
- Practice object is absent from persistent scene state before/after calibration.
- Public flow has six exercises + completion.
- Separate tutorial cannot be launched as a distinct UI flow.
- Legacy tutorial command is either explicitly aliased to calibration or explicitly versioned/removed per Slice 00 decision, with trace evidence.
- Existing calibration profile derivation remains valid.

## Acceptance Criteria

- Window training feels like manipulating a real Jarvis frame.
- One hand moves; two compatible captures resize.
- No standalone Tutorial surface remains.
- Calibration remains the single place to learn/test these interactions.

## Documentation Updates

Update Bare Hands flow documentation, command compatibility notes, settings schema/migration notes, and remove obsolete tutorial documentation.

## Handoff Notes

Baseline `qa-verification`, `code-review`, `runtime-validation`, and `agent-trace-analysis` are required because the command/tool path may change.
