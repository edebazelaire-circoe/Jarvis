# Slice 02 — Report

**Commits:**
- `4116dc70`: the contract;
- `b1a7151d`: rework after independent QA (blocking B1 pin source, B2 scene entry at local frame 0, plus 11 polish items).

**Tested tree:** `b1a7151d`.

**Status:** approved by agent 0. Human sign-off HV-RFX-02-01 on `UI-INVENTORY.md` is still open.

## Command

From `C:/Projects/jarvis/brn`:

```
<repo>/.venv/Scripts/python.exe -m pytest tests/unit/<file> -q -p no:cacheprovider
```

One file per process. `JARVIS_DATA_ROOT` points to a fresh scratch folder for each run.

## Results

30 doc test files, all passed:

| Group | Files (tests) |
| --- | --- |
| Contract and routes | `test_presentation_experience_contract_docs` 8, `documented_routes` 3 |
| Presentation Studio | `presentation_studio_docs` 21, `_playback_docs` 9, `_explorer_docs` 8, `_explorer_compare_docs` 4, `_engine_docs` 2, `_presenter_docs` 8, `_release_docs` 5, `_reload_docs` 11, `_scene_variants_docs` 8, `_variants_docs` 13, `_upgrades_docs` 6, `_inspector_docs` 9, `_mcp_docs` 3, `_cue_docs` 7, `_edit_docs` 6, `_history_docs` 8, `_template_docs` 11, `_authoring_docs` 12 |
| Remotion | `remotion_studio_docs` 10, `remotion_player_docs` 6, `_controls_docs` 5, `_mcp_docs` 4, `_release_docs` 4, `_source_edit_docs` 5, `_isolation_docs` 7 |
| Other | `presentation_render_docs` 13, `published_benchmark_figures` 22, `wake_word_docs` 30 |

## QA

Independent `qa-verification` ran on `4116dc70` and recommended REWORK. Its blocking findings:
- **B1:** the pin protection held by stage windows had no migration target.
- **B2:** the contract gave contradictory rules for where a scene enters in a presenter run.

Agent 0 decided B2: a new scene enters at its local frame 0, anchors only bound where the Player stops and holds, and resuming keeps the exact frame.

Everything was applied in `b1a7151d`. Agent 0 checked the rework against the findings list and the green test run. No second QA pass was run (docs-only tier).

## Not run

Behaviour tests: Slice 02 changes no code.
