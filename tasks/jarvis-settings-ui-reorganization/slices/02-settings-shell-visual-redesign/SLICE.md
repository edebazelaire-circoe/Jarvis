# Slice 02 - Settings shell and visual redesign

## Goal

Replace the current dense centered modal/top-tab chrome with the new Jarvis Settings shell driven by the six-category registry.

## Context

The user explicitly finds the existing Settings UI unreadable and visually poor. The before-state uses a large bordered modal, narrow text navigation, dense HUD typography and many long technical blocks. The new shell should feel like a first-class Jarvis surface, not a diagnostic panel.

## Canonical Concepts

- `docs/02-architecture.md`
- `references/current-settings-ui.png`
- Slice 01 registry contract

## Scope

### In Scope

- Full-screen or near-full-screen dark Settings surface over the existing blurred Jarvis background.
- Six-category primary navigation with clear identity and spacing.
- Reusable section/card/field/notice typography and spacing primitives.
- Responsive layout and scrolling ownership.
- Accessible close control, Escape behavior, keyboard category navigation and focus return.
- Temporary registry adapters so unmigrated legacy renderers can still mount while later Slices move their contents.

### Out of Scope

- Do not redesign every feature section in this Slice.
- Do not change setting semantics.
- Do not remove legacy aliases yet.

## Dependencies

- `01-settings-registry-ia-contract`

## Implementation Steps

1. Load `/impeccable` and use a Claude Work Agent if supported.
2. Inspect current shell CSS/DOM and existing theme variables.
3. Implement the new Settings frame/background/navigation/content layout.
4. Introduce reusable visual primitives for category intro, sections, field rows, status badges, advanced disclosures and action rows.
5. Mount current sections through the registry/adapters without losing controller cleanup.
6. Preserve outside-click/close semantics only if they still make sense for the new near-full-screen shell; keep Escape and explicit close guaranteed.
7. Add responsive/accessibility tests and screenshot/runtime checks.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- Settings shell/registry module from Slice 01
- Control Center UI tests

## Architecture Constraints

- No new hard-coded setting values.
- Technical monospace styling is not the default for ordinary controls.
- Shell owns navigation/layout; feature modules own their controls.

## Automated Validation

- Six categories render from registry data.
- Keyboard navigation and focus return work.
- No controller/timer survives after its section is destroyed where existing contracts require cleanup.
- Responsive layout has no horizontal overflow at agreed desktop widths and 125% zoom.
- Existing Settings open/close tests updated without weakening behavior coverage.

## Acceptance Criteria

- Old dense top-tab modal is no longer the primary Settings shell.
- All six categories are reachable and identifiable.
- Existing feature settings remain reachable through temporary adapters.

## Documentation Updates

Document the Settings shell primitives and how a feature section should mount into them.

## Handoff Notes

Do not use this Slice to prematurely redesign feature-specific content; later Slices own that work.
