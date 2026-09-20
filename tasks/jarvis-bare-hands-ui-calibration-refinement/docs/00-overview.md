# Overview

## Goal

Make the current Bare Hands V1 feel like a first-class Jarvis interaction mode rather than an experimental settings feature.

## Current repository baseline

At reviewed main commit `a949f40c16c4a61fc563e7d7cdf1c32da913c207`, the repository already contains substantial Bare Hands implementation:

- `control_center_barehands.js`: lifecycle, stable tracking/filtering, gesture/pinch intent, target resolution, interaction/capture integration, current Settings UI hooks.
- `control_center_barehands_contracts.js`: lifecycle/tool/profile/DOM contracts.
- `control_center_barehands_calibration.js`: seven-step calibration plus current modal-style shared flow shell.
- `control_center_barehands_tutorial.js`: separate tutorial flow.
- `control_center_barehands_recorder.js`: diagnostics/recording/replay.
- `barehands_test_mode.py`: persisted settings including `enabled`, `target_preview`, `tool`, `tutorial_seen`, `calibration_enabled`, diagnostics, etc.
- `control_center_barehands_commands.js` + `jarvis/domain/barehands_command.py`: voice/MCP command path including activate/deactivate/calibrate/tutorial/exit_overlay.
- `control_center_scene_page.js` + `control_center_scene_interact.js`: real scene/frame rendering and move/resize geometry.
- `docs/barehands-contracts.md`: canonical behavior contract.

This task is therefore an **information architecture and calibration UX refinement**, not a foundational Bare Hands implementation task.

## Scope

- first-class Bare Hands HUD lifecycle button and state chooser;
- right-click quick-action menu;
- fixed left tool palette for existing tools only;
- Settings cleanup;
- visual Help/Gestures card;
- Diagnostics quick entry;
- removal of separate user-facing Tutorial flow;
- full-screen calibration overlay redesign;
- intro/armed/running stage timing;
- simple schematic hand demonstrations;
- target pinch calibration;
- real Jarvis window move/resize practice within calibration;
- migration/tests/docs.

## Non-goals

- no new tool implementations;
- no new gesture-action bindings;
- no redefinition of existing contextual interaction semantics;
- no tracker/model/hardware change;
- no system-wide app control;
- no broad Constellation visual redesign;
- no separate Tutorial product surface.

## Mental model

The corrected product hierarchy is:

`Main HUD lifecycle button` → OFF / SLEEP / ACTIVE

`Right-click menu` → Settings / Calibration / Help / Diagnostics

`Left tool palette` → Pointer / Pan / Select

`Calibration` → both personalization and guided learning

`Settings` → persistent configuration only

The runtime state remains authoritative; UI components subscribe/render it rather than owning parallel local state.
