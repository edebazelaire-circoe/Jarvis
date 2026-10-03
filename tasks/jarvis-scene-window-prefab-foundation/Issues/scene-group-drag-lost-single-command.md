# Page group drag lost its single `translate_selection` command

Found by: baseline fix `fix/scene-baseline-2026-10-03` (2026-10-03). Status: open — not this task.

Merge `fd76479` kept the page from `fix/scene-deplacement-2d` (`057fa0c`, hold
logic computing each member's final position to undo its orbit) and the S3 batch
logic (`53c5d5d`, `orbitGroupDelta` / `commitGroupMove` → one rigid
`translate_selection`). The page now never calls `groupMove`: a group drag sends
one command per object instead of the single command required by
`docs/scene-selection-batch.md` §5.2/§6. The two designs conflict (per-member orbit
correction vs one rigid common move); reconciling them inside `createHoldDesk`'s
`desk.drop` is feature work, or the contract must change.

Evidence: `tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`
still fails after `96c725f` (which fixed the `orbitTurns`/`orbitReach`/`orbitInset`
ReferenceError — never reached by users because the page doesn't call `groupMove`).
Kept on this task's inherited "not yours" list.
