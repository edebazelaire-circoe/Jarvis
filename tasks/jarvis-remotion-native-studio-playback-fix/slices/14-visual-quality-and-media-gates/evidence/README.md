# Slice 14 evidence

Files of the delivered run (`summary.json` names the SHA, runtime, commands and durations): `gate-*`, `native-*`, `control-*` (smoke
path on the render host), `flow*` (the recorded 9-scene play), `flow-negative-control.json` (planted flash and held slider).

## Rework

Frozen-scope rework (branch `fix/rnsp-s14-rework` from 0cde0e05). Unit files run one per process.

| Item | Change | Test | Mutant (killed) |
| --- | --- | --- | --- |
| B1 | `release_gate`: an empty (black / blank) FIRST frame blocks; the first-frame exemption is kept for `authored` only (`_empty_severity`) | `test_an_empty_frame_blocks_by_role_and_profile[first-release_gate-blocking]` (+ `exit-release_gate`) | old `if role is FIRST: warning` -> 1 failed |
| P1 | `edge_clipped` / `edge_text_overflow`: a run of ink along a side that touches a corner and whose texture is below `corner_run_texture` = 0.05 is a full-bleed bar and does not count (generic, not a gate-specific band) | `test_a_smooth_bar_from_a_corner_of_a_side_is_not_content_cut_by_it` (full, growing from the left, ending at the right), `test_a_corner_run_that_is_textured_or_a_smooth_block_away_from_the_corners_is_still_reported`, the existing block-cut-by-the-right test | no skip -> 3 failed; skip any smooth run (no corner condition) -> 2 failed |
| P2 | none (the detector already flagged any blank capture) | `test_transition_flash_a_one_frame_white_or_grey_flash_blocks_too` (white 255, grey 128) | black-only flash -> 2 failed |
| 4 | none | `test_a_frozen_span_only_counts_pairs_of_captures_that_both_play` (paused 0-2000 ms then 900 ms playing; playing then paused) | `playing_a or playing_b` -> 1 failed |
| P3 (S12 polish) | `enforce_shape`: `node_modules/.cache` stays only as a REAL folder; a `.cache` link or junction is set aside and reported like any link (its target is never wiped by `launch`); `docs/remotion-studio.md` says so | `test_a_junction_planted_as_the_tool_cache_is_set_aside_and_its_target_never_wiped` | runner at 0cde0e05 -> 1 failed |
| P4 | flow transition sheet paired by `transition_captures`: the end of scene k is the last capture bracketed by two reads of k (the read comes just before the pixels), the start of k+1 the first capture read on k+1 | `test_a_transition_pair_never_takes_the_capture_read_just_before_the_hand_over` (pure, runs without the runtime) | old pairing `(i - 1, i)` -> 1 failed |
| P5 | `test_task_evidence_privacy` covers only the prefab-foundation task; the Slice 13 sweep (`test_native_parity_evidence_privacy.py`) is now parametrized over Slice 13 AND this Slice 14 folder | `test_no_committed_file_of_the_slice_keeps_...[slice-14]` | a planted home path in `evidence/` -> 1 failed |

Unit results (rework tip): `test_frame_quality` 45 passed; `test_frame_quality_docs` 6; `test_remotion_media_tools` 12 (with the
runtime); `test_remotion_studio_shape` 15; `test_remotion_studio_runner` 22; `test_remotion_studio_docs` 10;
`test_native_parity_evidence_privacy` 4; `test_presentation_flow_quality_browser` 1 passed, 2 skipped (no runtime: the pure pairing test).

**Real runs: NOT done in this rework.** The gate smoke was started once (runtime = a copy of the read-only gate runtime under a short
temp folder, isolated stack): every preview answered 507 `presentation_render_disk_low` ("18 MiB free, a render needs at least 1536
MiB"): drive C: was full (0 to 22 MB free) for reasons outside this rework. So the gate count after the corner rule (target 0 of 45),
the gate's first frame under the blocking rule, the control deck and `flow-transitions.jpg` are still to be re-measured once disk space
is back; the delivered files above are unchanged. Expected from the measured metrics: every one of the 27 gate findings was the bottom
side at ink share 0.49 to 1.0 with texture 0.006 to 0.013 (the bar), which the rule skips; the gate's first frames have edge density
0.004 (text), above the blank threshold; the control deck's clip is text (`edge_text_overflow`, texture 0.73, mid-side), not a corner run.
