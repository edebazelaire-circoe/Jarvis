# Slice 06 — Selection and Board-object actions

## Goal

Make Sélection the contextual manipulation entry for Board scene objects, with clear non-destructive vs destructive semantics and no permanent hidden-object junk UI.

## Dependencies

- `05-dossier-contract-projection`
- `04-jarvis-runtime-capture-controls` (added by Slice 00: both Slices register wheel entries and edit `control_center.html`; serialize them)

## Slice 00 reconciliation (read first)

Confirmed at HEAD (`../../docs/08-readiness-audit.md` §7): hidden = active + not rendered + recoverable; archived = out of the active scene with tombstone; batch ops `patch_selection {visibility, representation}`, `archive_selection`, `archive_many` (orphan scene artifacts only, `not_bulk_archivable` otherwise), MCP hide guard (`display_mcp.py`). No third disposition.

"Afficher les masqués (N)" already exists as machinery from orbital-ui S06, whose eye Slice 02 removed from the shell: the browser view pref `showHidden` (`control_center_scene_view.js`, ghosts at stored geometry, "Réafficher" = one `set_visibility visible`) and the hidden list `openHiddenMenu` with "Tout réafficher" (`control_center_scene_page.js`). Re-expose both inside the Sélection tree with the count in the entry label; do not rewrite ghost rendering. Keep the distinction: the ghost view never rewrites `visibility`; "Tout réafficher" does (canonical).

## Scope / implementation steps

1. Reuse current selection input arbitration (Mouse / Bare Hands where supported) and canonical `SceneSelection` resolution.
2. After objects are selected, expose applicable actions in the selected Sélection category tree. Hide/disable actions that make no semantic sense for the current selection rather than always showing a generic list.
3. Wire `Masquer` to canonical atomic `visibility=hidden` selection update.
4. Wire `Afficher` / global `Afficher les masqués (N)` to canonical selection-by-visibility update; count is contextual in the menu, never permanent shell chrome.
5. Wire visual representation commands to canonical `point`/`capsule`/`window` (user labels may be Étoile/Réduire/Fenêtre after UI review).
6. Wire `Retirer du Board` to canonical scene archive/removal semantics; make clear this removes the representation, not the durable document.
7. Wire `Ranger dans le Dossier` through Slice 05 Dossier durability semantics **first**, then archive/remove the successful representations. If Dossier persistence fails/refuses, leave representation intact and explain why.
8. If destructive durable content deletion is offered, name it explicitly and use the existing confirmation policy; never overload “Retirer du Board”.
9. Preserve scene authority, pins, archive tombstones and atomic batch/refusal behaviour.
10. Ensure voice/agent “masque ça”, “range ça”, “réduis-les”, “mets-les en étoiles”, “affiche les masqués” route to the same semantic operations where the current tool architecture supports them.
11. Add multi-selection and mixed-eligibility tests. Avoid partial data loss; a batch may report per-item Dossier ineligibility before scene archive.

## Out of scope

- Automatically archiving tasks because they are complete (follow-up Issue).
- Creating a new scene disposition called `stored` or `dossier`.

## Files likely touched (verified at HEAD 2fb66040)

- `jarvis/runtime/control_center_input_arbitration.js` (Sélection tree), `jarvis/runtime/control_center_tool_wheel.js` (registrations only)
- `jarvis/runtime/control_center_scene_page.js` (selection -> batch commands, hidden list), `jarvis/runtime/control_center_scene_view.js` (`showHidden`), `jarvis/runtime/control_center_scene_layout.js` (ghosts, unchanged unless needed)
- `jarvis/runtime/display_mcp.py` (brain tools for voice parity), Slice 05 Dossier relay/MCP
- `docs/scene-selection-batch.md`, `docs/scene-model.md` › *Visibility vs disposition* (eye wording), `docs/control-center-shell.md`, `docs/dossier.md`
- tests: `test_scene_selection.py`, `test_scene_batch.py`, `test_scene_batch_tools.py`, `test_scene_view_prefs.py`, `test_scene_renderer_logic.py`, `test_selection_method_browser.py`, `test_tool_wheel_browser.py`, a new Ranger browser test

Note: the worktree `C:/Projects/jarvis/eph` holds uncommitted runtime-archive changes to `jarvis/domain/scene.py` (completed ephemeral stars). Do not import them; they belong to the follow-up Issue.

## Architecture constraints

- Hidden remains active/recoverable.
- Archived remains out of active scene/history-backed.
- Dossier durability and scene presence are separate dimensions.
- Destructive actions never masquerade as layout actions.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation`
- `agent-trace-analysis` for agent/voice selection operations
- `/impeccable`, `/caveman`, `/coding-guideline`
- scene batch/MCP/browser selection tests

## Acceptance criteria

- Hidden count is available contextually but no permanent hidden chip returns.
- `Masquer` never creates Dossier content.
- `Ranger` creates/confirms durable Dossier backing before scene removal.
- `Retirer du Board` does not delete a durable Dossier source.
- Representation changes do not clone content.
- Mixed/bulk selections preserve atomic safety and explain refusals.
- Mouse, keyboard and Bare Hands can reach the same actions.

## Documentation updates

Update scene/Dossier tool semantics and shell/wheel accessibility docs.
