# Slice 05 — Replace the calibration modal with the full-screen exercise shell

## Goal

Rebuild calibration presentation so the whole viewport becomes the guided calibration space, while preserving current profile derivation and safety behavior.

## Context

The current `control_center_barehands_calibration.js` shell renders a centered `.jf-step` modal/card. The user explicitly rejected that composition. The desired experience is full-screen, blurred, calm, and centered around the exercise itself rather than a box.

## Canonical Concepts

- existing `createFlowOverlay` and calibration shell lifecycle
- current calibration profile derivation/privacy semantics
- Bare Hands hand overlay/token z-order
- Control Center scene/background layering

## Scope

### In Scope

- Replace the centered calibration card composition with a full-viewport shell.
- Preserve a blurred/darkened view of Jarvis behind the exercise.
- Put step number/title/short instruction in the upper area.
- Reserve the central majority of the viewport for demonstration/exercise content.
- Keep progress visible but visually light.
- Keep Skip/Quit/Close/Escape available but secondary.
- Add named regions/slots for demonstration visual, exercise target, live feedback, progress, and controls.
- Provide reusable simple schematic/robotic hand rendering primitives or hooks needed by Slice 06.
- Preserve the existing Bare Hands tracking overlay visibility needed during calibration.

### Out of Scope

- Changing calibration measurements/derivation.
- Changing step order/content beyond the shell interface.
- Window practice behavior (Slice 07).

## Dependencies

02

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check current calibration overlay z-index, DOM API and tests.
3. Refactor the shell API so step content can occupy viewport regions without a central modal wrapper.
4. Implement backdrop/blur/typography/progress/control layout using existing Jarvis/Omega tokens where practical.
5. Add a simple reusable schematic hand visual system using SVG/CSS line art; avoid realistic anatomy.
6. Preserve close/Escape/cleanup invariants and hand-token visibility.
7. Add responsive and reduced-motion handling.
8. Add browser/runtime tests.

## Files Likely Touched

- `jarvis/runtime/control_center_barehands_calibration.js`
- possibly `jarvis/runtime/control_center_barehands.js` if overlay glue changes
- `control_center_barehands_tutorial.js` only if shared-shell coupling must be broken before Slice 07
- calibration UI tests

## Architecture Constraints

- Shell remains presentation; derivation stays pure.
- No images/video are introduced into profile data.
- No exercise should depend on a fixed centered modal geometry.
- Bare Hands hand/token overlay must remain usable above/with the shell as current architecture requires.

## Automated Validation

- Old centered-card layout no longer renders in calibration.
- Shell occupies viewport and exposes expected content regions.
- Background blur/veil does not block required tracking interaction.
- Escape/close/skip clean up all state/resources.
- Responsive layout works across representative viewport sizes.
- Reduced-motion mode remains usable.

## Acceptance Criteria

- Calibration visually reads as a full-screen Jarvis mode, not a modal wizard.
- The center is free for exercises.
- Text is large/calm and spatial hierarchy matches the locked direction.
- Existing calibration persistence/privacy behavior is unchanged.

## Documentation Updates

Document the calibration shell layout contract and reusable visual regions.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required.
