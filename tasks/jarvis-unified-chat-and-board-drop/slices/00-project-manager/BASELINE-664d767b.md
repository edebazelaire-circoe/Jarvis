# Inherited test baseline: bucq @ 664d767b (2026-10-14)

HEAD was 664d767bf33e9690b67b2c12e0fd9b8cb894923a before, during and after the run. Tree clean. `jarvis` imported from C:\Projects\jarvis\bucq. JARVIS_DATA_ROOT was an empty scratch directory and was still empty at the end.

## Counts
| Directory | Files | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|---|
| tests/unit | 801 | 21457 | 22 | 0 | 125 |
| tests/integration | 76 | 648 | 4 | 0 | 26 |
| **Total** | 877 | **22105** | **26** | **0** | **151** |

- HANG: none. Killed: none.
- Wall time: 15:06 to 17:29, about 2h23m end to end. That is 8124 s (2h15m) of pytest across 43 chunk runs, plus collection and reruns.
- Coverage check: the union of the chunk lists equals the sorted list of all 801 unit files.

## Failing tests (all 26)
### tests/unit (22)
- test_app.py::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings: AttributeError at jarvis/app.py:1694, `'types.SimpleNamespace' object has no attribute 'data_root'`
- test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine: `assert [-12,-12,64,40] == [-17,-14,64,40]` (:2343)
- test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones: `assert [-72,-20,144,40] == [-62,-20,124,40]` (:2425)
- test_brain_capability_parity.py::test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt: tool exposed but missing from the prompt, `{'jarvis-display': ['ui_intent_publish']}`
- test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available: voice prompt text differs from expected (`...e consigne.\n` vs `...t la fiche.\n`) (:140)
- test_control_center_voice_architecture.py::test_async_browser_render_does_not_restore_a_previous_panel: node assert, panel rendered `Cannot read properties of undefined (reading 'agenda_reminders')` instead of `<new agent panel>`
- test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo: reduced-motion state still has glow and sweep animation (`sweep: '1.25s ease-in-out infinite imSweep'`) (:185)
- test_memory_context.py::test_recall_over_2000_notes_adds_nothing_to_the_other_context_builders_and_stays_in_budget: asyncio TimeoutError; also fails in an isolated rerun
- test_presentation_studio_explorer_player_js.py (6 tests, all via tests/fakes/explorer_js.py:115 JS TypeError):
  - ::test_the_pure_clock_and_key_rules: `C.autoStep is not a function`
  - ::test_one_play_button_whose_icon_is_the_state_and_the_slides_advance_by_themselves: `Cannot read properties of null (reading 'getAttribute')`
  - ::test_keys_right_left_double_left_space_and_f: `Cannot read properties of undefined (reading 'elapsed_ms')`
  - ::test_skip_five_seconds_moves_the_clock_and_carries_over_to_the_next_slide: `Cannot read properties of null (reading 'click')`
  - ::test_the_run_ends_on_the_last_slide_and_can_loop: `Cannot read properties of null (reading 'click')`
  - ::test_open_with_autoplay_starts_the_clock_inside_the_big_studio: `Cannot read properties of undefined (reading 'on')`
- test_scene_artifacts.py::test_the_artifact_guidance_exists_only_with_the_flag_and_the_other_prompts_are_byte_identical: prompt hash `87c9ecec...` != expected `20a65470...` (:599)
- test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged: `ValueError: substring not found` (:128)
- test_scene_query_tools.py::test_the_read_line_exists_only_with_the_flag_and_the_other_prompts_stay_byte_identical: same prompt hash mismatch `87c9ecec...` != `20a65470...` (:405)
- test_tool_brain_choices.py::test_ui_projection_is_consistent_in_the_single_metadata_copy: `memory_propose` has `reversibility='reversible'`, expected None (:97)
- test_tool_brain_intents.py::test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event: `'BrainOrchestrator' object has no attribute 'publish_ui_intent'` (:115)
- test_tool_brain_intents.py::test_without_a_turn_in_flight_the_intent_is_refused_never_retained: same missing `publish_ui_intent` (:144)
- test_tool_brain_intents.py::test_the_whole_channel_tool_to_core_over_the_real_protocol: `'display_internal_error' == 'no_turn_in_flight'` (:187)
- test_wake_word_settings_browser.py::test_la_section_reste_lisible_dans_chaque_theme[cosmos]: browser `TypeError: Cannot set properties of null (setting 'value')` (_wake_word_settings_browser.mjs:68); the [circuit-board] case passes

### tests/integration (4)
- test_settings_redesign_migration.py::test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation: assembled settings-migration.cjs:413 `SyntaxError: Unexpected token '}'` (:95)
- test_testlab_audio_runners.py::test_a_real_near_end_voice_over_the_echo_is_confirmed: `assert 0 >= 1` (:181), aiohttp server logged handler errors
- test_testlab_audio_runners.py::test_the_run_records_what_the_chain_actually_exercised: `assert (False is True)` (:196), aiohttp ClientConnectionResetError in log
- test_testlab_live_runners.py::test_the_live_runner_measures_the_provider_latency_and_records_its_identity: `assert (False is True)` (:198)

## Notes
- Reproducibility: the 6 explorer_player tests, memory_context, interaction_mode_hud, wake_word[cosmos], the 3 testlab tests and barehands "moved_by_one_zone" were rerun alone and failed again. The other failures were seen once only, but they look deterministic: missing attributes, prompt hash and text mismatches.
- Several failures share a likely cause, an in-progress `ui_intent_publish` / `publish_ui_intent` feature: brain_capability_parity, tool_brain_intents x3 and probably tool_brain_choices. The prompt hash mismatch is shared by scene_artifacts and scene_query_tools.
- Load: another session's pytest (C:\Projects\jarvis\jarvis\.venv) ran at the same time. Chunk u_13_0h0 (15 files, test_wake_word_install_command..test_workspace_manager_browser) took 665 s and went past the 600 s tool timeout, but it finished normally on its own and was not killed, so it was not split.
- Method: per-chunk `-rf -rE` left only the `E` summary because the last `-r` wins. Node IDs were therefore recovered by mapping F positions in the progress output to `--collect-only`; the counts matched for every chunk except u_06_0, which was confirmed by rerunning the file directly.
