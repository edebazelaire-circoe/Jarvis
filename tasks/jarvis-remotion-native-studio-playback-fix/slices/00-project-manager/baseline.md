# Slice 00 — inherited test baseline

## 1. Setup

- Worktree: `C:/Projects/jarvis/brq`, detached at **a8377529fa5753ab7636e019e218e424735f88b3**. HEAD checked before and after every chunk and rerun; it never moved.
- Runner: `bash <scratchpad>/run.sh <chunk> [test ids...]`, with `<scratchpad>` = `<home>/AppData/Local/Temp/claude/C--Projects-jarvis-jarvis/5d10375d-bc4d-4ad8-a28b-db91564b9e33/scratchpad`. It runs `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider -rfE --junitxml=res/<chunk>.xml <files>` in `brq` with an isolated `JARVIS_DATA_ROOT=<scratchpad>/datar/<chunk>` and a 560 s timeout. Logs and XML files are in `<scratchpad>/res/`.
- Chunks ran in the foreground, one at a time. JARVIS was not started or stopped.
- JS/Node: `jarvis/capabilities/remotion/package.json` has no `node_modules` and no test script. There is no separate Node suite; the browser `.mjs` tests run through their pytest wrappers. No `npm install` was run.

## 2. Results per chunk

| Chunk | Wall (pytest) | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|---|
| u00 | 238 s | 1527 | 3 | 0 | 1 |
| u01 | 394 s | 1359 | 2 | 0 | 2 |
| u02 | 317 s | 1543 | 1 | 0 | 4 |
| u03 | 511 s | 2082 | 1 | 0 | 5 |
| u04a | 138 s | 1258 | 0 | 0 | 4 |
| u04b | 297 s | 1105 | 0 | 0 | 5 |
| u05a | 166 s | 900 | 0 | 0 | 9 |
| u05b | 394 s | 802 | 0 | 0 | 0 |
| u06a | 418 s | 678 | 1 | 0 | 0 |
| u06b | 433 s | 541 | 77 | 0 | 0 |
| u07a | 155 s | 808 | 0 | 0 | 0 |
| u07b | 76 s | 913 | 0 | 0 | 20 |
| u08a | 91 s | 484 | 0 | 0 | 11 |
| u08b | 206 s | 978 | 2 | 0 | 3 |
| u09a | 103 s | 891 | 1 | 0 | 4 |
| u09b | 88 s | 814 | 0 | 0 | 1 |
| u10a | 96 s | 1429 | 0 | 0 | 0 |
| u10b | 55 s | 774 | 4 | 0 | 0 |
| u11a | 43 s | 705 | 0 | 0 | 0 |
| u11b (all 26 files) | timed out at 560 s (rc=124) | — | — | — | — |
| u11b1 (first 13 files) | timed out at 560 s (rc=124) | — | — | — | — |
| u11b1a (8 files) | 45 s | 390 | 0 | 0 | 0 |
| u11b1b (`test_wake_word_settings_browser.py` alone) | 528 s | 19 | 1 | 0 | 0 |
| u11b1c (4 files) | 8 s | 148 | 0 | 0 | 0 |
| u11b2 (last 13 files) | 91 s | 544 | 0 | 0 | 0 |
| i00 | 112 s | 182 | 0 | 0 | 9 |
| i01 | 330 s | 273 | 1 | 0 | 16 |
| i02 | 180 s | 194 | 0 | 0 | 1 |
| i03 | 5 s | 2 | 0 | 0 | 0 |

u11b did not hang. `test_wake_word_settings_browser.py` alone takes about 530 s, which is close to the timeout by itself. The split chunks u11b1a, u11b1b, u11b1c and u11b2 together cover all of u11b.

**Overall:** 21343 passed, 94 failed, 0 errors, 95 skipped.
- Unit tests: 20692 passed, 93 failed, 69 skipped.
- Integration tests: 651 passed, 1 failed, 26 skipped.

After isolated reruns, **16 failures still fail** and **78 pass (flaky)**.

Caveat: for u06b the runner printed `rc=0` even though the log has 77 failures. Trust the pytest summary line, not the printed rc.

## 3. Failing tests, isolated reruns and likely causes

### Still fail in isolation (16)

- `tests/unit/test_app.py`
  - `test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings`: still fails. `AttributeError: 'types.SimpleNamespace' object has no attribute 'data_root'`. The test's fake settings are missing `data_root`, which the product code now reads.
- `tests/unit/test_barehands_interaction_js.py`
  - `test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`: still fails. Got `[-12,-12,64,40]`, expected `[-17,-14,64,40]`. The engine's move geometry and the frame values pinned in the test no longer match.
  - `test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`: still fails. Got `[-72,-20,144,40]`, expected `[-62,-20,124,40]`. Same geometry drift, on resize.
- `tests/unit/test_brain_capability_parity.py`
  - `test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt`: still fails. `jarvis-display` tool `ui_intent_publish` is exposed to the brain but missing from the brain prompt.
- `tests/unit/test_brain_delegation.py`
  - `test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`: still fails. The voice agent prompt now ends with an extra "RÉGLAGES : L'INTERFACE EST AUSSI LA TIENNE" (settings_*) section that the pinned expected prompt does not have.
- `tests/unit/test_control_center_voice_architecture.py`
  - `test_async_browser_render_does_not_restore_a_previous_panel`: still fails. The settings render shows `Cannot read properties of undefined (reading 'agenda_reminders')`. The test stub is missing a settings section the page now reads.
- `tests/unit/test_interaction_mode_hud_browser.py`
  - `test_le_mouvement_reduit_arrete_vraiment_le_halo`: still fails. With reduced motion, `halo` is `none`, but the sweep animation `1.25s ... infinite imSweep` and the glow are still running.
- `tests/unit/test_scene_artifacts.py`
  - `test_the_artifact_guidance_exists_only_with_the_flag_and_the_other_prompts_are_byte_identical`: still fails. The SHA-256 of `BRAIN_SYSTEM_PROMPT` (fb9400af…) no longer equals the pinned base hash (20a65470…). The brain prompt changed and the pin is stale.
- `tests/unit/test_scene_group_drag_js.py`
  - `test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`: still fails. `ValueError: substring not found`. The source snippet `if(g.mode==='move'&&g.carried.length>1){` is no longer in `onPointerUp`, so the test's static source slice is stale.
- `tests/unit/test_scene_query_tools.py`
  - `test_the_read_line_exists_only_with_the_flag_and_the_other_prompts_stay_byte_identical`: still fails. Same stale brain-prompt hash as `test_scene_artifacts`.
- `tests/unit/test_tool_brain_choices.py`
  - `test_ui_projection_is_consistent_in_the_single_metadata_copy`: still fails. `memory_propose` has `reversibility='reversible'`, but the test expects `None`. Tool metadata and the test disagree.
- `tests/unit/test_tool_brain_intents.py`
  - `test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event`: still fails. `AttributeError: 'BrainOrchestrator' object has no attribute 'publish_ui_intent'`.
  - `test_without_a_turn_in_flight_the_intent_is_refused_never_retained`: still fails. Same missing `publish_ui_intent`.
  - `test_the_whole_channel_tool_to_core_over_the_real_protocol`: still fails. Core answers `display_internal_error` instead of `no_turn_in_flight`, also because `publish_ui_intent` is missing. The tool `ui_intent_publish` is wired, but the orchestrator method is not there. This looks like the same gap as the parity failure.
- `tests/unit/test_wake_word_settings_browser.py`
  - `test_la_section_reste_lisible_dans_chaque_theme[cosmos]`: still fails (the `circuit-board` case passes). `TypeError: Cannot set properties of null (setting 'value')` on `#ww_provider` after switching to the cosmos theme. The wake-word section is not rendered or open in that theme.
- `tests/integration/test_settings_redesign_migration.py`
  - `test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation`: still fails. The assembled `settings-migration.cjs` throws `SyntaxError: Unexpected token '}'` at the closing IIFE. The test slices the Control Center JS source, and that slicing no longer matches the source.

### Pass in isolation: flaky (78)

- `tests/unit/test_presentation_studio_inspector_browser.py::test_reset_and_undo_redo_through_the_buttons_and_the_keyboard_match_the_history_routes` (u06a): passes. Likely a timing-sensitive browser test under load.
- u06b, 77 failures in 6 files. All pass when each file's failing ids are rerun together, outside the chunk:
  - `test_presentation_studio_reload_browser.py`: 15 failures, 15 passed on rerun.
  - `test_presentation_studio_reload_crash.py`: 6 failures, 6 passed.
  - `test_presentation_studio_reload_host_js.py`: 22 failures, 22 passed.
  - `test_presentation_studio_reload_page_js.py`: 28 failures, 28 passed.
  - `test_presentation_studio_reload_real_page_browser.py`: 2 failures, 2 passed.
  - `test_presentation_studio_scene_variants_crash.py`: 4 failures, 4 passed.

  Cause: child processes failed to start. The node and python children exited with code 3221225794 (0xC0000142, STATUS_DLL_INIT_FAILED) and empty stderr, which is Windows running out of resources (desktop heap) after many process spawns in one long chunk on a low-RAM host. These are environment failures, not product failures. No orphaned node or python test processes were left behind.

Note on method: the u06b ids were rerun as one isolated pytest call per file (77 ids), not one process per id. Every other failing id was rerun on its own or in its small failure group.

## 4. Chunks not run

None. u11b timed out twice (whole chunk, then its first half). It was split and fully covered by u11b1a, u11b1b, u11b1c and u11b2.
