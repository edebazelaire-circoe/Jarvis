# Issue 03 — `d101d887` (merge into main) dropped the explorer autoplay code of `b52fa939`; its test fails

Found by the Slice 00 baseline (2026-10-13). `b52fa939` ("fix + runtime", 2026-10-13 09:52) added Studio autoplay code — `autoStep`,
`leftKeyAction`, `nextDwell` in `jarvis/runtime/control_center_presentation_studio_explorer_core.js` and play/keys/skip wiring in
`control_center_presentation_studio_explorer.js` — plus `tests/unit/test_presentation_studio_explorer_player_js.py`. The merge `d101d887`
resolved the conflicts in both JS files by keeping `408dc365`'s version (0-line diff against it), so only the test came through:
6/6 tests fail (`C.autoStep is not a function`, …). Every other file of `b52fa939` (voice/live runtime, OAuth) survived the merge intact.

Not fixed in this task: the conflict resolution may have been deliberate (the merged Remotion task reworked the same explorer), and merges into
`main` are the Human's call. **Human decision needed:** port the `b52fa939` autoplay onto the reworked explorer, or retire the test. Until then
the file is treated as an inherited failure by every Slice of this task.
