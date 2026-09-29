# Per-Board scene isolation (deferred from V1)

- Found at Slice 00 (2026-09-29). The scene is one global constellation: `scene_meta` is a singleton (`jarvis/adapters/sqlite_scene.py:125`) and `WorkRef` carries no Board (`jarvis/domain/scene.py:475`).
- V1 decision (agent 0): each Board stores `scene_ref={"kind":"global",...}`; the scene stays shared across Boards. The README asked for "scene/workspace state or references": V1 meets the "references" branch only.
- Real isolation needs Board attribution in the scene projector plus a per-Board scene store (or a board column and filtered projection). That is a Slice of its own.
- Human-visible consequence: after switching Board, the constellation still shows the other Board's objects.
