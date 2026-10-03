# Inherited test baseline at 1600dbf (worktree C:/Projects/jarvis/bwt)

Interpreter: C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe, cwd=bwt (jarvis -> bwt/jarvis/__init__.py).
JARVIS_DATA_ROOT=scratchpad/baseline-data. pytest-timeout NOT installed (ran without --timeout).
1600dbf differs from 257e911 only by task handoff docs (tasks/jarvis-scene-window-prefab-foundation/*).

## Totals
| dir | files | passed | failed | errors | skipped |
|---|---|---|---|---|---|
| tests/unit | 383 | 11645 | 17 | 0 | 12 |
| tests/integration | 72 | 630 | 0 | 0 | 23 |

No collection/import errors. No hanging files.

## Unit failures (17 tests, 11 files)

### Cluster A - `barge_in_decider` setting not reconciled with schema/IA contracts (4) [from merge 257e911, side ^1]
- test_control_center_voice_architecture_review.py (1): test_explicit_selection_roundtrip_preserves_inactive_and_unrelated_settings[config2] - extra key {'barge_in_decider': 'local'}
- test_control_center_voice_architecture_ui_review.py (1): test_server_describes_three_understandable_architectures_and_exact_panels - panel field set contains barge_in_decider
- test_settings_ia_contract.py (1): test_live_voice_stack_and_architecture_fields_are_mapped_once - 'voice_architecture.config.barge_in_decider' unmapped
- test_voice_settings_schema.py (1): test_projection_matches_the_canonical_inventory_categories_and_rendering_contract - extra 'barge_in_decider'

### Cluster B - scene object `source_path` field not in documented MCP output schema (2) [merge side ^1: domain/scene.py, display_mcp.py]
- test_mcp_catalog.py (2): test_scene_outputs_validate_their_documented_schemas; test_truncated_listings_and_an_oversized_object_still_validate_their_text_schemas - jsonschema "Additional properties are not allowed ('source_path' was unexpected)"

### Cluster C - model-visible display surface size changed (1)
- test_control_center_mcp_api.py (1): test_the_api_does_not_change_the_model_visible_display_surface - assert 32598 == 31864 (display_mcp.py grew in merge)

### Cluster D - ReferenceError `orbitTurns is not defined` in scene interact JS (5)
- test_scene_group_drag_js.py (5): test_a_group_move_keeps_recorded_offsets_and_leaves_unplaced_members_behind; test_dragging_n_objects_posts_one_translate_selection_and_confirms_every_layer; test_a_refused_group_move_rolls_every_layer_back_and_nothing_moving_sends_nothing; test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged; test_a_group_pushed_into_a_corner_keeps_every_orbiting_member_on_screen
- jarvis/runtime/control_center_scene_interact.js:1414 calls bare `orbitTurns(...)`; it is only defined in control_center_scene_layout.js (exported on its api). Same line exists in BOTH merge parents, so not a merge loss - latent bug; merge added 22 lines to the test file.

### Cluster E - missing settings field in app wiring test (1)
- test_app.py (1): test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings - AttributeError: SimpleNamespace has no attribute 'data_root' (jarvis/app.py:1469, board-memory work uses settings.data_root; test fake lacks it)

### Cluster F - brain prompt text changed (1)
- test_brain_delegation.py (1): test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available - prompt now has an extra "REGLAGES : L'INTERFACE EST AUSSI LA TIENNE" (settings_* tools) section; expected text ends at "la fiche."

### Cluster G - barehands practice-frame geometry (2)
- test_barehands_interaction_js.py (2): test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine ([-12,-12,64,40] vs [-17,-14,64,40]); test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones ([-72,-20,144,40] vs [-62,-20,124,40]) - assertion on computed geometry

### Cluster H - reduced-motion halo (browser) (1)
- test_interaction_mode_hud_browser.py (1): test_le_mouvement_reduit_arrete_vraiment_le_halo - assert 'none' != 'none' (halo animation already 'none'; possibly environment/browser dependent)

## Import errors / missing symbols
- No Python ImportError / ModuleNotFoundError / collection error anywhere.
- Only "missing symbol": JS ReferenceError orbitTurns (Cluster D) - present identically in both parents of 257e911, so not a lossy-merge artifact.
- Clusters A, B, C trace to code that came in from the local side (257e911^1 "trash") without matching test/schema updates.
