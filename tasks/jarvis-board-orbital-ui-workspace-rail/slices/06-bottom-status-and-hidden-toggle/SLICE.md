# Slice 06 - Bottom status center, recording indicators, and hidden-object eye

## Goal
Replace the F9 visual hint/right notification pills/hidden-object capsule with a compact bottom-center status system.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `01-shell-contract-and-design-system`
- `04-capture-wheel-migration`

## Scope / implementation steps
Remove the permanent bottom-center `F9 - DEMARRER` capsule while preserving any still-supported keyboard behavior. Re-render existing notification category data as a horizontal bottom-center strip. Required categories: alert/warning, completed task, pending question. A fourth item only if mapped to a canonical current category. Preserve click-through/popover semantics and unread/seen mutations.

Place Audio/Video active indicators adjacent as distinct `REC`/audio timer states. Add a compact eye/eye-off button for hidden-object visibility; remove permanent hidden-object count text. The eye calls the existing scene visibility behavior and reflects canonical state.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center.html`
- `notification/background-pill rendering code`
- `jarvis/runtime/control_center_scene_page.js or scene interaction module`
- `capture view model for persistent indicators`

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
- No F9 capsule remains in the approved shell.
- Required notification counters are readable, clickable and data-equivalent to the old model.
- Recording timers are visible while active and not confused with unread counters.
- Eye toggle is the only permanent hidden-object control in this zone; state is accessible by icon + label.
- No overlap with bottom-left context control or right rail.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` D8, §7 (D9), §10 rank 40, §11. QA tier: **ui**.

**Files.** `jarvis/runtime/control_center.html` (status centre container bottom-centre: `#recIndicators` | `#bgPills` | `#hiddenEye`; `BG_CATS` icons as inline SVG, larger targets; `#voiceHint` element and its CSS removed; `refreshStatus` writes the key hint into `.state` description; `.board-drop-tray` bottom from tokens); `control_center_capture_rail.js` (indicator view placed in `#recIndicators`); `control_center_scene_view.js` (`showHidden` field); `control_center_scene_layout.js` (`viewModel` `options.showHidden`, `ghost` nodes); `control_center_scene_page.js` (ghost rendering, ghost menu "Réafficher", `sc-hidden` note removed, eye wiring + `openHiddenMenu` on secondary); `control_center_interaction_mode.js` (rung selectors); `docs/control-center-shell.md`, `docs/scene-model.md` (view pref), `docs/interaction-mode.md` (rungs), `docs/boards.md` (alert pills location). Tests: `tests/unit/test_status_centre_browser.py`, `tests/unit/test_scene_view_prefs.py`, `tests/unit/test_scene_renderer_logic.py`.

**Acceptance tests.** `test_status_centre_browser.py::test_same_counts_and_categories_as_status_summary`, `::test_click_opens_same_popover_and_ack_clears`, `::test_icons_have_label_and_count_not_colour_only`, `::test_recording_indicator_distinct_from_counters_and_stops`, `::test_no_overlap_with_mode_control_rail_chat_tab_tray_at_1440_1280_900_600`, `::test_status_centre_clears_open_chat_panel`, `::test_no_voicehint_and_f9_still_wakes`; `test_scene_view_prefs.py::test_show_hidden_defaults_false_and_normalizes`; `test_scene_renderer_logic.py::test_show_hidden_emits_ghosts_without_writing_scene`, `::test_one_reveal_one_set_visibility`; browser `::test_eye_toggle_aria_pressed_and_secondary_lists_hidden`.

**Not in this slice.** Moving `#boardsHud`; launcher/dock changes (S08); archived objects.

**Preserved invariants.** Background category truth, sound cue rules, multi-tab leader, Board-elsewhere attribution, ack semantics; F9 keyboard; per-object visibility untouched by the eye; other `.sc-status` notes still shown.

**Test migrations here.** `test_control_center_mvp.py:74`, `test_scene_renderer_logic.py` (`.voicehint` in selector list), `test_interaction_mode_hud_js.py:1397,1469`, `test_barehands_contracts_js.py:194`, `test_presentation_attention_browser.py:606`, `test_control_center_chat_ui.py:77`, `test_control_center_chat_browser.py:385` — each mapped in §11; `test_board_alerts_browser.py:31` must stay unchanged (ids kept).
