# Slice 03 — Orbital wheel IA and graphic redesign

## Goal

Transform the existing four-action orbital wheel into the five-category Jarvis control wheel, with a materially updated visual style based on `../../assets/style-reference-radial-ui.png` and one contextual submenu at a time.

## Dependencies

- `02-shell-cleanup-board-switcher`

## Canonical context

Preserve mature input behaviour of the existing wheel where valid: left-edge reveal, mouse/pointer, keyboard and Bare Hands synthesized click/context interactions, escape/outside close, no network round-trip for reveal. Replace its product IA and graphics.

## Scope / implementation steps

1. Load `/impeccable` and audit current wheel geometry/reducer/browser tests before changing markup.
2. Replace primary slot model with exactly: `jarvis`, `selection`, `dossier`, `capture`, `settings`, with French labels JARVIS / Sélection / Dossier / Capture / Paramètres.
3. Remove first-level `video`, `screenshot`, `audio`; Capture handlers migrate in Slice 04.
4. Do not add first-level `boards`, `files/fichiers`, `search/recherche`, `tools/outils`.
5. Implement a single contextual submenu state: activating/focusing/selecting a category opens its second radial/curved layer; selecting another category replaces the previous subtree; close removes it. Do not mount two visible category panels simultaneously.
6. Preserve nested submenus where a category genuinely needs target/device/action depth, but navigation remains within the **single selected category tree**.
7. Redesign geometry/skin toward the reference: layered semi-circle, selected sector integrated with adjacent curved glass submenu, thin cyan lines, restrained glow, dark translucent panels, consistent line icons and typography. See `../../docs/06-ui-visual-spec.md`.
8. Keep the closed state unobtrusive and the scene usable. The graphic redesign may adjust radius/sector composition, but must respect responsive safe areas.
9. Preserve/repair keyboard navigation, focus restoration, Bare Hands click dedupe, reduced motion and forced-colour readability.
10. Register placeholder/injected category handlers rather than faking actions; Slice 04/05/06 wire semantics.
11. Update shell design tokens/layer tests when geometry changes.
12. Capture actual runtime screenshots for closed/open/JARVIS/Dossier/Capture states.

## Out of scope

- Implementing fake Jarvis thinking states.
- Implementing Dossier persistence.
- Rewriting capture ownership.
- Copying every decorative feature from the generated reference.

## Files likely touched

- `jarvis/runtime/control_center_tool_wheel.js`
- `jarvis/runtime/control_center.html` tokens/host if needed
- theme/shell CSS modules
- tool-wheel unit/browser tests
- `docs/control-center-shell.md`

## Architecture constraints

- Wheel reveal stays local/instant.
- Semantic actions remain injected; the wheel does not become a new domain owner.
- One visible submenu category tree maximum.
- Current canonical state controls must not be duplicated locally.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation`
- `/impeccable`, `/caveman`, `/coding-guideline`
- pure reducer tests + real browser tests for mouse/keyboard/Bare Hands paths
- responsive/reduced-motion/forced-colour checks

## Acceptance criteria

- The wheel visually reads as a redesigned layered radial system, not the old wheel with renamed labels.
- Exactly five primary categories exist in locked order.
- Reference-style visual language is recognisable without literal copying.
- At most one contextual category submenu is visible.
- Switching category replaces previous submenu cleanly.
- Mouse, keyboard and Bare Hands still activate the same semantic path without double-fire.
- Closed wheel remains unobtrusive.

## Documentation updates

Update shell/wheel contract and visual evidence. Document any geometry token changes.
