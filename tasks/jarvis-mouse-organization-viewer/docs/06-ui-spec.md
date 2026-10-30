# 06 - UI Specification

## Visual direction

The viewer should feel like a large focused Jarvis inspection surface, not a conventional desktop modal.

- full viewport overlay;
- near-black background with a restrained blur/translucency over the Board;
- generous spacing between content regions;
- thin borders and restrained cyan/blue emphasis compatible with the current settings language;
- semantic warning/error colors only where state requires them;
- sparse top-level controls;
- no dense telemetry wall.

The existing Settings visual language is a useful reference for spacing, cards, typography and controls, but the viewer is more spacious than Settings.

## Viewer shell

Suggested zones:

1. top-left: title/type and optional selection count;
2. top-center or compact toolbar: layout chooser when multiple items are open;
3. top-right: close and a small number of content-specific actions;
4. center: one or more viewer slots with generous gutters;
5. optional bottom status: zoom percentage / skipped-item notice / lightweight navigation.

### Layout picker

Presets should be represented visually, not only as text. Custom grid offers:

- hover/click mini-grid for common dimensions;
- explicit rows and columns inputs for larger dimensions;
- immediate preview without scene mutation.

### Image slot

- fit-to-view default;
- zoom in/out/reset;
- wheel/pinch or explicit controls as supported;
- pan only when zoomed beyond fit;
- image remains visually dominant; metadata is secondary.

### Document slot

- content scrolls inside its slot;
- avoid thick Jarvis window chrome inside the viewer;
- preserve readable margins and document controls only when useful.

## Agent viewer shell

Use the same overlay frame but a different content template. Recommended hierarchy:

### Header

- agent/role name;
- live state;
- mission title/objective;
- elapsed time;
- Stop and Ask controls.

### Current work

One prominent card containing current public activity and progress. If progress fraction is absent, do not invent a percentage.

### Plan / steps

A concise vertical list with semantic states:

- done;
- current;
- planned;
- blocked when canonical state says so.

Only render planned future steps when an explicit public plan source exists. Otherwise show actual completed/current children and a low-key `No published plan` state.

### Findings

A few bounded public summaries or findings. This is not a log stream and not hidden reasoning.

### Artifacts

Visual cards/thumbnails for produced or related artifacts. Clicking opens them in the object viewer without losing the ability to return to the agent viewer. The integration Slice may use a nested viewer history or a simple back action; it must remain deterministic and keyboard accessible.

## Scene border / resize affordances

- visual border target: approximately 1 px in the current theme language;
- pointer hit zone can extend several pixels inward/outward;
- cursors identify horizontal, vertical and diagonal resize regions;
- hit regions must not cover meaningful inner buttons/links;
- selected state can strengthen the outline without consuming large content area.

