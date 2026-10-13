# Target architecture

## Canonical ownership

| Concern | Authority after A+B |
| --- | --- |
| Presentation/variant identity and graph | Existing Presentation Studio documents/services |
| Scene source contents | Existing immutable Remotion prefab/source versions |
| Which source a scene uses | Existing exact scene pin in the variant |
| Voice/source edits | Existing validated source-edit door, CAS, rollback and `presentation_source` tooling |
| Master-project readiness | New pure master-project planner over the current variant + pinned source manifests |
| Master project files | Deterministic projection, materialized only for Studio/render/preview use |
| Master composition timing | Native Remotion master composition generated from ordered scenes; no new Jarvis wall-clock scheduler for this path |
| Current Variants playback | Existing CompositionClock + per-scene Players, unchanged in this task |
| Remotion Studio process | Existing managed local process/security boundary, extended with project target support |
| Whole-video rendering | Existing guarded render runner/browser/Artifact path, supplied with the master workspace/composition |
| Presenter score/cues | Existing Core model; not moved into the master composition in this task unless already consumed by scene source |

## New pure concept: MasterProjectPlan

Create one reusable pure planning layer. Exact class/module names are for the implementation audit to confirm, but there must be **one shared source of truth** for Studio, renderer, UI readiness and agent status.

Conceptual output:

```text
MasterProjectPlan
  presentation_id
  variant_id
  variant_revision
  project_key/digest
  status: ready | incompatible
  reason/code when incompatible
  master_composition:
    id
    width
    height
    fps
    duration_in_frames
  ordered scenes:
    scene_id
    prefab_id
    version
    source digest
    duration
    source entry
  planned files / source namespaces
  public asset merge plan
```

`project_key` must change if scene order, exact pins, source digests or any master-relevant project input changes. A title-only rename should not force unrelated source changes unless the title is intentionally part of the generated project.

## Master workspace shape

Recommended shape; the audit may adjust exact file names while preserving semantics:

```text
work/
  package.json                 generated project root, uses shared installed Remotion runtime
  studio-root.tsx              generated registerRoot
  src/
    master/
      Presentation.tsx         generated master composition component
    scenes/
      <scene-id-1>/            source files of exact pinned version
      <scene-id-2>/
      ...
  public/
    ...                        deterministic merged assets
```

The generated root registers at least one stable master composition ID such as `JARVIS_PRESENTATION`. Optional scene-debug compositions are allowed if they do not become a second canonical timing system.

## Native sequencing

Use Remotion primitives for the master timeline. A zero-overlap first implementation may use `Series`/`Sequence`. If a current durable transition contract exists and can be mapped faithfully with installed Remotion packages, use it; do not invent a custom browser timer.

Each scene must begin on its local frame zero inside the master sequence. The final master duration must be deterministically derived from scene durations and any explicitly supported transition overlap.

## Compatibility boundary

The planner must reject rather than silently mutate when faithful composition is not proven. At minimum audit:

- scene engine is Remotion and source is healthy/not tampered;
- common width/height/fps or another formally proven compatible mapping;
- source entry/module layout can be namespaced without altering relative imports;
- all public assets can be merged without changing `staticFile()` semantics;
- existing scene props/data can be supplied in the master context;
- no source relies on a per-scene configuration that the master changes unexpectedly;
- project size/file budgets stay bounded.

A typed incompatible status must be visible to Studio/export/agent/UI consumers. It is **not** a presentation corruption.

## Studio target model

Current service state is scene-pin-centric. Introduce a target identity that can represent the master project without discarding scene behavior.

Conceptually:

```text
StudioTarget
  kind: scene | variant_master
  scene pin fields when kind=scene
  presentation_id + variant_id + variant_revision/project_key when kind=variant_master
```

One Studio process remains the default. Switching targets follows existing explicit acknowledgment, local-only networking, clean environment, process guard and unpublished-work protection.

For A+B, master-workspace modifications are not silently publishable. If users modify the generated workspace, the service must preserve or explicitly discard/set aside them using a clear contract. It must never guess how an arbitrary top-level project change maps back to scene versions.

## Render path

The snapshot already freezes a full presentation/variant and pinned sources. Add a master render plan that consumes the whole frozen package:

```text
FrozenPackage
  -> validate exact master inputs
  -> plan_master_files(...)
  -> generated master composition
  -> existing guarded render host/browser
  -> verify MP4 incl. duration/audio/video
  -> existing presentation_video Artifact rendered_from snapshot
```

Scene export continues to use the current `choose_scene/plan_files` path.

## Voice/agent path

Do not create a parallel master-source write protocol for A+B.

```text
User voice/text request
 -> existing presentation authoring flow
 -> native scene source versions
 -> variant pins
 -> master project planner = ready
 -> Studio/export use master

User asks for change
 -> existing presentation_source write / semantic edit
 -> new immutable scene version + repin
 -> project_key changes
 -> master workspace/status/render automatically sees new inputs
```

The agent must be able to inspect master readiness/reason and to request a whole-video export on the user's instruction. It must not claim a full export exists if only scene renders were produced.

## Legacy/compatibility lane

The current scene-based CompositionClock/sequencer remains a supported lane during this task. It must not be called "master Remotion composition" in new documentation. New docs should distinguish:

- **master Remotion Composition**: real generated full-video composition;
- **Variants composition clock**: current Jarvis interval map used by the compatibility Player.
