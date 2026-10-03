# `SceneFileWatcher` is undocumented and has no path guard.

Found by: Slice 00 audit (2026-10-03). Status: open.

`jarvis/core/scene_file_watcher.py` re-reads `payload.source_path` about every second and rewrites `summary` as actor `brain`. Nothing in `docs/` describes it (only its docstring and a `v2_app.py` comment). It reads any path given, with no `safe_folders` or data-root restriction. Its writes are logged as `brain`, which muddies diagnostics. It needs a `docs/scene-model.md` section and a decision on guarding the path and on its actor identity. A later option is binding `source_path` to a `jarvis.document` `data.body` (follow-up, not here).
