# 02 - Architecture

## Current authoritative domains

### Scene

The scene domain owns active objects, representation, geometry, visibility and relations. Existing selection-batch semantics already resolve and apply a command atomically on one snapshot.

This feature adds at most one missing semantic capability: an atomic arbitrary-geometry update for a selected set. The exact operation name/wire shape is decided in Slice 01 after a fresh audit. A working name such as `layout_selection` is descriptive but not a requirement.

Required semantics:

- bounded explicit members;
- one target geometry per member;
- all targets validated on the same current snapshot;
- all-or-nothing patch;
- one scene revision when applied;
- batch report consistent with existing selection commands;
- user/brain authority consistent with existing explicit geometry commands;
- optional/required compare-before-write data if needed to make geometry undo safe against stale state.

### Work State

Work State remains the sole source of live execution status. The agent viewer reads its public fields: status, activity, summary, progress fraction, timestamps, counters, role and parent identity.

### Mission History

Mission History supplies durable objective, instance, role, hierarchy and relation context. It never replaces live Work State status.

### Artifact / scene relations

Produced artifacts should be discovered from existing durable artifact/scene relations or canonical Board artifact links. The viewer must not infer products by title matching.

### Viewer overlay

Implement the visual viewer as a new Control Center module with a small stable API, for example conceptually:

- `openObjects(entries, options)`
- `openAgent(viewModel, options)`
- `close()`
- `isOpen()`
- layout switching independent of scene mutation

The exact names are implementation details. The important boundary is that scene-page integration launches the viewer; the viewer does not become a scene-state owner.

## Input architecture

`control_center_scene_interact.js` already centralizes geometry manipulation. Extend the existing hold/manipulation path rather than adding a parallel pointer geometry implementation.

The mouse path needs to describe which side(s) are active, then reuse the existing side-based resize math. Shift aspect locking should occur in the same geometry layer so preview and committed geometry cannot diverge.

## Organization planner

Keep arrangement math deterministic and pure where practical. A pure JS planner can turn current boxes plus an action into target boxes, while Core remains authoritative for accepting the resulting atomic layout command.

Candidate pure operations:

- spatial ordering;
- bounding box / centroid;
- row/column packing;
- grid dimensions and gaps;
- alignment/distribution;
- equal width/height/size;
- group clamp to usable scene area.

Do not make CSS layout the source of truth for scene geometry.

## Undo architecture

The browser may retain a short ring of geometry transactions:

- target ids;
- before geometries;
- after geometries;
- command/revision identity if available.

Undo validates that each target still reflects the recorded `after` state (preferably atomically in Core when the Slice 01 contract can support it). If not, invalidate/refuse the undo instead of reverting unrelated newer edits.

## Agent viewer projection

Prefer one bounded read-model endpoint or existing composable reads that returns a UI-safe public projection. It should join:

- scene execution object / work identity;
- live Work State;
- Mission History objective and relations;
- actual child work if available;
- related artifacts.

If an explicit public plan-step contract is added, it must be bounded, optional and clearly distinct from hidden reasoning. Provider adapters may publish structured steps; the UI must not synthesize them from private traces.

## Existing fullscreen boundary

`jarvis/domain/surface_fullscreen.py` and `control_center_fullscreen.js` are the canonical browser fullscreen path. The object viewer is simply a high-z-index in-app overlay. Do not report it as browser fullscreen state and do not require the fullscreen command arm/gesture flow.

## Active-task boundaries

Slice 00 must check at current HEAD:

- `jarvis-scene-window-prefab-foundation`: generic window/prefab ownership;
- `jarvis-interactive-presentation-studio`: true fullscreen / presentation overlays;
- `jarvis-unified-chat-and-board-drop`: chat and Board UI ingress;
- any newer task touching `control_center_scene_page.js`, `control_center_scene_interact.js`, global overlays, context menus or keyboard handlers.

Shared-hot-file ownership is a scheduling constraint, not a reason to duplicate code.

