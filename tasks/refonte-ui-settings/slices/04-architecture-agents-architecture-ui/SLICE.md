# Slice 04 — Architecture & Agents / Architecture UI refactor

## Goal

Refactor the **Architecture** tab into the supplied operational graph workspace: top status/rules/actions, a dominant semantic graph canvas, contextual floating brain configuration, journal and connection legend.

## Context

Reference: `references/ui/03-architecture-agents-architecture.png`.

The existing Architecture task establishes that the graph is operational, directional and typed; node movement is layout-only; required links are locked; brain configuration is contextual rather than a standalone page.

## Canonical Concepts

- `REFERENCE.md`
- current architecture graph/runtime contract
- current brain configuration contract
- existing Architecture & Agents task decisions

## Scope

### In Scope

- Top `État du système`, `Règles d’architecture` and `Actions rapides` cards, populated from live state/capabilities.
- Large graph canvas with visual node categories for audio I/O, brains, system/infrastructure context and optional future nodes.
- Directional request/response/optional/locked connection styles with legend.
- Node active/degraded/disabled/locked states.
- Draggable node layout persistence without mutating runtime semantics.
- Context action on configurable brain nodes opening the floating/draggable configuration panel.
- Floating brain panel styling/layout matching the reference family while rendering canonical fields: model/provider, mission, instructions, delegation tendency and supported advanced entry points.
- Architecture journal/event list when live event data exists; otherwise preserve the same lower-panel structure with an honest empty state.
- Quick actions only when backed by real actions (reset/load/save preset or current equivalents).
- Loading/error/partial graph/degraded runtime states.

### Out of Scope

- Do not fake future brain nodes into the default graph.
- Do not allow locked infrastructure links to be edited.
- Do not create a standalone Brains tab/page.
- Do not make node position changes alter runtime routing.

## Dependencies

- `01-settings-visual-foundation`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent when supported.
2. Capture current Architecture tab before-state and inspect graph/popup runtime adapters.
3. Recompose the top status/rules/actions region with live state and concise descriptions.
4. Refactor graph node visuals to the reference: luminous icon medallions, strong labels, concise responsibility bullets/status and clear port/connection affordances.
5. Refactor edges with typed color/style semantics and visible direction arrows; ensure locked/optional/disabled styles remain distinct at a glance.
6. Preserve drag-to-layout behavior and saved layout semantics; clamp/reflow nodes so labels and edges remain legible after resize.
7. Refactor the contextual brain configuration panel to visually match the reference overlay while preserving all canonical fields, validation and apply/cancel semantics.
8. Ensure popup stacking does not break tabs, dropdowns or keyboard focus; support Escape and predictable focus return.
9. Recompose journal and legend panels at the bottom and keep graph canvas scroll/zoom/pan ownership clear.
10. Validate graph at 1254×1254 and a wider desktop viewport, including long node names and degraded links.
11. Capture final screenshot with a brain panel open in a deterministic fixture state.

## Files Likely Touched

Resolve exact paths during Slice 00. Expect architecture canvas renderer/styles, brain popup, graph layout persistence glue, Settings page composition and targeted graph/UI tests.

## Architecture Constraints

- Graph runtime remains source of truth for nodes, ports, connections and mutability.
- Required connections are visibly locked and cannot be disabled.
- Node drag changes layout only.
- Brain panel does not choose exact specialized role/model routing that belongs to global sub-agent configuration.

## Automated Validation

- Live graph nodes/edges render with correct direction/type/mutability state.
- Locked links reject mutation in the UI.
- Node layout persistence changes coordinates only.
- Context brain panel opens/closes/applies/cancels with keyboard and mouse.
- Graph remains usable after resize and at 125% zoom.
- Screenshot regression captures the deterministic graph with the brain panel open.

## Acceptance Criteria

- The Architecture workspace is immediately recognizable as the supplied graph reference.
- The graph still represents actual runtime architecture, not decorative sample nodes.
- The contextual brain configuration panel is polished, draggable where supported and clearly connected to the selected node.

## Documentation Updates

Document graph visual semantics (request/response/optional/locked), node status visuals and popup interaction rules.

## Handoff Notes

The screenshot is a composition target; runtime topology remains canonical.
