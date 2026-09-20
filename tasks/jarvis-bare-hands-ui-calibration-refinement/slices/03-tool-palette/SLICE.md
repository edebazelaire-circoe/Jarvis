# Slice 03 — Move existing tools into a fixed left palette

## Goal

Make the already-implemented Bare Hands tools selectable in one click from the main screen.

## Context

The current tool radio buttons live in Settings even though they change current interaction intent. The user wants a small Paint/Photoshop-style vertical icon bar, fixed on the left for this version.

## Canonical Concepts

- `TOOL`, `TOOLS`, `INSTALLED_TOOLS`, `describeTools()` and capability gating
- canonical current tool setting/state
- existing `pointer`, `pan`, `select` interaction semantics

## Scope

### In Scope

- Create a fixed vertical Bare Hands tool palette on the left side of the main UI.
- Populate it from the canonical installed tool description, expected at reviewed snapshot to be `pointer`, `pan`, `select`.
- Use clear icons/tooltips and a strong active-tool state.
- One click selects a tool through the existing canonical tool API/state.
- External tool changes update the palette.
- Hide/collapse behavior may follow current Bare Hands availability, but do not make the palette dependent on Settings being open.

### Out of Scope

- New tools (no highlighter/draw/eraser).
- Movable/dockable/horizontal palette.
- Redefining what pointer/pan/select do.

## Dependencies

01, 02

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use Claude routing when supported.
2. Freshness-check the canonical tool contract and currently installed tools.
3. Build palette rendering from canonical descriptions rather than hard-coding a divergent tool list where avoidable.
4. Choose simple icons consistent with Jarvis HUD language.
5. Wire selection to existing Bare Hands tool state.
6. Add synchronization, keyboard/focus and unavailable-state behavior.
7. Add tests proving Settings no longer owns the palette.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_barehands.js`
- possibly a small dedicated tool-palette module/style section
- `control_center_barehands_contracts.js` only if presentation metadata legitimately belongs there
- tool/settings UI tests

## Architecture Constraints

- Canonical tool semantics and capability gating remain untouched.
- The palette must never imply an uninstalled tool is usable.
- Tool choice is session intent, not lifecycle.

## Automated Validation

- Palette exposes exactly installed tools.
- Selection uses canonical state and is bidirectionally synchronized.
- Pointer remains default where current settings/profile say so.
- Future uninstalled tools cannot appear as enabled controls accidentally.
- Tool keyboard navigation/focus behavior works.

## Acceptance Criteria

- Pointer/Pan/Select are visible and switchable without opening Settings.
- No new tool behavior was introduced.
- Active tool is immediately understandable.

## Documentation Updates

Document the fixed left palette as the canonical V1 tool-selection surface.

## Handoff Notes

Baseline `qa-verification`, `code-review`, and `runtime-validation` are required.
