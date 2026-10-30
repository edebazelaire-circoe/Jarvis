# Dense graph browser failure: pretriage, no baseline run

Observed naturally in the root shard-02 log at root revision
`97d56f1144cb721e7c5303f43ff71d291ed1d9bc`:
`tests/unit/test_scene_task_graph_browser.py::test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable`.

This is an actual Chromium scenario. No browser, pytest, server or model was
launched for this pretriage. No product file or root HEAD changed. Final shard
trace and exact-baseline execution are needed before classifying the failure.

## Source comparison

Byte-identical between `c0858a80` and root HEAD:

- `test_scene_task_graph_browser.py`: SHA-256
  `d96b6a23cc12f6b497167b6a316a34eb9e8e83c7c7e2278669c92e88a8905145`.
- Python page/harness helpers `test_status_centre_browser.py` and
  `test_boards_card_browser.py`.
- `control_center_scene_layout.js`: SHA-256
  `f982cf9d9247c0c41e60c27ad35bd1f0e94b01138daa421ae1cb2455966d3560`.
- `control_center_scene_roles.js`: SHA-256
  `2759fd25ccb0cbba5769ac28d4b57123cbdb0dcbd58b9e95864933eb3e29990c`.
- `control_center_relation_board.js`: SHA-256
  `ebd5fba327a141b1346355bdb4271423b97ab958fed376c126819810314c7afc`.

The scene page and Node harness changed in this feature, so unchanged layout
code alone is not proof of a pre-existing failure. The harness diff adds layout
mutation support and new pointer/key options. This scenario uses only eval,
ordinary click and optional screenshots; its click helper's default clickCount
remains 1. It does not exercise resize, drag, Enter, Escape, viewer opening or
layout mutation. Viewport/forced-colour setup and settle timing are unchanged.
The tested role/relation rendering logic and relation-board click path are not
changed by the scene-page diff. New viewer styles/readers are lazy and not
opened by this scenario.

## Scenario and pending discriminator

The test drives three served-page instances:

1. 720×450, device scale factor 2, 38 role stars and dense typed relations;
   measures relation marks, then clicks `rel_comm` to open the relation board.
2. 1440×900 with forced colours; reads line styles and QA mark border colour.
3. 1440×900 Cosmos theme; reads role badges.

Assertions require >25 marks, at least 80% within viewport, maximum overlap
below 85%, at most two pairs overlapping by at least 50%, an in-viewport open
relation board, readable forced-colour styles, role badge and no browser errors.
The graph continues orbiting when measured; overlap is measured at an instant.
This makes the precise failing line/metrics material. Do not assume timing,
pre-existing drift or feature regression from the failure name alone.

## Queued command, requires separate PM authorization

After final trace review and when a browser allocation is explicitly allowed:

```powershell
Set-Location C:/Projects/jarvis/movb
git rev-parse HEAD
$env:PYTHONDONTWRITEBYTECODE='1'
$env:JARVIS_S09_EVIDENCE_DIR='C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/dense-graph-baseline-captures'
& C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -p no:cacheprovider -q tests/unit/test_scene_task_graph_browser.py::test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/dense-graph-baseline.xml
```

This command has **not** been run. No global ignore, known-failure list entry or
product correction is proposed before actual evidence. PM owns disposition.
