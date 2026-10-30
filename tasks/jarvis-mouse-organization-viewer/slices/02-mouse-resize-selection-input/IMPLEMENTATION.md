# S02 implementation — 2026-10-30

Implemented in isolated `mov2`, branch `task/mov-s2`, from S0 `5571fb07`.

IMPLEMENTING NEW LOGIC — mouse side descriptors and proportional constraint: mouse lacked edge/corner selection and Shift; canonical hold desk, side math and collision sweep already exist and are extended in place.

## Delivered

- Eight internal edge/corner hit targets on resizable windows and capsules; thin incumbent frame and correct native cursors. Prefab slots/iframes stay attached, targets remain siblings managed by the existing host.
- Mouse calls shared `resizeBySides` via the existing hold desk. Optional proportional constraint interpolates the entire rectangle at collision rather than independently distorting two dimensions. Opposite anchors stay fixed; edge-only Shift expands the other dimension around its center.
- Shift-at-start locks initial ratio; modifier press/release rebases at current drawn geometry/current pointer with no jump. PM accepted segment-local ratio clarification; recorded in SLICE.md and canonical docs.
- Right-click selected member and Menu/Shift+F10 preserve/anchor group. Unselected member replaces it.
- Ordinary mouse single-click selects/anchors; context actions use right-click/keyboard. Bare Hands selected-click and touch/stylus long-press remain. Necessary to make native double-click reachable.
- Ctrl/Cmd+A selects rendered, non-ghost scene nodes only from scene/background; editable text and other panels keep their shortcuts.
- Escape cancels active resize without write. Existing hold/drop/cancel, pending geometry, shields, group movement and keyboard arrows retained.

## S05 seam

Listen on `document` for bubbling `jarvis:scene-open`. `event.detail = {objectId, ids, source}`. Source: `keyboard` (Enter on focused scene node) or `double-click` (native mouse dblclick over noninteractive body). IDs are live selection if anchor belongs to it, otherwise anchor only. Event performs no geometry or selection writes. Filter content compatibility and launch viewer in S05; links/buttons/editable regions/resize handles keep their interactions.

`I.RESIZE_HANDLES` publishes named sides. `desk.take` accepts `{mode:'resize', pointer:{x,y}, sides:'top-left', aspectLocked:true}`; omitted sides retain southeast default. `desk.drag(handle,x,y,aspectLocked?)` carries current Shift state. Bare Hands calls remain unchanged.

## Validation observed

All commands used `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest --assert=plain --tb=short -q` with workdir mov2. No full suite.

- `test_mouse_resize_input.py`: **11 passed** (8 descriptors/opposite anchors, Shift rebase/release, proportional screen clamp, unchanged Bare Hands min rules).
- `test_mouse_resize_browser.py` first three scenarios: **3 passed in 53.36 s**, real CDP mouse/key events in fully served Control Center HTML with isolated fetch fixture. Sixteen actual resizes (8 directions × capsule/window), one command per operation after unrelated initial auto-fit, group context/menu keyboard parity, Ctrl+A/editable exception, native dblclick/Enter intents, Shift press/release movement, Escape rollback.
- Additional `test_shift_held_at_start_locks_initial_ratio_then_keyboard_resize_works`: passed in focused browser/Bare Hands batch (the unrelated Bare Hands baseline test below failed).
- Browser screenshot + existing wheel-selection scenario: **2 passed in 28.62 s**. Screenshot `qa/evidence/mouse-selection.png` opened and visually inspected: incumbent dark scene/menu, thin selected frames, no clipping/blank content.
- Hold contract + hold desk + interaction logic, excluding proven baseline browser-dialog regex: **49 passed, 1 deselected in 10.49 s**.
- Gesture shield + prefab page + hold rework/rework2: **29 passed in 6.32 s**. Updated existing source-wiring assertion for Shift arg and prefab redraw fixture for eight sibling grips; no iframe detach/remount regression.
- Broader focused geometry/artifact/group batch: **89 passed**, one pre-existing static group-drag test failed (below).
- Selected Bare Hands body-zone/min-size/frame-seam tests passed; one practice-resize expectation failed identically at baseline (below).
- `node --check` both changed JS files passed. Impeccable mechanical detector on scene page returned `[]`. `git diff --check` clean.

## Baseline failures — PM independently reproduced without S02

1. `test_scene_interaction_logic.py::test_the_page_serves_the_interaction_logic_and_never_uses_browser_dialogs`: regex treats existing `confirm()` comment in rail module as browser dialog. Use `--assert=plain` to avoid huge injected HTML repr.
2. `test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`: static test expects obsolete inline branch; existing code uses hold desk/drop.
3. `test_control_center_shell_layers.py::test_every_rank_in_css_matches_the_registry`: existing `.jvr-play` rank 1 missing registry entry. New `.sc-grip` rank is within existing scene-contained rank rules.
4. `test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`: actual existing `[-72,-20,144,40]`, stale expected `[-62,-20,124,40]`.

PM assigns baseline cleanup to S06; none changed here.

## Limits

Independent QA still required. No real camera/hand tracking, macOS Cmd key hardware, or user's live runtime used. Viewer/content filtering and organization/undo are S05 scope. No provider prompt, model behavior, agent runtime, backend or schema changed.
