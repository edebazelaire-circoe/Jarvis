# Slice 07 - Right-side active workspace rail with rich previews

## Goal
Move the current presentation rail to the right and evolve it into the active workspace rail without inventing a second registry.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `01-shell-contract-and-design-system`

## Scope / implementation steps
First preserve the complete existing presentation-rail behavior while moving/rebuilding its visual renderer on the right. Replace monogram-only rows with cards: real preview where available, recognizable type treatment, title, lightweight metadata, status and context menu.

Then, if current Board/artifact APIs support it cleanly, include additional context-linked image/video/document artifacts through a view-model adapter. Do not crawl arbitrary files or maintain local membership.

Status mapping: blue working, green ready/done, yellow changed/unreviewed only if backed by canonical state, explicit orange/red problem/error retained. Context switch must refresh the working set. Existing actions (open Variantes, Studio, edit, present, hide/show, rename, archive/restore where applicable) remain available.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center_presentation_rail.js`
- `presentation rail routes/view model`
- `workspace/artifact UI adapters if broadening beyond presentations`
- `presentation rail tests`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- `code-review` is mandatory.
- `runtime-validation` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- Rail is on the right and no longer competes with the left wheel.
- Presentation behavior/actions are preserved.
- Cards visually identify type and use truthful preview/fallback.
- Status is semantic and never relies on color alone.
- `problem` is not mislabeled as `changed`.
- Current-context membership is server/canonical-data-driven.
- Studio/Variantes coexists with the new rail without layering regressions.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` §8 (D10), D13. QA tier: **ui** (no SQLite migration; would become critical if one were added).

**Files.** Core `jarvis/core/presentation_studio_rail.py` (row `preview` + `type`, cached; `unreviewed` key in `rail.json` v1; action `review`; set on brain work `success`), `jarvis/protocol/presentation_studio_rail_routes.py` (docstring table), relay docstring `jarvis/runtime/presentation_studio_relay.py`; UI `jarvis/runtime/control_center_presentation_rail.js` (right zone, cards: preview/placeholder, type badge, title, metadata, state label+dot, menu affordance; Studio docking mirrored), new `jarvis/runtime/control_center_workspace_rail_model.js` (Stage B, pure) + script constant/injection; `docs/presentation-studio.md` (› Rail), `docs/control-center-shell.md`. Tests: `tests/unit/test_presentation_studio_rail.py` (Core), `tests/unit/test_control_center_presentation_rail_js.py`, `tests/unit/test_control_center_presentation_rail_browser.py`, `tests/unit/test_presentation_rail_e2e_browser.py`, new `tests/unit/test_workspace_rail_model_js.py`.

**Acceptance tests.** `test_presentation_studio_rail.py::test_row_preview_is_latest_complete_still_without_path`, `::test_preview_cache_bounded`, `::test_brain_success_marks_unreviewed_user_review_clears`, `::test_old_rail_json_reads_without_unreviewed`, `::test_problem_never_reported_as_unreviewed`; `test_control_center_presentation_rail_js.py::test_state_precedence_working_problem_unreviewed_done`, `::test_label_accompanies_every_dot`, `::test_placeholder_when_no_preview`; browser `::test_rail_right_no_overlap_launcher_chat_tab`, `::test_studio_docks_left_of_rail`, `::test_context_actions_preserved`, `::test_brain_show_hide_rail_and_display_state`; `test_workspace_rail_model_js.py::test_items_from_board_artifacts_typed_by_mime_and_host`, `::test_board_switch_drops_previous_items`.

**Not in this slice.** Generic file library; crawling files; yellow for Stage B items; changes to `jarvis.sqlite3`. Touches `control_center.html` only for the rail host line and its registry row (parallel with S02).

**Preserved invariants.** Rail is a view of Core; open/edit/present/hide/show/rename/archive/restore unchanged; `problem` keeps its own treatment; visibility rule and `Alt+Maj+P`; text via `textContent`.

**Test migrations here.** `test_presentation_rail_e2e_browser.py:52,68` (rail right of palette / left of Studio -> right zone / Studio bounded by rail).
