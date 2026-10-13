# Baseline: Slice 00, jarvis-remotion-master-project-studio-export

- SHA: d101d88740c4cf10c2da8114384d0148ec05c3ff (merge of b52fa939 "fix + runtime" and 408dc365 main)
- Worktree: C:/Projects/jarvis/bmq (detached, clean, HEAD checked == d101d887 before and after every chunk)
- Python: C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe, pytest 9.1.1 (no pytest-timeout plugin)
- Env: JARVIS_UI_PORT / JARVIS_VISUALIZER_PORT / JARVIS_CORE_HOST unset for the runs, so no test could point at the live Jarvis
- Date: 2026-10-13. Other sessions were running pytest on the host at the same time (load)

## Commands

Runner (scratchpad/bl/run.sh), run per chunk, from C:/Projects/jarvis/bmq:

    python -m pytest -q -p no:cacheprovider -rfEs --junitxml=bl/<chunk>.xml $(cat bl/<chunk>)

- File set: `tests/unit/test_*.py` + `tests/integration/test_*.py` = 863 files, sorted alphabetically
- chunk_00 = first 50 files; c_00..c_13 = 30 files each; h_14_a..h_26_b = 15 files each (smaller chunks to stay under the 10-minute limit)
- s_1..s_11 = the 11 `test_presentation_studio_reload_*` files, one per process. No `test_scene_variants_crash*` file exists at this SHA
- Isolation reruns: r_1..r_12 and r_21..r_23, one failing file per process
- Logs and junit xml: scratchpad/bl/*.log and *.xml

## Totals (whole suite, chunked run)

| passed | failed | errors | skipped |
|---|---|---|---|
| 21837 | 23 | 0 | 140 |

After the isolation reruns: **22 deterministic failures in 14 files, plus 1 load flake.**

## Deterministic failures (each also fails when its file runs alone)

| File | Test | Short message | Inherited |
|---|---|---|---|
| integration/test_settings_redesign_migration.py | test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation | assembled settings-migration.cjs:413 SyntaxError: Unexpected token '}' | yes |
| unit/test_app.py | test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings | AttributeError: SimpleNamespace has no attribute 'data_root' | yes |
| unit/test_barehands_interaction_js.py | test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine | [-12,-12,64,40] != [-17,-14,64,40] | yes |
| unit/test_barehands_interaction_js.py | test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones | [-72,-20,144,40] != [-62,-20,124,40] | yes |
| unit/test_brain_capability_parity.py | test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt | jarvis-display ui_intent_publish missing from the brain prompt | yes |
| unit/test_brain_delegation.py | test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available | brain prompt text differs at its end | yes |
| unit/test_control_center_voice_architecture.py | test_async_browser_render_does_not_restore_a_previous_panel | notice "Cannot read properties of undefined (reading 'agenda_reminders')" | yes |
| unit/test_interaction_mode_hud_browser.py | test_le_mouvement_reduit_arrete_vraiment_le_halo | assert 'none' != 'none' (reduced-motion halo) | yes |
| unit/test_scene_artifacts.py | test_the_artifact_guidance_exists_only_with_the_flag_and_the_other_prompts_are_byte_identical | prompt sha256 87c9ec... != 20a654... | yes |
| unit/test_scene_group_drag_js.py | test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged | ValueError: substring not found | yes |
| unit/test_scene_query_tools.py | test_the_read_line_exists_only_with_the_flag_and_the_other_prompts_stay_byte_identical | prompt sha256 87c9ec... != 20a654... | yes |
| unit/test_tool_brain_choices.py | test_ui_projection_is_consistent_in_the_single_metadata_copy | memory_propose: reversibility 'reversible' is not None | yes |
| unit/test_tool_brain_intents.py | test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event | 'BrainOrchestrator' has no attribute 'publish_ui_intent' | yes |
| unit/test_tool_brain_intents.py | test_without_a_turn_in_flight_the_intent_is_refused_never_retained | 'display_internal_error' == 'no_turn_in_flight' | yes |
| unit/test_tool_brain_intents.py | test_the_whole_channel_tool_to_core_over_the_real_protocol | publish_ui_intent missing | yes |
| unit/test_wake_word_settings_browser.py | test_la_section_reste_lisible_dans_chaque_theme[cosmos] | TypeError: Cannot set properties of null (setting 'value') | yes |
| unit/test_presentation_studio_explorer_player_js.py | test_the_pure_clock_and_key_rules | TypeError: C.autoStep is not a function | **NO (new)** |
| unit/test_presentation_studio_explorer_player_js.py | test_one_play_button_whose_icon_is_the_state_and_the_slides_advance_by_themselves | TypeError: Cannot read properties of null (reading 'getAttribute') | **NO (new)** |
| unit/test_presentation_studio_explorer_player_js.py | test_keys_right_left_double_left_space_and_f | TypeError: Cannot read properties of null (reading 'click') | **NO (new)** |
| unit/test_presentation_studio_explorer_player_js.py | test_skip_five_seconds_moves_the_clock_and_carries_over_to_the_next_slide | TypeError: Cannot read properties of undefined (reading 'elapsed_ms') | **NO (new)** |
| unit/test_presentation_studio_explorer_player_js.py | test_the_run_ends_on_the_last_slide_and_can_loop | TypeError: Cannot read properties of null (reading 'click') | **NO (new)** |
| unit/test_presentation_studio_explorer_player_js.py | test_open_with_autoplay_starts_the_clock_inside_the_big_studio | TypeError: Cannot read properties of undefined (reading 'on') | **NO (new)** |

All 13 inherited files from the READINESS at a8377529 still fail, with the same counts. The extra docs tests noted later all **pass** at d101d887: test_presentation_studio_edit_docs (authored_released_for_studio) and the render, authoring and import docs tests.

### Presentation / Remotion / Variants failures, all new and all deterministic

`tests/unit/test_presentation_studio_explorer_player_js.py`: all 6 tests fail (6 failed, 0 passed) in the chunk and alone.

**Cause: the merge d101d887 dropped code.**
- **Where the test came from:** commit b52fa939 ("fix + runtime", edebaze, 2026-10-13 09:52) added the test. The same commit added Studio autoplay code: `autoStep`, `leftKeyAction` and `nextDwell` in `jarvis/runtime/control_center_presentation_studio_explorer_core.js`, plus play, keyboard and skip wiring in `control_center_presentation_studio_explorer.js`.
- **What the merge kept:** it took main's 408dc365 version of both JS files unchanged. The diff against 408dc365 is 0 lines, and `autoStep` appears 0 times. Only b52fa939's test came through.
- **Result:** the test checks an API that is not in the code. This is a regression from the merge resolution, not an environment issue. The fix is to port the b52fa939 autoplay additions onto the reworked Variants/explorer code, or to adapt or retire the test.

No other presentation, Remotion, Variants, render or studio test fails. All 11 `test_presentation_studio_reload_*` files pass one per process.

## Flakes (fail only under batch load)

| File | Test | Chunk result | Alone |
|---|---|---|---|
| unit/test_memory_context.py | test_recall_over_2000_notes_adds_nothing_to_the_other_context_builders_and_stays_in_budget | failed (c_09) | 38 passed (37 s): timing or budget under load |

The 0xC0000142 flake did not show up, because the reload files were run one per process from the start.

## Skips (140)

### Remotion / presentation / Variants "real runtime" skips

The main gate is `JARVIS_REMOTION_RUNTIME_DIR`, which must point to an existing Remotion install with node_modules. Most of these tests also need node, and the browser ones need Chrome. Some report "points to no installed Remotion runtime", which means the default or empty location has no install.

- test_presentation_continuous_playback_browser.py (2): needs JARVIS_REMOTION_RUNTIME_DIR, node, Chrome
- test_presentation_flow_quality_browser.py (2): same
- test_presentation_playback_release_gate_browser.py (15): same
- test_presentation_resilience_browser.py (2): same
- test_presentation_render_real.py (2): JARVIS_REMOTION_RUNTIME_DIR + Node.js
- test_presentation_studio_authoring_remotion_browser.py (3): needs JARVIS_REMOTION_RUNTIME_DIR, node, Chrome
- test_presentation_studio_authoring_remotion_real.py (6): "JARVIS_REMOTION_RUNTIME_DIR points to no installed Remotion runtime"
- test_remotion_compiler_real.py (17): same
- test_remotion_studio_real.py (1): same
- test_remotion_continuity_realpage_browser.py (1), test_remotion_controls_realpage_browser.py (1), test_remotion_player_realpage_browser.py (7), test_remotion_timeline_realpage_browser.py (2), test_remotion_source_edit_realpage_browser.py (1): needs JARVIS_REMOTION_RUNTIME_DIR, node, Chrome
- test_remotion_frame_quality_real.py (3): needs JARVIS_REMOTION_RUNTIME_DIR, node, Chrome
- test_remotion_import_real.py (2): needs **JARVIS_REMOTION_IMPORT_NETWORK=1** + JARVIS_REMOTION_RUNTIME_DIR + node
- test_remotion_isolation_real.py (1): JARVIS_REMOTION_RUNTIME_DIR, Chrome, Node
- test_remotion_media_tools.py (2), test_remotion_release_flows.py (1), test_remotion_source_edit_real.py (1), test_remotion_studio_shape_real.py (1): JARVIS_REMOTION_RUNTIME_DIR (+ node)
- test_remotion_studio_roundtrip_real_browser.py (1): JARVIS_REMOTION_RUNTIME_DIR, node, Chrome
- test_variants_controls_browser.py (2): JARVIS_REMOTION_RUNTIME_DIR with node_modules, node, Chrome
- test_variants_media_export.py (1), test_variants_media_fullscreen_browser.py (7), test_variants_transport_browser.py (5): JARVIS_REMOTION_RUNTIME_DIR, node, Chrome
- test_variants_remotion_studio_browser.py (1): **JARVIS_VARIANTS_REMOTION_EVIDENCE_DIR** not set
- test_remotion_studio_publish.py:271 (1): this Windows account cannot create symlinks. Junctions and hard links are still tested.

### Other skips (environment or opt-in)

- **Live providers:** JARVIS_LIVE_OPENAI, JARVIS_LIVE_CLAUDE, JARVIS_LIVE_GPT_LIVE, JARVIS_LIVE_CIRCOE, JARVIS_TENCENT_LIVE
- **Testlab:** JARVIS_TESTLAB_AUDIO, _HARDWARE, _GUIDED, _REAL_SESSION, _LIVE
- **Real state DB:** JARVIS_TEST_REAL_STATE_DB
- **Symlink privilege missing:** about 10 tests
- **Missing tools or models:** ffmpeg absent (3), owner-voice model absent (2), wakeword model and clip env (2), axe-core (JARVIS_AXE_JS)
- **Other:** JARVIS_CODEGRAPH_TIMING, real embedding provider, POSIX-only (2), barehands real-hand fixture absent, one presentation_integration skip that is covered elsewhere
