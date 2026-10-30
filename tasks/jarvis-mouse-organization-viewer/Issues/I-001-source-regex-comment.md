# I-001 — Existing source-regex false positive in interaction test

Observed on untouched baseline origin/main c0858a80, isolated mov worktree before any product edits.
Command: main .venv Python -m pytest -q tests/unit/test_scene_interaction_logic.py::test_the_page_serves_the_interaction_logic_and_never_uses_browser_dialogs --assert=plain --tb=short -p no:cacheprovider.
Result: 1 failed in 6.55s, test line 543. Regex finds browser-dialog-looking calls inside comments. Actual match in served page: comment describing in-page confirmation says "jamais confirm()". No actual native dialog call established.

The broader baseline test_scene_batch.py + test_scene_interaction_logic.py + integration/test_work_cancel_protocol.py reached 100% with one F, then rendered the huge injected HTML assertion for minutes; stopped only that owned pytest session. No completed aggregate count claimed. Plain assertions bounded rendering; use --assert=plain --tb=short for broad final validation when giant served-page assertions fail.
Disposition: pre-existing test defect, not feature regression.

Resolved in S06: shared `tests/fakes/javascript_source.py` extracts executable
HTML script/handler text with stdlib HTMLParser and reuses canonical
`remotion_import.strip_comments`. The original forbidden-call guard now checks
comment-free source and reports only compact matches. Focused regression tests
prove real alert/confirm/prompt calls (including window/whitespace forms) remain
detected, while comments, prose, URLs and legitimate methods do not fail. The
formerly failing served-page test passes with the focused source/layer/group/
viewer batch (31 passed, 15.76 s).

