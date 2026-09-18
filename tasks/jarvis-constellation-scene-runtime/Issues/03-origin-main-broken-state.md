# Issue — origin/main f7e33ad is in a broken state (outside this task)

Found during the 2026-09-17 integration of main into the task branch.

1. **Committed conflict markers** in `jarvis/runtime/realtime_audio.py` (lines ~1095–1114 on `origin/main`, from the "sauvegarde avant refresh" merge d7e9ca4). The module does not import on main → voice runtime broken for anyone checking out main. Fixed on this task branch only (`e68cfdc`, both sides kept).
2. **9 committed tests without implementation** (sauvegarde commits d7e9ca4 / 56c7892): `tests/unit/test_agent_routing_settings.py` (3, `group_by_harness` missing), `tests/unit/test_brain_card_state.py` (2), `tests/unit/test_routing_settings_screen.py` (4). They fail identically on a clean export of f7e33ad, so `scripts/verify_release.py` is red on main and on this branch.
3. Known flaky `test_three_turns_run_in_one_session_without_a_second_wake` (main already tracks it).

Consequence for this task: the release gate is now "no failure beyond these 10 main-baseline failures". Human action needed on main.


Update 2026-09-17: item 1 fixed on main by `b86f228` (same resolution as this branch's `e68cfdc`; merged as `c12773c`, no content change). Items 2 (9 tests without implementation) and 3 (flaky) still open on main.

Update 2026-09-18: items 2 and 3 addressed on branch `fix/main-baseline-and-timeline` (worktree C:\Projects\jarvis-mainfix, HEAD `24d32d6`). The 9 tests had lost their implementation in merge `10b455e` (one side dropped: 41 lines in `agent_routing.py`, 94 in `control_center.html`); restored byte-exact from `90d3234` and `56c7892`. Full chunked suite on that branch: 0 failures. Two timing-fragile files remain (`test_live_primary_lease_review.py`, `test_back_brain_tasks.py`), unrelated, each failing once across two QA rounds and passing on every rerun.
