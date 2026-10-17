# Slice 02 — Shell cleanup and bottom-left Board switcher

## Goal

Remove obsolete permanent controls and make the bottom-left Board card the single everyday Board navigation entry.

## Dependencies

- `01-board-type-contract-migration`

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
11. Remove permanent hidden-object count/toggle from shell. The canonical scene state remains untouched; contextual controls arrive in Slice 06.
12. Update shell zones, layer registry mirror, tokens/safe areas and responsive rules so the scene/right rail regain space.
13. Add explicit DOM/browser assertions that obsolete controls are absent.

## Out of scope

- Wheel visual redesign (Slice 03).
- Capture controls (Slice 04).
- Dossier surface (Slice 07).

## Files likely touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_boards.js`
- `jarvis/runtime/control_center_interaction_mode.js` (retire from composition/remove when safe)
- shell/theme modules and tests
- `docs/control-center-shell.md`, `docs/boards.md`

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
