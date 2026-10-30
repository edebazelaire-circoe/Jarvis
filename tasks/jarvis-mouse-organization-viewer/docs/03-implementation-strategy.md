# 03 - Implementation Strategy

## Dependency strategy

The handoff intentionally separates four early branches that can be developed in parallel after Slice 00:

1. atomic layout/undo contract;
2. mouse/input behavior;
3. viewer shell and media/document rendering;
4. agent public projection.

Scene integration then converges these seams in one owner Slice to avoid concurrent edits to the hottest page controller.

## Suggested implementation sequence

### Branch A - atomic layout

Add or adapt one scene command capable of applying arbitrary target boxes atomically. Preserve the existing `SceneSelection` / `SceneBatchReport` mental model where it fits. Add focused domain/wire tests, but do not run the full suite in this Slice.

Define stale/compare semantics sufficient for safe undo. Avoid introducing a general history subsystem.

### Branch B - mouse/input

Refactor pointer resize intent from `is .sc-grip` to a side/corner descriptor. Reuse `resizeBySides()` and hold bounds. Add aspect-ratio behavior in the shared geometry layer.

Fix context-menu anchoring so an already-selected object does not collapse the selection. Add low-level key/double-click intents but do not wire the final viewer/menu orchestration here if that would collide with Slice 05.

### Branch C - viewer shell

Build a new isolated viewer module and fixture harness. It should render without requiring a live scene or live agent runtime. This allows visual/runtime QA before scene integration.

Content adapters should degrade safely by type. Initial priority: images plus already-supported document/artifact representations. Reuse safe existing prefab/document display components where appropriate; do not embed arbitrary raw HTML outside the prefab safety contract.

### Branch D - agent projection

Create a bounded public read model using existing Work State and Mission History. Reuse existing cancellation. Define Ask routing through canonical communication/chat. Add explicit public step data only if a real upstream structured source exists or a small bounded contract is necessary; otherwise expose actual child work and a `plan unavailable` state.

### Convergence - scene integration

The integration Slice owns the final scene context menu, keyboard dispatch, double-click launch, organization UI and viewer wiring. It reconciles real interfaces from Branches A/C/D rather than requiring those branches to block on each other.

## Layout behavior details

### Ordering

Use centers of current drawn boxes. Sort primarily by top/row band, then x, then stable snapshot/selection order. Reuse a current spatial-order helper if one already exists and matches this intent.

### Row / column

Pack with a consistent visible gap. Preserve individual sizes. Center the resulting block on the original selection center, then clamp the block as a whole to the usable area.

### Auto grid

Choose rows/columns close to the selection aspect ratio and item count. Do not resize items simply to force a perfect matrix.

### Custom grid

The graphical picker selects N x M, and numeric fields allow larger values such as 3 x 8. Fill row-major. Empty final cells are allowed. Reject impossible zero/negative/over-limit values locally and at the command boundary where applicable.

### Align / distribute

Alignment preserves non-target axes and sizes. Distribution requires at least three eligible objects; with fewer, show disabled/explanatory state rather than a no-op surprise.

### Same size

Use a deterministic reference: the active/anchor object in the current selection when one exists, otherwise the last selected item. The menu should make the reference understandable if this is not visually obvious.

## Viewer interaction details

- Overlay traps focus while open and restores focus to the launching scene object on close when it still exists.
- Escape closes one overlay layer at a time.
- Layout picker is keyboard accessible.
- Image pan should not steal ordinary page scrolling outside the image viewport.
- Reduced-motion removes nonessential zoom/fade transitions.
- A multi-view layout never mutates source or Board geometry.
- Unsupported content produces a typed fallback with metadata/open-external option when safe, not a blank tile.

## Agent viewer interaction details

Use a small number of high-level panels: mission/status header, current activity/progress, public steps, findings/summary, artifacts, actions. Avoid telemetry dashboards by default.

Elapsed time is computed from canonical timestamps and current time; terminal agents show their final duration when the source provides an end time or a truthful lower-fidelity fallback when it does not.

