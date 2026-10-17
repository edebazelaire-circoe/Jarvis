# Slice 02 — Shell cleanup and bottom-left Board switcher

## Goal

Remove obsolete permanent controls and make the bottom-left Board card the single everyday Board navigation entry.

## Dependencies

- `01b-derived-interaction-mode` (the mode is no longer user-writable, so removing its HUD removes no capability)

## Slice 00 reconciliation (read first)

HEAD already contains orbital-ui S04-S10, which the planner did not see (`../../docs/08-readiness-audit.md` §3). Concretely:

- The « N objets masqués — afficher » note of `current-ui-before.png` is already gone; it became the **permanent eye `#hiddenEye`** in the bottom-centre status centre. D06 applies to the eye: remove it from the status centre here. Keep its machinery (`showHidden` view pref, ghosts, `openHiddenMenu` / « Tout réafficher ») intact and unexposed until Slice 06 re-exposes it in Sélection — do not delete it.
- The F9 capsule is already gone; the wake-key hint lives on `.state` (`setWakeHint` in `control_center.html`). Removing `.state` must keep the hint reachable: keep `setWakeHint` feeding an accessible, hidden-until-Slice-04 target (or a transient cue), and record in LOG that Slice 04 re-homes it in the JARVIS submenu. Keep the `refreshStatus` gates; delete only the `.state` DOM and its writes.
- The mode HUD is not only a chooser: it shows **Voice's presentation presence report** (`presenceOf`: Voice refused PRESENTATION, microphone failure, deaf session; `docs/interaction-mode.md` › *The live Presentation session*) and it is kept live over Variants during a Studio run (`data-keep-live="run"`, `html.jvx-run`, registry rank 9150 `html.jvx-run #interactionModeHud`) as « the way out of PRESENTATION ». The Variants-run placement is CSS in `control_center_presentation_studio_explorer_core.js:452-460` (`html.jvx-run #interactionModeHud{z-index:9150}`, `html.jvx-run.jvr-studio #interactionModeHud …`, `#presentationRail{bottom:96px}`) plus `JarvisShell.ZONES` (`control_center_shell.js:49`); the reload band (`control_center_presentation_studio_reload.js`) does not reference the HUD, so `docs/presentation-studio.md:3319` (« the band measures `#interactionModeHud` ») is probably stale — verify and fix it. This critical feedback must move, not disappear: the Board card shows the live presence line for a Présentation Board (and during a Studio run), carries `data-keep-live="run"`, and takes over those `jvx-run` rules. The « way out of PRESENTATION » during a run becomes the Studio's own stop/exit (already in the presenter strip / band); do not add a mode toggle.
- Geometry tied to the mode control must be re-derived from the card in the same commit: status-centre side insets (`--shell-gutter + 254px`), `.sc-status` rung (`max(52px, --sc-status-h + 28px)`, Bare Hands badge second rung), `#screenshotPreview` rung, Board drop tray centring, registry rows (`#interactionModeHud .im-btn` 32, `.im-pop` 36, `html.jvx-run #interactionModeHud` 9150), `CONTROL_SELECTOR` table, `JarvisShell.ZONES` (`top-left`, `bottom-left`), and the *Integration matrix (Slice 09)* of `docs/control-center-shell.md`.
- The Board control's create **and edit** flows carry a kind selector with labels `Générique/Réunion/Présentation` (`BOARD_KINDS`, `#boardsCreateKind`); after Slice 01a they become Assistant/Présentation/Réunion on create only (edit keeps title only).
- The launcher row holds `SET` (Réglages). Leave it in place here; Slice 04 folds it into « Plus d’outils » when the wheel's Paramètres goes live.

## Scope / implementation steps

1. Re-read shell zones/layer registry and actual Cosmos/default theme composition.
2. Refactor/move the canonical Board quick control (`control_center_boards.js` or successor) from top-left into a compact bottom-left Board card. Do not create a second Board state client.
3. Card shows active Board type + icon/accent + title, with canonical pending/unavailable states and no optimistic activation.
4. Click opens the Board browser: active/recent/all Boards, create new Board with mandatory type selection, archived browsing where currently supported, new Session only if it belongs to the existing Board control contract.
5. Remove type editing from ordinary Board edit flow. Title rename/archival stay only if still canonical.
6. Favorites are optional: only expose if persistence exists/coheres. Do not block the Slice on inventing favorites.
7. Remove old top-left Board selector host/placement and any duplicate UI after the move.
8. Remove the old bottom-left `interactionModeHud` / SIMPLE-PRESENTATION-REUNION chooser from page composition.
9. Remove the large/legacy interaction-mode panel if still present in current implementation.
10. Remove permanent generic runtime status (`VOICE SLEEP • CLAUDE RUNNING`-style `.state`) from top-left. Preserve critical error/safety alerts through existing dedicated surfaces.
11. Remove the permanent hidden-object eye `#hiddenEye` (successor of the count/toggle) from the status centre. The canonical scene state remains untouched; contextual controls arrive in Slice 06.
12. Update shell zones, layer registry mirror, tokens/safe areas and responsive rules so the scene/right rail regain space.
13. Add explicit DOM/browser assertions that obsolete controls are absent.

## Out of scope

- Wheel visual redesign (Slice 03).
- Capture controls (Slice 04).
- Dossier surface (Slice 07).

## Files likely touched (verified at HEAD 2fb66040)

- `jarvis/runtime/control_center.html` (`.topbar`, `#boardsHud`, `.state`, `#interactionModeHud`, `#hiddenEye` host, status-centre CSS, registry mirror comment, `refreshStatus`)
- `jarvis/runtime/control_center_boards.js` (move to a bottom-left card; kind labels; create-only kind)
- `jarvis/runtime/control_center_interaction_mode.js` (remove from composition; keep/move only the presence-report logic the card needs, or delete the module once its tests are migrated)
- `jarvis/runtime/control_center_scene_page.js` (eye host binding only), `jarvis/runtime/control_center_shell.js` (`ZONES`), `jarvis/runtime/control_center_work.js` (Cosmos skin of the moved surfaces), `jarvis/runtime/control_center_screenshot_preview.js` (rung), `jarvis/runtime/control_center_presentation_studio_explorer.js` / `_explorer_core.js` (keep-live target, `jvx-run` CSS)
- `docs/control-center-shell.md`, `docs/boards.md` › *Control Center Boards control*, `docs/interaction-mode.md` › *The Control Center selector* / *Placement*, `docs/presentation-studio.md` (keep-live and band placement lines)
- tests: `test_boards_hud_js.py`, `test_boards_hud_browser.py` (+ `_boards_browser.mjs`), `test_boards_status.py`, `test_interaction_mode_hud_js.py`, `test_interaction_mode_hud_browser.py` (migrate the presence assertions to the card, delete the chooser ones), `test_control_center_shell_layers.py`, `test_control_center_shell_browser.py`, `test_global_launcher_browser.py`, `test_status_centre_browser.py` (+ `_status_centre_browser.mjs`), `test_scene_renderer_logic.py`, `test_screenshot_preview_browser.py`, `test_variants_run_browser.py`, `test_variants_run_surface_docs.py`, `test_barehands_contracts_js.py`, `test_control_center_mvp.py`, `test_capture_rail_js.py` (eye references)

## Architecture constraints

- Server/Core remains Board truth.
- Moving the control must not change switch transaction semantics, timeouts or one-speech-authority behaviour.
- Delete obsolete hosts/listeners rather than hiding duplicated controls with CSS alone.
- Update layer registry and accessibility membership in the same commit.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation`
- `/impeccable`, `/caveman`, `/coding-guideline`
- focused Board HUD/shell browser tests + responsive screenshots

## Acceptance criteria

- Bottom-left card is the only everyday Board switcher.
- Active type/title are clear.
- New Board flow asks for type and does not later offer type edit.
- Old top-left Board control is gone.
- Old interaction-mode controls are gone.
- Permanent hidden-object chip is gone.
- Permanent generic Voice/Claude status badge is gone.
- Scene/right rail do not collide with new bottom-left card at tested viewport sizes.

## Documentation updates

Update `docs/control-center-shell.md`, `docs/boards.md` UI section and any operator docs/screenshots that name the old control locations.
