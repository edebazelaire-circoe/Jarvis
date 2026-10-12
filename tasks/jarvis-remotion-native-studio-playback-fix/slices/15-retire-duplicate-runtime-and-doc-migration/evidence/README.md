# Slice 15 evidence

Tested HEAD: `feb4563e` (code `c6ecf553`, docs `96c752c6`, fixture `2d8cb83b`). The live Jarvis was never started, stopped or contacted.
Paths below are repo-relative; no home path or user name is recorded.

## Audit commands (HEAD `c486eae7`)

```sh
for p in jvStudioBand studio_stage studio_aux STUDIO_STAGE presentation_window JarvisPresentationWindow rs-bar jvx-vbar "8 s par" dwell \
         onNavigate stage_object_id window_open reload_stage LegacyStageReclaimer explorateur; do git grep -l -F -- "$p" -- jarvis tests docs; done
git grep -n "\.chain(" -- jarvis tests          # no caller of the playback client's chain()
# orphan CSS: every .jvx-* selector of the Variants modules vs the bare class token elsewhere (now test_variants_css_orphans.py)
# unreferenced Python defs of the presentation Core/MCP modules (git grep -w count <= 1): none
# unreferenced JS functions of presentation/rail/Remotion/prefab-host/fullscreen modules (word count <= 1): two named IIFEs only
```

Results are summarised in `../CLEANUP.md` § 1.

## Slice tests

| File | Result |
| --- | --- |
| `test_presentation_studio_task_base_data.py` (new) | 2 passed |
| `test_variants_css_orphans.py` (new) | 2 passed; mutant `.jvx-upg` → `.jvx-upgrades` fails both |
| `test_presentation_retirement_map_docs.py` (new) | 4 passed |
| `test_presentation_studio_player_js.py` | 9 passed |
| `test_variants_controls_js.py`, `test_variants_transport_js.py`, `test_remotion_stage_js.py` | 5, 29, 26 passed |
| `test_mcp_catalog.py`, `test_presentation_studio_mcp_policy.py`, `test_presentation_studio_mcp_ops.py` | 92, 11, 27 passed |
| every docs test touching presentation / Remotion / Variants / fullscreen / prefabs / architecture / operations (40 files, one per process) | 40 files green |

MCP catalogue: declared 113 521 → 113 495 B (budget 113 700); `jarvis-presentation` 20 888 → 20 862 B (budget 21 000).

## Wide regression sweep

File list: `sweep-files.txt` (457 files of `tests/unit` + `tests/integration` matching presentation, Remotion, Variants, control center,
MCP, scene, board, docs, privacy, fullscreen, prefab, rail, studio, continuous, composition, playback, frame quality, media tools; three
voice-composition files that matched « composition » by name were dropped). One file per process, 250 s cap per file, chunks under 10 min.

Run on the task branch as it moved (Slices 12-14 reworks landed meanwhile; last code tip `c190f48e`), then 713ee2de for the fix below.
First pass at 41 / 457 paused at about 21:30 (drive C: full from outside the task); resumed when about 27 GB were free.

**Totals, 457 files:** 11 230 passed, 6 failed, 95 skipped (real Remotion / Chrome / network runtime not set: `JARVIS_REMOTION_RUNTIME_DIR`).

| File | Result | Verdict |
| --- | --- | --- |
| `integration/test_board_session_e2e.py` | killed at the 250 s cap during the disk-full window; rerun 7 passed | not a regression |
| `integration/test_presentation_scenarios.py` | 1 latency failure during the disk-full window; rerun 16 passed | not a regression |
| `integration/test_remote_mcp_connector.py` | killed at the cap during the disk-full window; rerun 36 passed | not a regression |
| `integration/test_scene_transport.py` | 43 errors `No space left`; rerun 56 passed | not a regression |
| `unit/test_presentation_studio_docs.py::test_no_studio_state_leaked_into_the_sqlite_schemas_or_the_repository` | failed: the guard wants `tests/fixtures/presentation_studio/` to hold flat `.json` documents only, and the Slice 15 fixture was a folder inside it | **Slice 15 regression, fixed 713ee2de**: fixture moved to `tests/fixtures/presentation_studio_task_base_a8377529/` (21 + 2 passed; engine-migration 9, prefab routes 25 passed) |
| `unit/test_presentation_studio_edit_docs.py::test_every_diagnostic_the_edit_service_emits_is_documented` | `core.presentation_studio.authored_released_for_studio` undocumented | passes at `c486eae7`; introduced by the Slice 13 second rework `3da74f17`, **not Slice 15** (agent 0) |
| `unit/test_control_center_voice_architecture.py` (`agenda_reminders` undefined), `unit/test_scene_artifacts.py` and `unit/test_scene_query_tools.py` (brain prompt hash), `unit/test_scene_group_drag_js.py` (substring not found), `unit/test_scene_interaction_logic.py` (`confirm(` in the page) | 1 failure each | **pre-existing**: same failure at `c486eae7` in a fresh `bs15` worktree |
