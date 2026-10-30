# Jarvis - Mouse Organization and Object Viewer

**Project:** Jarvis  
**Task type:** Feature  
**Repository:** `edebazelaire-circoe/Jarvis`  
**Source branch:** `main`  
**Planning baseline:** `c0858a8000e2ca23b57231edb8f46c643080ad07` (2026-10-29)  
**Drive destination:** `Jarvis/task/to-do/jarvis-mouse-organization-viewer/`  
**Initial status:** planning handoff created; implementation is blocked until Slice 00 returns `READY`.

## Goal

Make Jarvis comfortable to operate with ordinary mouse and keyboard interactions without making Voice or Bare Hands mandatory. The feature has three tightly related product outcomes:

1. direct desktop manipulation that feels conventional: reliable multi-selection, context actions, 8-way resize, aspect-ratio lock, group organization, and bounded undo;
2. a first-class in-app object viewer opened by double-click or Enter, including multi-document comparison layouts;
3. an agent/task detail viewer using the same fullscreen overlay shell, showing public execution state, mission, progress, current activity, visible steps, findings and artifacts, with explicit Stop / Ask actions when canonical runtime routes support them.

The viewer is an **in-app viewport overlay**, not a replacement for the existing browser Fullscreen API contract used by presentation surfaces.

## Product contract

### Mouse and keyboard

- Preserve existing click, Ctrl/Cmd-click multi-selection, selection rectangle and group drag.
- Right-click on an object that already belongs to a multi-selection preserves that selection and opens actions for the full group.
- Windows/capsules that are resizable can resize from four edges and four corners.
- Resize hit areas may be wider than their visual border. The visible border remains thin and unobtrusive.
- Holding Shift during resize preserves the object's starting aspect ratio.
- Enter opens the selected object(s) in the viewer when they are viewable.
- Escape closes the viewer/menu or cancels the active interaction without changing Board geometry.
- Ctrl/Cmd+A may select all scene objects only when focus is not inside an editable control.
- Ctrl/Cmd+Z provides a short-lived, geometry-only undo path for user organization/resize operations. It is not durable history and must not overwrite a target that changed after the recorded operation.
- Existing Delete, `-`, Ctrl/Cmd-click, Shift+Arrow and Ctrl+Arrow behavior remains compatible.

### Organization actions

For a multi-selection, expose conventional layout actions from the context menu:

- Row / horizontal line
- Column / vertical line
- Auto grid
- Custom grid N x M, with a small graphical picker and numeric fallback
- Align left / center / right / top / middle / bottom
- Distribute horizontally / vertically
- Same width / same height / same size

Layout order is deterministic and based on current visual spatial order. Layouts stay around the current selection rather than jumping to an unrelated part of the Board. Arbitrary multi-object geometry updates are atomic: one user action must result in one all-or-nothing Core mutation, not N independent writes.

### Multi-object viewer

- Double-click opens an object in a large viewer.
- If the double-clicked viewable object belongs to a compatible multi-selection, open the compatible selected set.
- Enter opens the current compatible selection.
- Context menu exposes an explicit Open/View action.
- Closing the viewer restores the Board exactly as it was: selection and geometry are not rewritten simply because the viewer was opened.
- Supported layouts include single, horizontal pair, vertical pair, 2x2, row, column, auto grid, custom grid, and a small number of asymmetric presets such as large-left/small-right and large-top/small-bottom.
- Images support zoom and pan. Scrollable documents retain document scrolling.
- Viewer layout state is transient in this task. Saving a viewer composition, exporting a contact sheet, or replacing source artifacts is out of scope.

### Agent viewer

Double-clicking an execution agent opens the same dark fullscreen overlay shell, but with an execution-oriented projection:

- mission / objective;
- role and live status;
- elapsed runtime from canonical timestamps;
- current public activity;
- progress when provided by Work State;
- a concise public step list: done / current / planned where structured public progress exists, otherwise a truthful degraded view from actual child work / mission facts;
- recent public findings or summary notes, never private reasoning or chain-of-thought;
- produced/related artifacts, openable in the object viewer;
- Stop action through the canonical cancellation path;
- Ask action through an existing canonical communication/chat path. If no direct agent-question route exists, prefill/route a question through the main chat with the target identity rather than inventing a second control plane.

## Existing implementation to reuse

The planning audit found important reusable foundations on current `main`:

- `docs/scene-selection-batch.md` and the scene batch reducer already provide atomic selection semantics.
- `control_center_scene_interact.js` already has `resizeBySides()` for left/right/top/bottom manipulation, while mouse resize is still explicitly bottom-right only through `resizeBox()`.
- `control_center_scene_page.js` already implements multi-selection, selection-band, carrying selected objects during drag, keyboard movement/resize, Delete and hide. Its current `onContextMenu()` calls `select(id)` and therefore collapses multi-selection.
- Work State already exposes bounded public status, current activity, summary, progress fraction, timestamps, counters and role identity.
- Mission History already exposes mission objective, agent instances, roles, mission hierarchy and relations, joined to live Work State.
- Scene/artifact relations already provide the durable link between execution objects and produced artifacts.
- `surface_fullscreen.py` owns true browser `requestFullscreen()` semantics. This viewer must not reuse that state machine for a normal in-app lightbox/overlay.
- The active `jarvis-scene-window-prefab-foundation` task owns generic prefab/window runtime. This feature consumes that substrate rather than creating a second one.
- The active `jarvis-interactive-presentation-studio` task owns presentation fullscreen and variant-explorer behavior. This feature must remain compatible with it.
- The active `jarvis-unified-chat-and-board-drop` task may touch shared Control Center/chat entry points; Slice 00 must re-audit conflicts before dispatch.

## Explicit non-goals

- Capsule/minimized-card representation redesign.
- Appearance setting for hiding stars.
- Systematic end-of-agent report artifact generation.
- Persistent container/group object redesign.
- Saving viewer layouts as artifacts or exporting contact sheets.
- Replacing presentation fullscreen behavior.
- Reworking Board/Session/Context ownership.
- Creating a parallel scene renderer, prefab runtime, work-state owner, mission-history owner, or agent communication channel.

## Execution graph

Start with `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md` itself. No implementation dispatch before `READY`.

After readiness, the expected parallel-ready set is:

- `01-atomic-layout-and-undo-contract`
- `02-mouse-resize-selection-input`
- `03-multi-object-viewer-shell`
- `04-agent-viewer-projection`

Then `05-scene-integration-organize-viewer` converges the UI and contracts, followed by `06-final-integration-e2e-qa`.

Every coding Slice loads `/caveman` and `/coding-guideline`. Every frontend Slice additionally loads `/impeccable` and uses the configured frontend Work Agent routing when available.

