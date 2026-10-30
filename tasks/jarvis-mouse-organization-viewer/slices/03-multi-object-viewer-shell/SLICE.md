# Slice 03 - Multi-object viewer shell

## Goal

Build the isolated full-viewport object viewer shell and content/layout behavior so it can be validated independently before scene integration.

## Context

The viewer is an in-app overlay, not browser Fullscreen API state. It must support one or several images/documents, multiple layouts, clean dark/blurred visual treatment, image zoom/pan and document scrolling.

## Canonical Concepts

- Control Center overlay/z-index ownership
- prefab/document safety boundaries
- focus trapping/restoration
- reduced motion
- existing artifact/document preview providers

## Scope

### In Scope

- New viewer module/shell with an explicit launch/close API.
- Full viewport dark/blurred overlay.
- Single, horizontal, vertical, 2x2, row, column, auto grid, custom grid and selected asymmetric presets.
- Graphical custom-grid picker plus numeric rows/columns.
- Image fit/zoom/pan.
- Scrollable document/text/PDF content through existing safe renderers/providers where available.
- Typed unsupported-content fallback.
- Viewer-local back/history seam sufficient for opening an artifact from the later agent viewer and returning, if the architecture can support it cleanly.
- Focus trap, Escape close, focus restore hook, reduced-motion behavior.
- Fixture/demo harness and focused browser/runtime tests.

### Out of Scope

- Scene double-click/Enter wiring.
- Scene context menu.
- Agent-specific data rendering beyond an API slot/template seam.
- Persistent viewer layouts.
- Contact sheet/export.
- Browser `requestFullscreen()`.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Existing prefab/document display providers. If a provider is unavailable or still owned by an active task, use a typed fixture adapter and integrate at Slice 05.

Fallback: fixture-based viewer entries with image/text/unsupported content.

Integration required before: `05-scene-integration-organize-viewer` for real scene/artifact content.

Mismatch policy: adapt the viewer entry adapter; do not duplicate the provider/runtime.

### Can Start With

Current Control Center overlay conventions and isolated fixtures.

### Produces

A stable viewer API, visual shell and content-layout component contract.

### Integration Checkpoint

Slice 05 binds real scene/artifact entries and confirms z-index/focus compatibility with current overlays.

## Implementation Steps

1. Audit current global overlay/z-index registry and presentation/fullscreen surfaces.
2. Define a small viewer entry/view-model contract separate from scene domain storage.
3. Implement overlay shell, focus management and close behavior.
4. Implement layout planner/renderer and accessible layout picker.
5. Implement custom grid picker and numeric fallback.
6. Implement image zoom/pan/fit and reset controls.
7. Connect only safe existing document renderers/providers; use typed fallback for unsupported types.
8. Add reduced-motion and high-zoom/responsive behavior.
9. Build a fixture harness covering 1, 2, 4, 5 and 24 entries.
10. Capture focused visual/runtime evidence in both supported Jarvis themes if both remain current.

## Files Likely Touched

Prefer new isolated modules such as a Control Center object-viewer JS/CSS module and focused tests. Revalidate exact integration host at HEAD. Avoid editing `control_center_scene_page.js` in this Slice unless Slice 00 explicitly assigns ownership here.

## Architecture Constraints

- Viewer state is transient UI state.
- No scene geometry writes.
- No fullscreen control-plane writes.
- No arbitrary unsandboxed HTML rendering.
- No new document store.

## Automated Validation

Focused browser/runtime tests for layouts, focus, Escape, image pan/zoom, document scroll, unsupported fallback, reduced motion and responsive/200-percent zoom. No full suite.

## Acceptance Criteria

- One and many compatible entries render clearly in the overlay.
- User can switch layouts without changing source/scene state.
- Image zoom/pan and document scroll work without pointer conflicts.
- Focus is trapped/restored correctly.
- Overlay does not claim or mutate true fullscreen state.

## Documentation Updates

Add a concise canonical object-viewer document or the appropriate Control Center UI section, including the explicit fullscreen distinction.

## Handoff Notes

Return the final viewer launch/view-model API to Slice 05. Keep real scene selection semantics out of this module.

