# Issue — scene-model doc overstates error-message bound

Found by Slice 01 QA re-verification (non-blocking nit).

`docs/scene-model.md` says refusal messages "never echo more than 80 characters of a received value". Patch replay and relation errors echo already-validated ids up to 128 characters (`jarvis/domain/scene.py` ~700, ~1026, ~1030). Bounded, but not to 80.

Also: `test_scene_module_is_pure_domain` allows importing `jarvis.domain._checks` but does not parse `_checks.py` itself (it imports only `re` today).

Resolution target: Slice 11 documentation pass (or any earlier Slice touching `scene.py` docs/tests).
