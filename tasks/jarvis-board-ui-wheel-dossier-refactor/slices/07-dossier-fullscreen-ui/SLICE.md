# Slice 07 — Full-screen Dossier workspace and Jarvis-guided navigation

## Goal

Deliver the human-facing full-screen Dossier interface: organized browsing on the left, serious document/media work in the centre, optional context/provenance on the right, and manual + Jarvis-guided navigation over the same state.

## Dependencies

- `05-dossier-contract-projection`
- `06-selection-object-actions`

## Scope / implementation steps

1. Load `/impeccable` and design the screen against `../../docs/06-ui-visual-spec.md` before writing final DOM/CSS.
2. Dossier opens from the wheel as a full workspace overlay/surface associated with the active Board. Show Board type/title clearly; provide explicit close/back-to-Board.
3. Left organization pane: human-readable folder/collection tree, recent/useful sections as justified, local Dossier search/filter, loading/empty/error states.
4. Centre workspace: text/document viewer/editor where authorized; images/media/PDF using safe preview routes; tabs or panes for multiple opened entries; side-by-side comparison on large screens; fall back to tabs on narrow screens.
5. Right contextual pane: summary, source/provenance, modified time, linked work/artifacts and contextual actions. It is collapsible and not the default visual focus.
6. Advanced Jarvis/memory/log/ID details live behind an explicit disclosure, never as the Dossier home screen.
7. Provide actions `Afficher sur le Board`, representation choice, edit/annotate if supported, move/rename inside Board memory where canonical operations allow it.
8. Preserve archived Board read-only behaviour and explicit write refusals.
9. Implement UI command seam so Jarvis/agent results can open/focus the same Dossier entries/panes in response to spoken/text commands. Manual navigation and voice navigation update the same view state.
10. Example supported intents (through canonical tool/service path): show a named report, show multiple sources explaining a decision, summarize changes, open a resource, present selected documents back on Board.
11. Do not pretend Jarvis “used/read” an entry unless the backend provides that truth. Distinguish “available to Jarvis” from “retrieved in this turn” if such telemetry exists.
12. Implement focus trap/restore, Escape/back semantics, keyboard navigation, screen-reader labels and responsive collapse of side panes.
13. Add screenshots/evidence from actual runtime, not generated concept art.

## Out of scope

- General OS filesystem browser.
- New office/PDF editing engine beyond supported formats/actions.
- Replacing the technical Workspace manager if it remains useful for diagnostics.
- Generic web research browser as a Dossier tab.

## Files likely touched (verified at HEAD 2fb66040)

New focused `jarvis/runtime/control_center_dossier*.js` module(s) served like the other modules (see how `ControlCenter.index` serves `TOOL_WHEEL_SCRIPT_FILE` in `jarvis/runtime/control_center.py`); a full-screen layer next to the existing rank-55 views (`.wsp`, `.tl`, `.tlab`, `.mcpi`, `.pfb`) in the registry of `docs/control-center-shell.md` and its mirror in `control_center.html`; a Dossier client over the Slice 05 relay routes; reuse of the read/preview helpers of `jarvis/runtime/control_center_workspace.js` (memory pages, artifact previews) without exposing its technical UI; the agent -> UI seam modelled on the Studio explorer channel that opens Variants on a voice-started run (`control_center_presentation_studio_explorer*.js`). Tests: new `test_dossier_*_js.py` / `test_dossier_*_browser.py`, `test_control_center_shell_layers.py`, `test_control_center_shell_browser.py`, `test_workspace_manager_browser.py` (no regression of the technical manager).

## Architecture constraints

- Dossier view-model comes from canonical Dossier service, not direct arbitrary file reads.
- No duplicate storage.
- Board switch while Dossier is open must either rebind cleanly to the new Board or close/ask according to a documented policy; never show Board A title with Board B content.
- User edits are server-confirmed; unknown/conflict states visible.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation`
- `agent-trace-analysis` for voice/tool-driven open/search/present flows
- `/impeccable`, `/caveman`, `/coding-guideline`
- browser tests with large trees, long docs, images/media, multiple tabs, archived Board, Core unavailable, narrow viewport

## Acceptance criteria

- Dossier feels like a polished document workspace, not a debug manager.
- Human can browse, read, compare and correct Board documents/media.
- Jarvis can navigate/open requested Dossier material through the same UI semantics.
- Multiple requested documents can be shown together where screen permits.
- `Afficher sur le Board` creates a representation without cloning canonical content.
- Human-readable view is default; technical memory/provenance is available but secondary.
- Closing Dossier returns cleanly to Board with focus restored.

## Documentation updates

Canonical Dossier UI/tool docs, shell layer registry, operator docs, accessibility notes and screenshots/evidence index.
