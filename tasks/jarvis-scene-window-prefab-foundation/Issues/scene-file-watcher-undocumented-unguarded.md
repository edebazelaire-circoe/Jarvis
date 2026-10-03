# `SceneFileWatcher` has no path guard (documentation part resolved).

Found by: Slice 00 audit (2026-10-03). Status: **partly resolved** (Slice 09 re-check, 2026-10-03) — open for the guard and the actor.

- Resolved upstream (origin/main `c57cc65`, `085928d`, merged into this task at `1523823`): the watcher is
  documented in `docs/scene-model.md` › *Windows bound to a file*, and it is now event-driven
  (`FileChangeNotifier`, `ReadDirectoryChangesW`, no 1 s polling).
- Still true (re-read of `jarvis/core/scene_file_watcher.py` at `1523823`): it reads any absolute
  `payload.source_path` it is given, with no `safe_folders` or data-root restriction, and it rewrites
  `summary` through a `patch_object` as actor `brain`, so its writes look like the brain's in diagnostics.
- Prefab windows: the watcher copies the payload with `replace(payload, summary=…)`, so a prefab block is kept
  unchanged and is not revalidated (D-SCENE "unchanged block"). No change needed for prefabs.
- Remaining decision (not this task): guard the path (data root, Documents, or an allow-list) and give the watcher
  its own actor or a `runtime` origin. A later option is binding `source_path` to a `jarvis.document` `data.body`.
