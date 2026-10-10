# Slice 18 - Fullscreen Variant Explorer

## Goal
Build the designed fullscreen UI for browsing the creative evolution of a presentation.

## Context
The user explicitly imagines a dark blurred full-screen explorer with the branch tree on the left and rich presentation preview on the right.

## Canonical Concepts
Variant tree, selected node, preview, active branch, context actions, voice/UI parity.

## Scope
### In Scope
- Fullscreen dark/blurred variant workspace.
- Navigable branch tree.
- Selected variant metadata/title/short ID.
- Rich preview with scene browsing.
- Activate/branch/rename/delete actions.
- Entry from voice and graphical affordances such as context menu.

### Out of Scope
- Multi-variant compare mode (next Slice).
- General project/file browser.

## Dependencies
- `16-presentation-variants-domain`
- `17-scene-local-variants`
- `03-fullscreen-borderless-surface`

## Implementation Steps
1. Design information hierarchy and keyboard/mouse navigation.
2. Render graph without becoming unreadable for realistic branch counts.
3. Wire actions through canonical variant operations.
4. Integrate preview renderer without mutating variants.
5. Add entry/exit and focus restore.

## Files Likely Touched
Presentation/Control Center frontend and UI tests.

## Architecture Constraints
The UI visualizes the canonical variant graph; it is not the source of truth.

## Automated Validation
Component/state tests, selection/preview, context actions, keyboard navigation, branch deletion confirmation, fullscreen entry/restore.

## Acceptance Criteria
A user can understand how the project evolved and choose a branch visually without reading raw version metadata.

## Documentation Updates
Variant Explorer interaction contract.

## Handoff Notes
Frontend Slice: `/caveman`, `/coding-guideline`, `/impeccable`, Claude when supported.
