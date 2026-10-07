# The presentation stager's `reveal` calls a method that does not exist.

Found by: Slice 00 audit (2026-10-03). Status: open.

`jarvis/runtime/presentation_staging.py:100` calls `self._tools.set_visibility(object_id=..., visibility=...)`, but `SceneDisplayTools` (`display_mcp.py:726`) has no such method; its own docstring (line 26) admits `scene_set_visibility` is granted nowhere. Production `reveal` would raise `AttributeError`. The unit tests (`test_presentation_speculative.py:1073`, `test_presentation_integration.py:860`) use fakes and don't catch it. The fix belongs to the Presentation task: route through `update_object(visibility="visible")`. Not fixed here because it touches presentation behaviour.
