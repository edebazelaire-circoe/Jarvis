# Issue — `runtime/trace.jsonl` interleaved concurrent writes

Found during Slice 00 (2026-09-16), outside this task's scope.

- `RuntimeJournal._append` (`jarvis/runtime/journal.py`) opens/appends/closes with no lock and no rotation; UI, Voice, Core, Claude/Codex adapters and back-brain workers write the same file.
- Live file: 14.4 MB, 13,123 lines, never rotated since 2026-09-03, 15 unparseable fragments (e.g. `}}`) and 1 non-UTF-8 line.
- Impact: diagnostic readers (`trace_summary.py`, `TraceFollower`, `/api/trace`) must tolerate corruption; `read_jsonl_tail` rereads the whole file.
- Not fixed here: the conversation event log must not depend on this file. A separate task should add rotation and a cross-process-safe append.

Related: `docs/BUILD_VERIFICATION.md` is stale (08-31, 107 tests); canonical gate is README/CI `pytest -W error::ResourceWarning` + `scripts/verify_release.py`.
