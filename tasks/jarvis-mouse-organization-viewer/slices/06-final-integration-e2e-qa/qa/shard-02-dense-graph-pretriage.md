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

## Completed shard evidence and exact failed phase

Root shard 02 completed with **1,305 passed, 2 failed, 21 skipped**, exit 1.
The app settings-stub `data_root` failure is already listed/known. The dense
graph node remains an unclassified potential regression and blocking pending
disproof. Its actual traceback is line 438, `board["open"]`, raising TypeError
because the captured board is `None`.

Thus preceding mark-count, viewport-share and overlap assertions passed; this
failure is specifically that the relation board DOM never exists after the
physical click and bounded wait. It is not the overlap assertion hypothesized
as one possible discriminator above. `BOARD` returns None only when
`document.getElementById('relationBoard')` is absent. The relation reader creates
that panel synchronously in `open()` before starting HTTP reads, so an ordinary
slow/failed relation fetch would leave a panel/loading/error, not this None.

## Full scene-page pointer/click path inspected

The event path was traced beyond unchanged graph modules:

1. `applyMarks` creates actual button elements under `.sc-relmarks`, a sibling
   layer outside `.sc-node`. It sets `data-relation-id`, keeps them mounted and
   attaches delegated `onMarkClick` to the marks container. This path is unchanged.
2. `nodeElement(target)` finds only closest `.sc-node`. A correctly targeted
   mark/button or its SVG is outside a scene node. Scene `onPointerDown` therefore
   returns before gesture creation. The new S05 `geometryBusy` guard only returns
   earlier and there is no geometry command in this scenario.
3. `onDocumentBandDown`/`bandCandidate` were checked: actual `button` targets
   are excluded from band selection. Document selection clearing can run, but its
   only task change adds viewer/status exemptions; it does not prevent or stop
   the mark's event. These checks do not create a relation panel themselves.
4. The S02 eight resize grips are emitted only for window/capsule
   representations. All 38 fixture objects are point agents, so no new grip target
   is added over this graph. Existing mark-layer rank, point hover/focus rank and
   mark pointer-events styles are unchanged. No viewer/dialog was opened, and its
   lazy styles/controls do not overlay this scenario.
5. New normal-click/menu behavior is inside scene-node gesture pointerup; context
   selection is on contextmenu, viewer opening on double-click/Enter, and aspect
   behavior on resize/Shift. None directly handles a correctly targeted ordinary
   click on a relation button. The harness's ordinary clickCount remains 1.
6. Unchanged `onMarkClick` prevents default (not propagation), derives the selected
   mark IDs and calls the existing `JarvisRelationBoard.open`. Missing module or
   synchronous failure is logged. The test checks console errors only after its
   board assertion, so this failure does **not** establish that the console was
   clean. The full gate log does not retain the returned step console/actions.

This tracing finds no direct introduced handler interception of a correctly
targeted mark; it does not prove the real click hit that mark. Chromium evidence
is required before ruling out an introduced hit/stack/timing effect.

## Concrete unresolved hit-test discriminator

The Node harness resolves the mark's current bounding-rectangle centre, then
sends mouseMoved, mousePressed and mouseReleased at those coordinates. It never
checks `elementFromPoint`, the eventual event target or whether that specific
mark is inside the viewport. The test permits up to 20% of marks outside the
viewport and does not separately prove `rel_comm` is one of the inside marks.
Marks also reflow every second while orbiting; hovered/focused point rank can
exceed the mark layer. These are existing potential click-miss mechanisms, not
established explanations for this run.

When PM allocates a bounded browser check, retain the exact baseline outcome
and, if the scenario needs diagnosis, its selected mark rectangle/viewport,
element at the click point, pointer/click targets and errors. A passing baseline
at another wall-clock phase alone cannot prove this failure unrelated. Do not
change product code or weaken the test merely because source paths look stable.
Baseline Chrome is still **not executed** and the blocking status remains.
