# Overview

## Goal

Make a Presentation Variant representable as **one real Remotion video project** without breaking the existing scene-version architecture that currently works.

The master project is initially a deterministic projection of the active variant's existing exact source pins. It is not yet a new source of truth.

## Desired mental model

### Current model

```text
Presentation
  Variant
    Scene 1 -> Remotion source/composition -> Player 1
    Scene 2 -> Remotion source/composition -> Player 2
    Scene 3 -> Remotion source/composition -> Player 3

Jarvis CompositionClock + sequencer makes these look like one video.
Remotion Studio receives one selected scene source.
Export renders one selected scene.
```

### A+B target

```text
Presentation
  Variant (canonical scene pins stay unchanged)
    Scene 1 source
    Scene 2 source
    Scene 3 source
           |
           v
   Remotion Master Project Planner
           |
           +--> normal project workspace
           |      src/master/Presentation.tsx
           |      src/scenes/<scene_id>/...
           |      public/...
           |      generated root/composition registration
           |
           +--> native Remotion Studio: whole project
           |
           +--> guarded renderer: whole master composition -> MP4

Existing Variants multi-Player path remains operational in parallel.
```

## User journey in scope

1. User asks Jarvis by voice/text to create a video/presentation.
2. Existing authoring flow creates ordered Remotion scenes and immutable source versions.
3. As soon as the variant is master-compatible, Jarvis can describe/materialize one master project and composition.
4. **Remotion Studio** opens the whole variant project and exposes the master composition.
5. **Export video** renders the whole master composition, not one scene.
6. The user asks Jarvis to change a scene/style/content by voice.
7. Existing source-edit flow publishes a new immutable scene version and updates the pin.
8. Master-project identity/digest changes deterministically; Studio can refresh/reopen and the next whole-video export includes the edit.
9. No direct master-workspace publication is required in this task.

## Scope

### In scope

- deterministic master project planning for one variant;
- master compatibility/status with typed refusal reasons;
- generated master composition using native Remotion sequencing primitives;
- safe source namespacing and deterministic asset handling;
- one Studio process capable of targeting the master project;
- whole-variant rendering/export through current sandbox/guard/Artifact semantics;
- voice/agent generation and scene edits that keep the master path usable;
- minimal Variants entrypoints/status so the user sees project-level Studio/export behavior;
- full regression protection for the current scene-based runtime.

### Out of scope

- replacing the current Variants playback sequencer;
- deleting scene-level Studio or scene export;
- arbitrary top-level project editing/publish back into the Presentation model;
- broad dependency changes or loosening the threat model;
- UI redesign beyond the minimum entrypoints/status needed to make the new model clear;
- silently rewriting legacy scene source code to normalize incompatible FPS, dimensions or public paths.

## Compatibility philosophy

The master path is **additive and fail-closed**. A variant that cannot be represented faithfully as one project must expose a specific reason and continue to work through the existing scene-based path. No automatic pre-render/concatenate fallback may pretend to be an editable Remotion master project.

The Project Manager must specifically audit heterogeneous FPS, heterogeneous dimensions, `staticFile()` asset collisions, audio/video assets, and assumptions made by scene code through `useVideoConfig()`. A simple deterministic compatibility envelope is preferred over risky source rewriting.
