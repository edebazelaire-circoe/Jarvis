# Slice 03 — Orbital wheel IA and graphic redesign

## Goal

Transform the existing four-action orbital wheel into the five-category Jarvis control wheel, with a materially updated visual style based on `../../assets/style-reference-radial-ui.png` and one contextual submenu at a time.

## Dependencies

- `02-shell-cleanup-board-switcher`

## Slice 00 reconciliation (read first)

Reducer verdict (step 8 of Slice 00): **preserve** the pure `reduce` / `initialState` / `viewOf`, `register` / `setStatus`, the activation rules (primary = `click` only, Bare Hands `pointerId` 9001-9002 attribution, keyboard secondary dedupe 500 ms, close reasons, 400 ms leave grace) and the radial sub-arc + second level, which already replaces the first level **in place** (one visible subtree). Replace: `SLOTS` (4 → 5 categories), the geometry (`layoutWedges`, `sectorPolygon`, 156°/39° wedges, radius tokens `--shell-wheel-r` 200 px, sub-arc radius 236 px / 15°), the skin, and label visibility (today only the hovered wedge shows a label pill; the 5 categories need readable labels when open). `menu:true` already makes a primary activation open the category tree — use it for every category that has a tree.

Current registrations to migrate: Sélection in `control_center_input_arbitration.js` (`register({id:'selection', menu:true})`), Vidéo / Capture d'écran / Audio in `control_center_capture_wheel.js` (slot ids `video`, `screenshot`, `audio`; capture semantics move in Slice 04 — in this Slice keep them reachable under the `capture` category tree so no intermediate commit loses capture). JARVIS / Dossier / Paramètres get injected placeholder handlers (`tool_wheel.unbound` notification), wired by Slices 04/05-07/04.

Contract to update: `docs/control-center-shell.md` › *Tool wheel* (« Exactly four primary wedges … Sélection, Vidéo, Capture d'écran, Audio »), *Layer registry* (`#toolWheel`, `#toolWheel[data-open]`), *Integration matrix*, *Tokens*; `docs/capture.md` › *Interface* when the wedges move.

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

## Files likely touched (verified at HEAD 2fb66040)

- `jarvis/runtime/control_center_tool_wheel.js` (`SLOTS`, geometry, skin, labels, `ART` icons)
- `jarvis/runtime/control_center_input_arbitration.js`, `jarvis/runtime/control_center_capture_wheel.js` (registrations only)
- `jarvis/runtime/control_center.html` (tokens `--shell-wheel-r`, `--shell-anchor-w`, `--shell-wedge-min`, host, registry mirror), `jarvis/runtime/control_center_work.js` (Cosmos skin), `jarvis/runtime/control_center_shell.js` if tokens are mirrored
- `docs/control-center-shell.md`, `docs/capture.md` › *Interface*
- tests: `test_tool_wheel_js.py`, `test_tool_wheel_browser.py`, `test_selection_method_browser.py`, `test_capture_wheel_browser.py` (+ `_capture_wheel_browser.mjs`), `test_control_center_shell_layers.py`, `test_control_center_shell_browser.py`, `test_screenshot_preview_browser.py` (preview steps right of the open wheel's radius)

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
