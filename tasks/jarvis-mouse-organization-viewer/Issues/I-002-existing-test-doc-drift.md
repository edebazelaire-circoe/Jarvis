# I-002 — Existing test/documentation drift around scene hold and rail layers

Independently reproduced in PM integration worktree containing only S01 Python changes; scene JS and shell docs remain baseline c0858a80.
Command: main venv Python -m pytest --assert=plain --tb=short -q tests/unit/test_scene_group_drag_js.py::test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged tests/unit/test_control_center_shell_layers.py::test_every_rank_in_css_matches_the_registry.
Result:2 failed in3.33s.
- group source test line128 searches obsolete inline onPointerUp branch; current baseline commits via canonical desk.drop. ValueError substring not found.
- layer registry test reports existing control_center_presentation_rail.js selector #${DOM.hostId} .jvr-play rank1 not listed in docs/control-center-shell.md.

Disposition: pre-existing test/doc drift, not S01/S02 regressions. Batch small test/registry hygiene in S06 if useful; no product defect established here.

