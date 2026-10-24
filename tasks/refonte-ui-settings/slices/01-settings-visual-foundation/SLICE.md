# Slice 01 — Settings visual foundation

## Goal

Establish the reusable visual primitives, spacing/layout rules and screenshot harness needed for the five reference-driven page refactors without rewriting page-specific content.

## Context

All target pages share a recognizable Jarvis visual language: dark translucent panels, thin cyan/blue borders, selective purple accents, circular neon icons, disciplined grids, clear tabs, compact control rows and a blurred scene background. Implement this once where the repository architecture supports reuse.

## Canonical Concepts

- `docs/02-architecture.md`
- `docs/06-visual-contract.md`
- all files in `references/ui/`
- current Settings shell/registry from the live repository

## Scope

### In Scope

- Audit and refine existing Settings tokens/components before creating new ones.
- Shared glass panel, border/glow, typography, spacing and grid primitives.
- Shared tabs/segmented control visual treatment.
- Shared icon medallion, stat tile, labeled row, status badge/dot, button, select, slider, switch and textarea styling.
- Shared dense-table shell and floating-panel primitives where reusable.
- Layering/z-index/focus-ring conventions for dropdowns and floating configuration panels.
- Responsive layout utilities for 3-column, 2-column, single-column and dense workbench layouts.
- Deterministic fixture/state hooks and screenshot capture helpers for page visual tests.
- Visual documentation for future Settings sections.

### Out of Scope

- Do not fully redesign any of the five target pages in this Slice.
- Do not change setting semantics, backend ranges, role registries or provider catalogs.
- Do not create a new design framework if current CSS/components can be extended cleanly.

## Dependencies

- `00-project-manager`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline` and `/impeccable`; use a Claude Work Agent when supported.
2. Inspect the current Settings DOM/component boundaries, CSS variables, reusable controls and screenshot/E2E tooling.
3. Produce a small before-state screenshot set for the five target routes/views when currently reachable.
4. Consolidate visual tokens for background, glass opacity, border/glow intensity, radius, spacing, type scale, muted text and semantic accents.
5. Implement/refine reusable primitives using existing architecture conventions.
6. Add responsive grid/layout utilities with explicit overflow ownership; no accidental page-wide horizontal scroll.
7. Ensure hover/focus/pressed/disabled/loading states are represented for reusable controls.
8. Add deterministic visual fixture hooks so later Slices can render stable reference states without hard-coding production data.
9. Add or extend screenshot tooling to capture the reference viewport sizes and one narrower viewport.
10. Document how page Slices should consume the primitives and where page-specific CSS is permitted.

## Files Likely Touched

Resolve exact paths during Slice 00. Likely areas include the Settings shell HTML/components, shared Settings CSS/theme tokens, reusable control modules and UI/E2E screenshot tests.

## Architecture Constraints

- Shared primitives own presentation, not business state.
- Existing controllers/runtime APIs remain authoritative.
- No browser-only duplicate catalog of models/providers/roles/settings ranges.
- Do not hard-code mockup data into reusable components.

## Automated Validation

- Existing Settings routes still mount/unmount without leaked listeners/controllers.
- Shared controls expose visible focus state and disabled state.
- Representative 3-column and 2-column layouts have no horizontal overflow at target widths and 125% zoom.
- Screenshot harness can capture deterministic fixtures at `1672x941` and `1254x1254`.
- Existing build/lint/type/test gates for touched frontend code pass.

## Acceptance Criteria

- Later page Slices can implement their references without duplicating the same glass/tabs/control styling.
- The foundation visibly matches the common language of all five references.
- No page-specific content has been prematurely frozen into the shared layer.

## Documentation Updates

Document visual tokens/primitives and screenshot fixture conventions in the repository's appropriate frontend/settings documentation.

## Handoff Notes

If current code already has equivalent primitives, prefer refinement and consolidation over replacement.
