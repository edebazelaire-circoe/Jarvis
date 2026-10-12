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

**Status: paused at 41 / 457** on agent 0's order: drive C: fell to about 170-240 MB free from outside this task (WSL/Docker suspected) at
about 21:30. Results so far:

| File | Result | Note |
| --- | --- | --- |
| 38 files | green | (includes `integration/test_scene_transport.py`: 56 passed on its rerun) |
| `integration/test_board_session_e2e.py` | killed at the 250 s cap | to rerun alone with a longer cap |
| `integration/test_presentation_scenarios.py` | 1 failed (`test_explicit_turn_latency_is_unc…`), 15 passed | timing test under load and low disk: to rerun |
| `integration/test_remote_mcp_connector.py` | killed at the cap (2 F seen) | during the disk-full window: to rerun |
| `integration/test_scene_transport.py` (first run) | 43 errors during disk full (`No space left`) | rerun: 56 passed |
