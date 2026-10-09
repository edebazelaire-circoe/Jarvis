# Issue 01 - Debt inherited from `jarvis-interactive-presentation-studio` (not caused by this task)

Opened by Slice 01 (2026-10-09, base `main` de7b9c59). None of these blocks the Remotion work; none is repaid by it unless the PM says so. Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit".

| # | Debt | Evidence | Blocks Remotion? |
| --- | --- | --- | --- |
| 1 | Original Slice 15 (rehearsal) has no round of its own: no section-loop / restart-a-section command, no rehearsal runbook | `docs/presentation-studio-release.md:8,119`; closed playback event enum `jarvis/domain/presentation_studio_playback.py:73-96` | No |
| 2 | Old task `slices/TODO.md` is stale (15 and 18-22 unchecked although 18-22 are merged) | `tasks/jarvis-interactive-presentation-studio/slices/TODO.md`; commits `7fd422ee`, `ddf1a8c0`, `0bd43312` | No (do not edit the old task from here) |
| 3 | No QA round recorded for old Slices 19, 20, 21 | `docs/presentation-studio-release.md` status table rows 19-21 | Slices 19 and 21 of this plan build on 20 and 21: treat their behaviour as machine-tested only |
| 4 | Physical Human checks H-1..H-11 open (projector, microphone, audible presenter, screen reader) | `docs/presentation-studio-release.md:100-119` | Slice 22 of this plan must not claim them |
| 5 | Slice 18 polish items P1, P8-P10, F5, F7-F9 left open | old task LOG, `QA-1.md` | No |
| 6 | Tool context budget of `jarvis-presentation` almost full (limit 17 100 B, about 16 849 B used) | `tests/unit/test_mcp_catalog.py:233`; old LOG | Yes for Slice 21 (new verbs need another server/category or a deliberate budget change) |
| 7 | Red tests on `main` (see `slices/01-final-branch-conformance/BASELINE.md`): "not ours, do not fix" | BASELINE.md | No |
