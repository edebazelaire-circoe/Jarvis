# 06 - Branch compliance audit (static snapshot)

**Reference**: https://github.com/edebazelaire-circoe/Jarvis/tree/task/jarvis-interactive-presentation-studio at `16e3dc585a29a767af26440e5a4364c8d57d9065`. Read-only GitHub connector review; **no local checkout or independent test execution** (git host network unavailable in this session). Old `LOG.md` recorded a sweep, not reproduced here. Branch was still in progress at the time of review. The statuses below describe code/doc evidence as of this commit, not readiness to ship.

### 01. Presentation aggregate and per-scene structures

- **Status**: Implemented, Level 3.
- **Finding**: StudioScene/PresentationVariant and service support editable source pointers, pins and controls.
- **Evidence**: `docs/presentation-studio.md:19-50; jarvis/domain/presentation_studio_scene.py`.

### 02. High-quality serious first draft + art direction

- **Status**: Partial.
- **Finding**: Authoring quality gate with rules; real-model end-to-end results and source harvesting still need proof.
- **Evidence**: `docs/presentation-studio.md:583-766; tasks/.../LOG.md S11`.

### 03. Script/score and prepared cues

- **Status**: Implemented, with runtime caveats.
- **Finding**: Score supports tracks, roles, silence, soft cues, locked sequences; real live voice behavior still must be validated.
- **Evidence**: `jarvis/domain/presentation_studio_score.py`.

### 04. Audience sidekick and Jarvis presenter

- **Status**: Partial in practice.
- **Finding**: Services in branch, live microphone and audible timing tests pending.
- **Evidence**: `jarvis/core/presentation_studio_playback.py; presenter.py`.

### 05. Rehearsal

- **Status**: Pending.
- **Finding**: Old Slice 15 unchecked at snapshot.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 06. Fullscreen host

- **Status**: Partial.
- **Finding**: Browser API requires click; not proof of arbitrary monitor native takeover.
- **Evidence**: `jarvis/domain/surface_fullscreen.py`.

### 07. Semantic control patch/Inspector/Hot reload

- **Status**: Implemented (Slidecar).
- **Finding**: Prefab pins, controls, source revision publication and one scene reload exist; not a Remotion bridge.
- **Evidence**: `jarvis/core/presentation_studio_reload.py; runtime/inspector.js`.

### 08. Autosave, bounded undo/redo

- **Status**: Implemented.
- **Finding**: File store + session memory undo; no infinite snapshots.
- **Evidence**: `jarvis/core/presentation_studio_autosave.py`.

### 09. Whole-presentation and scene alternatives

- **Status**: Implemented (domain).
- **Finding**: Operations exist; visual explorer/comparison remain pending.
- **Evidence**: `jarvis/core/presentation_studio_variants.py; scene_variants.py`.

### 10. Visual variant explorer + multi-compare/mix

- **Status**: Pending.
- **Finding**: Old Slices 18/19 unchecked.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 11. Template/prefab promotion

- **Status**: Pending.
- **Finding**: Old Slice 20 unchecked; new explicit promotion only rule locked.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 12. Voice-edit / agent tool surface

- **Status**: Pending.
- **Finding**: Old Slice 21 unchecked; existing ambient follower does not equal voice authoring.
- **Evidence**: `tasks/.../slices/TODO.md`.

### 13. Remotion Player / Studio / export

- **Status**: Missing.
- **Finding**: No Remotion integration in inspected branch; HTML/JS prefab host used.
- **Evidence**: `docs/presentation-studio.md / code refs`.

### 14. Engine policy (Remotion forced, Slidecar experimental)

- **Status**: Missing.
- **Finding**: No multi-engine interface or selection; all scenes prefab HTML.
- **Evidence**: `jarvis/domain/presentation_studio_scene.py`.

### 15. Local install-once plugin

- **Status**: Missing.
- **Finding**: Current plugin registry remote MCP URL only.
- **Evidence**: `docs/mcp/plugins.md:49-100`.

### 16. Board artifact source and derivatives

- **Status**: Missing bridge.
- **Finding**: Presentations live under data_root/presentations, not ArtifactService; existing Artifact kinds closed/terminal and Board links available.
- **Evidence**: `docs/presentation-studio.md:143-165; docs/artifacts.md:20-60,204-245`.

### 17. Live assets + self-contained export

- **Status**: Missing bridge.
- **Finding**: Resource references recorded; no verified freeze-and-export pipeline.
- **Evidence**: `jarvis/domain/presentation_studio.py`.

### 18. Prefabs category/taxonomy/compat/tech stack

- **Status**: Missing extension.
- **Finding**: Current Prefab is a window HTML bundle with version and props/data, without Remotion engine details.
- **Evidence**: `docs/prefabs.md`.

### 19. External provenance/licenses

- **Status**: Missing extension.
- **Finding**: Current Prefab provenance records base/custom/fork/revision, no full imported upstream manifest.
- **Evidence**: `docs/prefabs.md`.

### 20. Prefab latest notice and upgrade-in-variant

- **Status**: Missing extension.
- **Finding**: Immutability/pinning exists, but explicit new-version trial UX is new.
- **Evidence**: `docs/prefabs.md; StudioScene`.

### 21. Main branch integration readiness

- **Status**: Conflict risk.
- **Finding**: Branch 129 ahead / 85 behind main at snapshot; cannot assume clean merge.
- **Evidence**: `GitHub compare main...task branch`.

## Special risks and contract conflicts

- Artifact immutable terminal lifecycle vs repeatedly saved Presentation source; resolve mapping *before* implementing registry links. Do not substitute renaming directories for integration.
- Existing browser fullscreen cannot satisfy a spoken-only enter without user gesture; new native-host capability is a separate explicit decision if required.
- Existing MCP external Plugin is a remote server endpoint; local Node tools need an actual host lifecycle/permissions model.
- Remotion Player can preview props, not automatically render arbitrary browser-only interactivity to MP4. Compatibility declaration must be capability-scoped, including export.
- Upstream Remotion SDK/codemods are experimental; pinned versions, seam isolation and live tests are prerequisites.
- Source/head drift, unmerged WIP and baseline reds need fresh PM audit after original task completes.
