# SWEEP-1 - wide regression sweep (read-only)

Branch task/jarvis-interactive-presentation-studio, resolved HEAD **64d494f903708c06adf69b23ef657ec36917a1b3** ("S0: Slices 06, 07 and 17 approved and merged").
Worktree C:/Projects/jarvis/bipq detached at that sha; HEAD verified unchanged before and after every chunk; `import jarvis` resolves to bipq. Foreground pytest, `-q -p no:cacheprovider`, no -x.
Baseline: origin/main 9721b3ca = 13736 passed, 10 failed, 40 skipped.

## Chunks (alphabetical, tests/unit/test_*.py = 556 files, 48 per chunk)
| chunk | files (first .. last) | passed | failed | err | skipped | time |
|---|---|---|---|---|---|---|
| u00 | test_action_broker .. test_barehands_learned_wake_posture | 1180 | 3 | 0 | 0 | 3:09 |
| u01 | test_barehands_lifecycle_js .. test_brain_interrupted_speech | 996 | 1 | 0 | 2 | 3:35 |
| u02 | test_brain_notice_contract .. test_conversation_event_mouth_producers | 1313 | 1 | 0 | 1 | 6:07 |
| u03 | test_conversation_event_producers .. test_live_duplex_review | 1287 | 1 | 0 | 4 | 7:02 |
| u04 | test_live_idle_composition_review .. test_prefab_routes | 1504 | 0 | 0 | 2 | 3:17 |
| u05 | test_prefab_service .. test_presentation_studio_history | 1945 | 0 | 0 | 3 | 5:58 |
| u06 | test_presentation_studio_history_crash .. test_presentation_studio_scene_variants_domain | 1144 | 0 | 0 | 0 | 12:52 (over the 9 min goal; tool backgrounded it, waited, passed) |
| u07 | test_presentation_studio_scene_variants_limits .. test_scene_contracts | 1548 | 0 | 0 | 0 | 3:39 |
| u08 | test_scene_file_watcher .. test_speech_presentation_scheduler | 1219 | 1 | 0 | 5 | 2:27 |
| u09 | test_speech_scheduler_live_completion .. test_tool_brain_active | 1825 | 0 | 0 | 0 | 2:02 |
| u10 | test_tool_brain_adapters .. test_voice_architecture_benchmark | 1036 | 3 | 0 | 0 | 1:30 |
| u11 | test_voice_architecture_config .. test_worktree_pool | 1090 | 0 | 0 | 0 | 2:30 |
| i00 | tests/integration test_agenda_reminders_core .. test_settings_redesign_migration (39 files) | 355 | 0 | 0 | 10 | 5:01 |
| i01 | tests/integration test_simple_front_brain_composition .. test_work_ui_projection (38 files) + tests/e2e + tests/replay | 297 | 0 | 0 | 13 | 6:57 |

tests/replay contains only helper modules (no tests collected); tests/e2e has test_demo_scenario.py (in i01).

## Totals vs baseline
- Now: **16739 passed, 10 failed, 0 errors, 40 skipped**.
- Baseline: 13736 passed, 10 failed, 40 skipped.
- Delta: +3003 passed, +0 failed, skipped identical (40 = 40; per-test skip comparison not available, count identical so no net new skips).
- **No NEW-REGRESSION. No ERROR. The 10 failures are exactly the 10 baseline reds.**

## Failing tests (all BASELINE-RED; each re-run alone once: same failure alone, deterministic, no flake; no further reruns needed since none passed alone)
1. tests/unit/test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings - `AttributeError: 'types.SimpleNamespace' object has no attribute 'data_root'` - BASELINE-RED (fails alone).
2. tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine - `assert [-12,-12,64,40] == [-17,-14,64,40]` - BASELINE-RED (fails alone).
3. tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones - `assert [-72,-20,144,40] == [-62,-20,124,40]` - BASELINE-RED (fails alone).
4. tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available - prompt equality diff, extra "REGLAGES : L'INTERFACE EST AUSSI LA TIENNE" block in actual prompt - BASELINE-RED (fails alone).
5. tests/unit/test_control_center_voice_architecture.py::test_async_browser_render_does_not_restore_a_previous_panel - node ERR_ASSERTION, actual `<div class="notice bad">Cannot read properties of undefined (reading 'agenda_reminders')</div>` vs expected `<new agent panel>` - BASELINE-RED (fails alone).
6. tests/unit/test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo - `assert 'none' != 'none'` (halo computed style) - BASELINE-RED (fails alone, 3:31 headless Chrome).
7. tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged - `ValueError: substring not found` - BASELINE-RED (fails alone).
8-10. tests/unit/test_tool_brain_intents.py::{test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event, test_without_a_turn_in_flight_the_intent_is_refused_never_retained, test_the_whole_channel_tool_to_core_over_the_real_protocol} - `AttributeError: 'BrainOrchestrator' object has no attribute 'publish_ui_intent'` / `'display_internal_error' == 'no_turn_in_flight'` - BASELINE-RED (fail alone).

## Product-code size (`git diff --stat origin/main...HEAD -- jarvis`)
94 files changed, 27882 insertions(+), 55 deletions(-) (69 files added). (origin/main has since moved to fed66732; merge-base is 9721b3ca, the baseline sha.)

Files under jarvis/ over 1500 lines that the task grew (all were already over 1500 at the merge-base; none newly crossed it):
- jarvis/runtime/control_center.py 6244 -> 6481 (+239)
- jarvis/runtime/control_center.html 4730 -> 4752 (+24)
- jarvis/runtime/control_center_scene_page.js 3968 -> 3988 (+21)
- jarvis/core/brain_service.py 2687 -> 2694 (+7)
- jarvis/runtime/control_center_timeline.js 2585 -> 2604 (+20)
- jarvis/runtime/presentation_runtime.py 1866 -> 1892 (+26)
- jarvis/app.py 1785 -> 1788 (+4)
- jarvis/protocol/server.py 1601 -> 1616 (+15)
- jarvis/runtime/control_center_scene_interact.js 1521 -> 1525 (+4)
Biggest concern: control_center.py (+239, 6481 lines). No new file over 1500 lines was added.

## Environment notes
- C: free space 45G at start -> 46G at end (swung 45-59G between chunks; browser chunks freed/used a few GB). Cleaned only jarvis-*-cdp-* dirs older than 15 min in %TEMP% after each chunk; 15 recent ones remained at the end (younger than 15 min).
- Noisy output (not failures): aiohttp "Unclosed client session/connector" warnings in u06; "own FN" lines printed by a speech-scheduler corpus test in u05.
- Live Jarvis (17653/17654) never touched; no product file modified, no stash; only this report written in bips.
