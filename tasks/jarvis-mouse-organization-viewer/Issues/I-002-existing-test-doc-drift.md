# I-002 — Existing test/documentation drift around scene hold and rail layers

Independently reproduced in PM integration worktree containing only S01 Python changes; scene JS and shell docs remain baseline c0858a80.
Command: main venv Python -m pytest --assert=plain --tb=short -q tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged tests/unit/test_control_center_shell_layers.py::test_every_rank_in_css_matches_the_registry.
Result:2 failed in3.33s.
- group source test line128 searches obsolete inline onPointerUp branch; current baseline commits via canonical desk.drop. ValueError substring not found.
- layer registry test reports existing control_center_presentation_rail.js selector #${DOM.hostId} .jvr-play rank1 not listed in docs/control-center-shell.md.

Disposition: pre-existing test/doc drift, not S01/S02 regressions. Batch small test/registry hygiene in S06 if useful; no product defect established here.

Resolution2026-10-30: PM added the missing canonical contained-rank row for existing rail play indicator. Complete shell layer suite now12 passed14.33s. No CSS/product behavior changed. Obsolete group source assertion remains release polish.

## S05 atomic group-drag correction (2026-10-30)
PM traced canonical hold path beyond old menu/pointer helpers: createHoldDesk.drop currently loops handle.ids and calls injected d.commit once per member; scene page injects commitUserGeometry only. The known group-drag test therefore points to a real lost atomic behavior, not solely a stale assertion. Earlier readiness wording was incomplete. This task's atomic multi-object/user-manipulation contract requires correction in S05, not deferral as pre-existing.
Extend the SAME shared hold commit seam to submit all eligible group target boxes once through S01's canonical atomic operation (or existing canonical translation when mathematically appropriate). No second gesture engine or manual per-object mutation loop. Preserve hold release, common movement/offsets, user pin semantics, pending/rollback and payload bounds. Unknown/stale required member refuses whole set. Actual browser+Core/SQLite scenario must show one group gesture -> one command and at most one revision, including orbit/fixed behavior. Update canonical docs/static conformance to landed seam; remove old known-failure entry only when corrected test and live behavior pass. S05 tier remains UI plus atomic integration checks; backend critical semantics already verified in S01.

