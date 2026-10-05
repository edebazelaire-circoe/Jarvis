# Baseline: task/jarvis-presentation-interaction-mode (worktree C:/Projects/jarvis/bpm, HEAD 5378eb6 = 085928d + S0 handoff commit)
Interpreter: C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe. pytest-timeout is not installed, so the runs used no --timeout.
Command: python -m pytest -q -p no:cacheprovider -o addopts="" <files> -rfE  (foreground, 9 unit chunks + 2 integration chunks)

## Totals
- tests/unit: 384 files, 11,684 tests: 11,662 passed, 10 failed, 12 skipped
- tests/integration: 72 files, 653 tests: 629 passed, 1 failed, 23 skipped
- Collection or import errors: none

## Failing tests (each re-run alone once: all STABLE, no flakes)
### tests/unit/test_app.py
- test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings: STABLE. The test passes a SimpleNamespace settings with no `data_root`, and app.py:1470 now reads it. The test fixture is stale.
### tests/unit/test_barehands_interaction_js.py
- test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine: STABLE. The frame geometry is [-12,-12,64,40] where the test expects [-17,-14,64,40]. The engine's step or zone size drifted from the test.
- test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones: STABLE. Same cause: [-72,-20,144,40] where the test expects [-62,-20,124,40].
### tests/unit/test_brain_delegation.py
- test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available: STABLE. The voice-agent system prompt now has a "RÉGLAGES" (settings_*) section that the expected text lacks. The prompt is out of sync with the test.
### tests/unit/test_interaction_mode_hud_browser.py
- test_le_mouvement_reduit_arrete_vraiment_le_halo: STABLE. Under reduced motion the halo is already 'none' before and after, so the test's `!= 'none'` precondition fails. The baseline CSS has no halo animation to stop.
### tests/unit/test_scene_group_drag_js.py
- test_a_group_move_keeps_recorded_offsets_and_leaves_unplaced_members_behind: STABLE. ReferenceError: `orbitTurns` is not defined at control_center_scene_interact.js:1414 (orbitGroupDelta).
- test_dragging_n_objects_posts_one_translate_selection_and_confirms_every_layer: STABLE. Same orbitTurns ReferenceError.
- test_a_refused_group_move_rolls_every_layer_back_and_nothing_moving_sends_nothing: STABLE. Same orbitTurns ReferenceError.
- test_a_group_pushed_into_a_corner_keeps_every_orbiting_member_on_screen: STABLE. Same orbitTurns ReferenceError.
- test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged: STABLE. ValueError "substring not found": the page's onPointerUp no longer contains `if(g.mode==='move'&&g.carried.length>1){`. This is source drift from the `fix/scene-deplacement-2d` merge.
### tests/integration/test_scene_transport.py
- test_stopping_the_server_releases_a_pending_long_poll: STABLE. The pending long poll gets ConnectionRefused (WinError 1225) instead of a 200 with empty patches when the server stops. The poll is not yet connected, or the stop refuses it on Windows.
