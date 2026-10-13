# Slice 08 — Minimal Variants entrypoints for master Studio/export

## Goal

Make the new project-level semantics understandable and usable in the existing Variants screen without broad UI redesign.

## Context

Current UI text is scene-centric (for example, Studio open on scene N). The user wants the primary concept to be the whole Remotion project/video while preserving the current player for now.

## Canonical Concepts

Master readiness/status, master Studio target, whole-video export, existing Variants compatibility Player.

## Scope
### In Scope

- primary `Remotion Studio` action targets the variant master project when ready;
- project-level status text names presentation/variant/project rather than one selected scene;
- whole-video export action/state uses master scope;
- clear typed reason when master unavailable/incompatible;
- keep current scene selection/player/transport untouched;
- preserve a documented compatibility path to scene-level Studio if still needed.

### Out of Scope

- new Variants layout/tree redesign;
- master Player;
- duplicating Remotion Studio timeline in Jarvis;
- new editing widgets.

## Dependencies

`05-remotion-studio-master-project`, `06-whole-variant-render-export`, `07-voice-generation-and-reedit`.

## Implementation Steps

1. Refresh the current Explorer/Remotion door/export owners after latest UI changes.
2. Add/read master readiness once; avoid frontend reimplementation of compatibility logic.
3. Change the primary Studio door to the master target, with existing explicit safety confirmation semantics adapted to project identity.
4. Add/retarget whole-video export using the existing render job UI pattern if present.
5. Keep player, transport, scene strip and presenter behavior unchanged.
6. Ensure legacy scene Studio/export is not accidentally exposed as an equally prominent competing primary path; retain it in a clear compatibility/debug location only if still user-reachable.
7. Verify 800x600, 1280x720, 1920x1080 and fullscreen interactions relevant to changed controls.

## Files Likely Touched

`jarvis/runtime/control_center_presentation_studio_explorer*.js`, Remotion Studio/explorer modules, render UI/relay modules, CSS/tests/docs as fresh audit confirms.

## Architecture Constraints

No second Jarvis timeline/editor. Do not imply the current Variants multi-Player preview is already the master composition; it remains the compatibility viewer until phase C.

## Automated Validation

Frontend DOM/behavior tests; real browser master-ready and incompatible cases; Studio action sends variant/master identity; export sends master scope; old player controls unchanged; accessibility labels; responsive layout.

## Acceptance Criteria

The user sees one clear project-level Remotion Studio action and one clear whole-video export path. The UI no longer suggests that opening Remotion Studio fundamentally means opening only the current slide, while the current playback experience still works.

## Documentation Updates

Update UI/control inventory and operating docs. Avoid future-facing claims about phase C.

## Handoff Notes

Frontend coding Slice: `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude frontend Work Agent when host routing supports it. QA + code-review + runtime-validation required. Human check `HV-RMP-08-01` after machine/browser evidence.
