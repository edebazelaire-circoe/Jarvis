# Baseline rouge a 9721b3ca (origin/main)

Worktree: C:/Projects/jarvis/bipq (detached, HEAD 9721b3ca2a593e9469c2cd5ea714b0c7001f7e8b avant et apres, status propre).
Python: C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest, PYTHONPATH=C:/Projects/jarvis/bipq, cwd bipq.
`import jarvis` verifie: C:\Projects\jarvis\bipq\jarvis\__init__.py. Options: -q -p no:cacheprovider (pas de -x).
Pas de package.json: les tests JS sont des tests pytest qui lancent node (tests/unit/*_js.py, *_browser.py), inclus dans les chunks.

## Chunks (446 fichiers tests/unit/test_*.py tries, decoupes en 8 par liste)
| # | Premier -> dernier fichier | Fichiers | Passed | Failed | Skipped | Duree |
|---|---|---|---|---|---|---|
| 0 | test_action_broker -> test_barehands_pointer_js | 53 | 1274 | 3 | 0 | 3m11 |
| 1 | test_barehands_pointing_intent_js -> test_catalog_view | 57 | 1342 | 1 | 3 | 6m20 |
| 2 | test_claude_debug_console -> test_data_root | 50 | 1298 | 1 | 1 | 2m47 |
| 3 | test_deployment -> test_owner_input_gate | 58 | 1658 | 1 | 4 | 3m23 |
| 4 | test_owner_replay -> test_scene_capture_logic | 55 | 2021 | 0 | 4 | 4m42 |
| 5 | test_scene_constellation -> test_spontaneous_notice_typing | 56 | 1608 | 1 | 5 | 2m19 |
| 6 | test_sqlite_scene -> test_tool_brain_speech | 58 | 2177 | 3 | 0 | 1m45 |
| 7 | test_tool_brain_wiring -> test_worktree_pool | 59 | 1710 | 0 | 0 | 3m03 |
| 8 | tests/integration (74 fichiers) + tests/e2e (1 fichier) | 75 | 648 | 0 | 23 | 9m55 |

Les listes exactes sont l'ordre alphabetique de tests/unit/test_*.py coupe en 8 blocs consecutifs (split -n l/8).

## Totaux
Passed 13736, Failed 10, Errors 0, Skipped 40.

## Echecs (10, 8 fichiers). Tous reels au SHA (aucune erreur d'import, aucune erreur d'environnement)
### Control Center / UI JS
- tests/unit/test_barehands_interaction_js.py (2)
  - test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine: box [-12,-12,64,40] au lieu de [-17,-14,64,40], geometrie du deplacement divergente.
  - test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones: [-72,-20,144,40] au lieu de [-62,-20,124,40], resize plus ample que l'attendu.
- tests/unit/test_control_center_voice_architecture.py (1)
  - test_async_browser_render_does_not_restore_a_previous_panel: le rendu JS des reglages leve "Cannot read properties of undefined (reading 'agenda_reminders')".
- tests/unit/test_interaction_mode_hud_browser.py (1)
  - test_le_mouvement_reduit_arrete_vraiment_le_halo: en reduced-motion l'animation `sweep` reste active (1.25s infinite imSweep), le halo n'est pas arrete.
- tests/unit/test_scene_group_drag_js.py (1)
  - test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged: test par inspection de source, ValueError, la chaine "if(g.mode==='move'&&g.carried.length>1){" est absente de control_center_scene_page.js (test perime ou code refactore).
### Core / app wiring
- tests/unit/test_app.py (1)
  - test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings: AttributeError, le SimpleNamespace de settings du test n'a pas `data_root`.
### Brain / prompt
- tests/unit/test_brain_delegation.py (1)
  - test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available: le prompt contient en plus la section "REGLAGES : L'INTERFACE EST AUSSI LA TIENNE" (settings_*) absente de l'attendu (test perime).
- tests/unit/test_tool_brain_intents.py (3)
  - test_publishing_during_a_turn_attaches_the_intent_and_records_one_contentless_event: AttributeError 'BrainOrchestrator' has no attribute 'publish_ui_intent' (server.py l'appelle, la methode n'existe pas).
  - test_without_a_turn_in_flight_the_intent_is_refused_never_retained: obtient display_internal_error au lieu de no_turn_in_flight, meme cause.
  - test_the_whole_channel_tool_to_core_over_the_real_protocol: meme cause (publish_ui_intent manquant sur BrainOrchestrator).

## Skips (40, tous environnement/opt-in)
Symlinks impossibles sans privilege Windows (WinError 1314), ffmpeg absent (capture), axe-core absent (JARVIS_AXE_JS), modele owner-voice absent, signaux POSIX / DPAPI non-Windows, tests integration opt-in (JARVIS_TESTLAB_*, live OpenAI), 1 skip presentation_integration (aucun outil nommable).

## Notes
- Aucun fichier produit modifie, aucun stash, aucun autre worktree touche.
- tests/replay et tests/fixtures/fakes: pas de tests collectes en propre.
- Le chunk integration+e2e a depasse 9 min (9m55) : a decouper en deux pour les futurs runs.
