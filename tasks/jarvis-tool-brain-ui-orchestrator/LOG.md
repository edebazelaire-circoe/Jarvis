# Execution Log

Reserved for implementation agents to record durable execution notes. No implementation progress has been recorded at task creation time.

## 2026-10-07 — Slice 00 (agent 0)

- Lifecycle doc absent; Drive IDs + `main` base used (see slices/00-project-manager/READINESS.md). Branch `task/jarvis-tool-brain-ui-orchestrator` from origin/main 085928d.
- Handoff mirrored from Drive (45 files) as S0. Task Type: all Slices set to `waived` (standing Human waiver, to be confirmed).
- **Inherited-red baseline @ 085928d** (not ours, do not fix): unit 384 files = 11709 passed / 10 failed / 13 skipped; integration 72 files = 629 passed / 1 failed / 23 skipped. Failing:
  - tests/unit/test_app.py (1) `..._tools_gateway_target_built_from_core_settings` — fake settings lack `data_root`
  - tests/unit/test_barehands_interaction_js.py (2) practice-frame move/resize geometry
  - tests/unit/test_brain_delegation.py (1) `test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` — golden prompt text
  - tests/unit/test_interaction_mode_hud_browser.py (1) `test_le_mouvement_reduit_arrete_vraiment_le_halo`
  - tests/unit/test_scene_group_drag_js.py (5) `ReferenceError: orbitTurns is not defined` at jarvis/runtime/control_center_scene_interact.js:1414 (real bug in scene interaction; relevant to Slice 07 scene adapters — report, do not fix inside unrelated Slices)
  - tests/integration/test_scene_transport.py (1) `test_stopping_the_server_releases_a_pending_long_poll` — possibly flaky (each chunk run once)
- State: **READY**.

## 2026-10-07 — Slice 04 (implementer)

- Speech progress = read-only projection (`jarvis/runtime/tool_brain_speech.py`), UI intent = typed tool `ui_intent_publish` on `jarvis-display` -> Core `POST /v1/ui-intents` -> event `brain.ui_intent.published` (`docs/tool-brain-contracts.md` §10-12). Brief block derived from `ToolMeta`, mode `jarvis_direct` (observation) until S8.
- Test-pin updates owed to the new tool (display 19 -> 20 tools, +1 225 B): `test_mcp_catalog`, `test_control_center_mcp_api`, `test_scene_query_tools`; `ATTRIBUTE_KEYS` +3 (`paragraph`, `ref_count`, `timing`).
- Inherited reds unchanged: `test_brain_delegation` golden prompt (1), `test_app` (1); no new failure in the 153 unit files touching the changed modules.

## 2026-10-07 — Slice 05 (implementer)

- Tool Brain runtime in shadow mode (`docs/tool-brain-contracts.md` section 13): port `ToolBrainDecider` (G8 closed), `ToolBrainRuntime` (wake classes, coalescing, rate limit, safety tick that only pays on a changed perception digest, bounded inspection loop, fresh-state `validate_call`, supersession, backoff, bounded decision log), `ModelToolBrainDecider` + `RuleToolBrainDecider`, Core wiring behind `JARVIS_TOOL_BRAIN` (default `off`).
- Core change: one neutral hook `ConversationEventEmitter.add_listener` (wake source). Main brain untouched.
- Inherited reds unchanged: `test_app` (1, `data_root`). No new failure in the 16 files run (architecture, tool_brain_*, emitter, control_center_quality, documented_routes, live_idle_composition, config).
- Not done here (by design): no real-model trace (needs a Claude native CLI and a live session; S10), no execution (S6), no timeline events (S9), Core-side speech section not wired (no SpeechScheduler in Core).

## 2026-10-07 — Slice 06 (implementer)

- Action queue + executor + `active` mode (`docs/tool-brain-contracts.md` section 14): ephemeral bounded queue (`tool_brain_queue`, speech/intent/event/delay triggers, add/cancel/replace/reprioritize/reschedule/inspect, idempotent ids, thrash guard, expiry on every wait), `UiActionExecutor` (`tool_brain_executor`: gate, fresh-state `validate_call` + preconditions, adapters `scene_move` via `SceneService.apply_if` and `board_switch` via `BoardService.switch(origin="brain")` with the `scheduled` status), runtime pump + invalidation replan (bounded streak), authority-change flush. `JARVIS_TOOL_BRAIN=active` is the only way to execute; `tool_brain_ownership` still `jarvis_direct` (S8).
- Test pins updated: `test_tool_brain_runtime` (modes), `test_tool_brain_wiring` (`active` is now a mode). Inherited reds untouched.
