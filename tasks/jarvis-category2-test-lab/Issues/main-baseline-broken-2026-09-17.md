# origin/main baseline broken (2026-09-17)

Found by Slice 00. The Test Lab didn't cause this.

1. `jarvis/runtime/realtime_audio.py` lines 1095–1114 contain committed merge-conflict markers (commits `c914f7d`, `d7e9ca4`). The module doesn't parse, so every import of the voice stack fails. The fix, which keeps both helpers, already exists on `task/jarvis-constellation-scene-runtime`.
2. With (1) resolved, 9 unit tests still fail on `main`:
   - `tests/unit/test_agent_routing_settings.py` ×3: `jarvis.runtime.agent_routing.group_by_harness` missing; `KeyError: 'harnesses'`
   - `tests/unit/test_routing_settings_screen.py` ×4: page source assertions
   - `tests/unit/test_brain_card_state.py` ×2: menu item source assertions

   These look like a test/implementation mismatch introduced by the 2026-09-17 `10b455e` merge on routing and brain-card UI work.

Owner: outside this task. (1) is a precondition for this task's baseline (see READINESS D1). (2) is recorded as the known baseline, so these failures aren't counted as Test Lab regressions.
