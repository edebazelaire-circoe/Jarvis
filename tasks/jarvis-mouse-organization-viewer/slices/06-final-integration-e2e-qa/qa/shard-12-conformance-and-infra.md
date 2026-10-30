# Shard 12: atomic-drop test conformance and browser startup failure

## Original gate result

Frozen root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc`: **1518 passed,
3 failed, 6 skipped**, pytest duration 1239.24 seconds. Original trace:
`C:/Projects/jarvis/mov/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/evidence/shard-12.log`.

Two failures in `test_scene_renderer_logic.py` required old per-member
`d.commit` source substrings at lines 518 and 550. S05 intentionally changed
group drop to the accepted atomic `commitMany` path, backed by independent
real Core/browser proof. PM assigned test-conformance rework; these failures
are neither classified as baseline failures nor hidden as ignores.

## Corrective test change

Both tests now execute the production interaction module through the existing
`test_scene_hold_desk.run_desk` harness. The harness exposes its existing
injected dependencies as `P.deps` so tests can observe the canonical commit
and view seams; no geometry or pointer implementation was added.

The first test observes actual `createPending` layers at **every** hold-release
callback and requires all commit calls to precede the first release. Seven
scenarios cover atomic group, partly changed group (unchanged member retained),
legacy group without `commitMany`, single object with `commitMany` available,
resize limited to the primary target, and unchanged group/single drops.
Commit promises remain unresolved until after drop and release, checking
synchronous optimistic setup independently from eventual network completion.
Every held member must be released. Existing mouse/Bare Hands/keyboard page
wiring assertions remain.

The second test requires one batch for three mixed representations, no
individual commits, all members still held at the batch call, exact target
IDs/origins/representations, preserved dimensions and the expected common
nonzero displacement. Existing page selection, follow-edge, refusal reporting
and the production `commitManyGeometry` wiring checks remain.

Focused foreground verification: **13 passed in 10.35 seconds**. Retained
[console log](shard-12-conformance.log) and [JUnit](shard-12-conformance.xml).
The same main venv interpreter was used with `PYTHONDONTWRITEBYTECODE=1`:

```powershell
python -m pytest --assert=plain --tb=short -p no:cacheprovider -q `
  tests/unit/test_scene_renderer_logic.py::test_the_dropped_place_is_pending_before_the_hand_lets_go `
  tests/unit/test_scene_renderer_logic.py::test_a_gesture_on_a_selected_object_carries_the_whole_selection `
  tests/unit/test_scene_hold_desk.py::test_group_drop_calls_atomic_seam_once_before_releasing_and_releases_on_throw `
  tests/unit/test_scene_hold_desk.py::test_4_a_drop_on_the_same_place_does_not_animate `
  tests/unit/test_scene_hold_desk.py::test_a_keyboard_resize_resizes_and_a_move_moves `
  tests/unit/test_scene_group_drag_js.py `
  --junitxml=tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/shard-12-conformance.xml
```

No product file changed, and no full suite or browser was launched for this
correction. The original gate result remains recorded as red.

## Browser infrastructure pretriage; current rerun queued

The third failure is
`test_settings_shell_browser.py::test_open_voice_model_comparison_does_not_overflow[1366-768]`.
Its trace reaches `_wake_word_settings_browser.mjs:52`, then `poll` at line
190: `Chrome n a pas ouvert son port de debogage`.

The helper spawns Chrome on `about:blank` and first polls its loopback
`/json/list` endpoint for a page debugger URL (100 attempts, 150 ms between
attempts). This failure occurs before creating the CDP WebSocket or reaching
`Page.navigate` at line 106. Consequently the failed run did not navigate to
the Control Center page or execute the model-comparison/overflow assertions.
It proves a debugger-startup failure, not a measured layout failure; the
specific Chrome/process/resource cause was not captured and is not inferred.

The original shard log also reports **`Unclosed client session`** and
**`Unclosed connector`**, including an aiohttp connection deque, after the
pytest summary. These warnings are preserved as an unresolved cleanup signal;
their owning fixture and relationship to Chrome startup are not established.

Queue only the affected current-branch parameter for a browser rerun after
the broad gate and a PM resource allocation. No baseline/browser execution
was performed during this pretriage.
