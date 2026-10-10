# 03 - Implementation Strategy

## Phase 0 - Reconcile reality

Slice 00 and Slice 01 must audit the live repository before coding. The Presentation interaction mode is already implemented on `main`; the Scene/Prefab foundation is an active separate handoff and may change before this task starts.

Do not code against guessed file names from this handoff.

## Phase 1 - Establish contracts before UI

Implement Presentation Artifact, scene presentation metadata/control schema, score, variant and persistence contracts before behavior-heavy UI. The purpose is to prevent a fullscreen prototype or variant browser from becoming the de facto data model.

## Phase 2 - Rendering/edit substrate

Add generic fullscreen borderless surface support through the canonical scene/window boundary, then implement semantic edits and scene-local hot reload. The GUI edit inspector comes only after the edit API exists so it cannot create a parallel mutation path.

## Phase 3 - Authoring semantics

Implement DA sourcing/generation, score/cue model and authoring planner. Validate that the planner can produce a complete first draft without requiring editing, while still supporting exploratory multi-direction generation.

## Phase 4 - Playback and rehearsal

Build the playback state machine, user-presenter cue following, Jarvis presenter locked sequences and rehearsal. Integrate with the existing Presentation ambient lane and explicit-address priority rules.

A critical gate: cue matching must prove that ambient speech can only satisfy pre-armed cue IDs, not authorize arbitrary actions.

## Phase 5 - Creative branching

Add presentation variants, scene-local variants, Variant Explorer, comparison and semantic branch composition. Keep branch persistence independent from the short undo ring.

## Phase 6 - Reuse and agent ergonomics

Add promotion to shared templates/prefabs and complete the agent-facing semantic operations. Ensure voice commands and GUI controls resolve to the same operations and stable IDs.

## Phase 7 - Hardening

Run end-to-end scenarios across all three playback roles, crash/restart autosave, HMR failures, cue ambiguity, full-screen exit/restore, branch deletion, comparison, template promotion and current SIMPLE/PRESENTATION regression gates.

## Cross-task dependency policy

### Scene/Prefab foundation

Slices that instantiate/update/persist reusable scene objects are blocked until the active `jarvis-scene-window-prefab-foundation` public contracts are available or Slice 00 proves equivalent contracts already landed in `main`.

### Tool Brain

Do not block the artifact/score/domain model solely because Tool Brain is absent. Use a semantic intent seam. Integrate the canonical Tool Brain when/if it exists at implementation time.

### Existing Presentation mode

This is a hard integration dependency, not a code dependency to rewrite. The current ambient lane, working set, explicit-address priority and privacy model must remain authoritative.

## Migration / compatibility

Existing Presentation mode must continue to function without any Presentation Artifact loaded. Existing scene objects/windows must not be forced into the presentation schema. Fullscreen should be an opt-in capability of compatible surfaces.
