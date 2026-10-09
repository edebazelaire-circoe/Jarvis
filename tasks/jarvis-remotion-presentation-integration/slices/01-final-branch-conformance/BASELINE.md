# Measured test baseline on `main` de7b9c59 - NOT OURS, DO NOT FIX

**For implementers of Slices 02-22: every failure listed here exists on `main` before this task changed anything. Do not fix, skip, xfail or "clean up" them as part of a Remotion Slice. A test that is red here and still red after your Slice is inherited; a test that is green here and red after your Slice is YOUR regression and blocks the Slice.** Fixing one of these is a separate Issue with its own owner.

## Environment of the measurement

- Date: 2026-10-09. Commit: `7648eba5` on branch `task/jarvis-remotion-presentation-integration` in the worktree `C:/Projects/jarvis/brm` = `main` `de7b9c59` + the handoff folder only (no product file differs from `main`; verified `git status` showed only `tasks/` and one `docs/presentation-studio.md` table edit made after the unit runs, then the four docs-parity suites re-run green: 46 passed).
- Interpreter: `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe` (Python 3.14, pytest 9.1.1, pytest-asyncio 1.4.0), run with the worktree as cwd; `jarvis` imported from `C:\Projects\jarvis\brm\jarvis` (checked). Windows 11, Node v24.18.0 (browser/JS tests spawn Chrome via Node). Host RAM free about 5 GB at start.
- Command: `python -m pytest -p no:cacheprovider -q --no-header -rfE <files>` in foreground chunks. The unit chunks were run with the user's shell variables `JARVIS_UI_PORT`, `JARVIS_VISUALIZER_PORT`, `JARVIS_CORE_HOST` present (they are set in the agent environment); the 16 failing tests were then **re-run with those three unset**: result below. Integration and the re-runs used the three variables unset. No `JARVIS_LIVE_*` / `OPENAI_API_KEY` opt-in variable was set (live tests skip).
- No live Core, Control Center or voice was started or touched. The data root is the per-worktree default (`~/.jarvis/instances/...`); no file under `data/` of any repository was read or written.
- Not run: `tests/replay/*` harnesses (real-model traces, cost money and need the `claude` CLI), the opt-in live/hardware/audio/real-session tests (skipped by their own guards).

## Totals (re-measured, not carried over from any LOG)

| Suite | Files | Passed | Failed | Skipped | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| `tests/unit` (all 631 `test_*.py`) | 631 | **18 435** | **16** | 24 | 0 |
| `tests/integration` (79 files; the live/hardware ones skip by guard) | 79 | **651** | **1** | 26 | 0 |
| `tests/e2e` | 1 | 1 | 0 | 0 | 0 |
| **Total** | 711 | **19 087** | **17** | 50 | 0 |

(The old studio LOG's reported sweep, 16 739 passed / 10 failed / 40 skipped, is a different head and is not comparable; do not quote it.)

## Chunks that were run (each a separate pytest invocation)

| Chunk | Files | Result |
| --- | --- | --- |
| `tests/unit/test_a*.py` | 16 | 411 passed, 1 failed |
| `tests/unit/test_b*.py` | 86 | 1 963 passed, 4 failed, 2 skipped |
| `tests/unit/test_c*.py` | 61 | 1 626 passed, 1 failed, 2 skipped |
| `tests/unit/test_[defgik]*.py` | 35 | 946 passed, 1 failed, 6 skipped |
| `tests/unit/test_[lmo]*.py` | 54 | 2 061 passed, 1 failed, 6 skipped |
| `tests/unit/test_p*.py` except `test_pres*` | 25 | 641 passed |
| `tests/unit/test_pres*.py` except `test_presentation_studio*` | 17 | 937 passed, 3 skipped |
| `tests/unit/test_presentation_studio*.py` (4 chunks: 66 + 22 + 23 + 22 files) | 133 | 1 846 + 279 + 520 + 671 = 3 316 passed |
| `tests/unit/test_[rs]*.py` | 78 | 2 224 passed, 3 failed, 5 skipped |
| `tests/unit/test_[tuvw]*.py` | 126 | 4 310 passed, 5 failed |
| `tests/integration/test_[a-p]*.py` | 34 | 221 passed, 10 skipped |
| `tests/integration/test_[q-z]*.py` | 45 | 430 passed, 1 failed, 16 skipped |
| `tests/e2e` | 1 | 1 passed |

All 133 Presentation Studio unit files (3 316 tests) and every `test_presentation_*` file are **green**. No Presentation Studio, Artifact, Board, prefab, plugin or schema-migration test is red.

## Every failing test (17)

First column: unit/integration; the re-run column says whether it still failed alone with the three `JARVIS_*` variables unset. Cause = first assertion line observed (one-line diagnosis, not a root-cause analysis).

| # | Test (`tests/...`) | Re-run alone, env unset | Observed cause |
| ---: | --- | --- | --- |
| 1 | `unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings` | fails | `AttributeError: 'types.SimpleNamespace' object has no attribute 'data_root'` at `jarvis/app.py:1604` (test double lacks a settings field) |
| 2 | `unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine` | fails | `[-12,-12,64,40] != [-17,-14,64,40]` (geometry through a JS engine) |
| 3 | `unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones` | fails | `[-72,-20,144,40] != [-62,-20,124,40]` |
| 4 | `unit/test_brain_capability_parity.py::test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt` | fails | `{'jarvis-display': ['ui_intent_publish']}` exposed to the brain but absent from its prompt. **Known red.** |
| 5 | `unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` | fails | prompt text differs (`'Tu es le cer...e consigne.' != '...t la fiche.'`) |
| 6 | `unit/test_control_center_voice_architecture.py::test_async_browser_render_does_not_restore_a_previous_panel` | fails | Node `strictEqual` mismatch in the browser render (expected `<new agent panel>`) |
| 7 | `unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo` | fails | reduced-motion halo: `'none' != 'none'` assertion on computed style in Chrome |
| 8 | `unit/test_memory_context.py::test_recall_over_2000_notes_adds_nothing_to_the_other_context_builders_and_stays_in_budget` | **passed alone** | failed once inside the full chunk: timing / load sensitive, treat as **flaky** |
| 9 | `unit/test_scene_artifacts.py::test_the_artifact_guidance_exists_only_with_the_flag_and_the_other_prompts_are_byte_identical` | fails | prompt digest `67bd0503... != 20a65470...` (a prompt other than the flagged one changed) |
| 10 | `unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged` | fails | `ValueError: substring not found` at `test_scene_group_drag_js.py:128` (page source marker moved) |
| 11 | `unit/test_scene_query_tools.py::test_the_read_line_exists_only_with_the_flag_and_the_other_prompts_stay_byte_identical` | fails | same digest pair `67bd0503... != 20a65470...` as #9 |
| 12 | `unit/test_tool_brain_choices.py::test_ui_projection_is_consistent_in_the_single_metadata_copy` | fails | `AssertionError: memory_propose` (`'reversible' is None`) |
| 13 | `unit/test_tool_brain_intents.py::test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event` | fails | `'BrainOrchestrator' object has no attribute 'publish_ui_intent'` |
| 14 | `unit/test_tool_brain_intents.py::test_without_a_turn_in_flight_the_intent_is_refused_never_retained` | fails | same `publish_ui_intent` AttributeError |
| 15 | `unit/test_tool_brain_intents.py::test_the_whole_channel_tool_to_core_over_the_real_protocol` | fails | `'display_internal_error' == 'no_turn_in_flight'` |
| 16 | `unit/test_wake_word_settings_browser.py::test_la_section_reste_lisible_dans_chaque_theme[cosmos]` | fails | Chrome/CDP script exception (`_wake_word_settings_browser.mjs:68`) in the `cosmos` theme only |
| 17 | `integration/test_settings_redesign_migration.py::test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation` | fails | generated Node script `SyntaxError: Unexpected token '}'` (`settings-migration.cjs:413`); cause not investigated |

Groups: **#4, #12-#15** are the Tool Brain `ui_intent_publish` channel that the studio task documented as broken on `main` ("handoff Issue 01", `docs/presentation-studio.md` section "Binding facts"); **#9, #11** are byte-identity checks of prompts (a prompt shared with the studio planner attachment or another change moved a digest; not investigated); **#2, #3, #6, #7, #10, #16, #17** are browser/JS page tests (Chrome/Node, layout or page source); **#1, #5** are independent test-double / prompt drift; **#8** is flaky.

Comparison with what was already known: the one known-red test (#4) reproduces. The READINESS note listed only #4 because it had run two files; the wide sweep here finds 15 more files' worth of reds that are present on `main` for reasons unrelated to Remotion. The old studio LOG says "10 baseline reds"; this head has 17 (16 unit, 1 integration) of which #8 is flaky; the sets are not the same head, so do not equate them.

## How a Slice must use this

1. Before starting, run the files you touch plus the files named in your SLICE.md; compare with this table.
2. Never list one of these 17 as caused or fixed by your Slice. A new red outside this table is a regression of yours.
3. If your Slice changes a prompt, the Tool Brain tools, a Control Center page script or `jarvis/app.py`, re-run #1, #4, #5, #9-#17 to show you did not change their failure signature.
4. Re-measure the baseline when `main` moves (this file is exact for `de7b9c59`/`7648eba5` only).
