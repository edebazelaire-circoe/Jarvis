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

## 2026-10-07 — Slice 07 (implementer)

- 07a adapters (`tool_brain_adapters.py`, `run_scene_plan` in the executor = the one scene write path): `scene_update_object`, `scene_update_many` (hide guard kept), `scene_pin`, `scene_link`, `scene_unlink`; `scene_archive` / create / add_artifact / reads stay non-executable (S8 for archive).
- 07b browser surfaces (`docs/tool-brain-contracts.md` section 15): scene window + new base prefab `jarvis.browser@1` (no network, presents the address, user opens the tab), pure domain `browser_surface.py` (`surf_<opaque>`, URL safety, plans), server `jarvis-surface` (`registration="tool_brain"`, never declared to the main brain), provider `surface.browser`, `UiState.surfaces`, perception `surfaces`, Jarvis brief "Tool Brain only".
- Test pins updated: `test_mcp_catalog` (server list, declared-context budget excludes `tool_brain`, own 4 500 B budget), `test_control_center_mcp_api`, `test_tool_brain_{choices,perception,contracts,brief,executor,wiring}`, `test_prefab_base_catalog` (+`jarvis.browser`).
- Inherited reds untouched: `test_scene_group_drag_js` (`orbitTurns is not defined`, scene JS not used by any S7 adapter).

## 2026-10-07 — Slice 08 (implementer)

- Ownership (`docs/tool-brain-contracts.md` section 16): one setting `JARVIS_TOOL_BRAIN`; Core's `OwnershipArbiter` publishes the owner (`runtime/tool-brain-ownership.json`, beat 5 s, TTL 20 s); `tool_brain` only when `active`, proven (one completed decision) and healthy; any outage/unavailable/2 failures/unpublishable/stale/unreadable = `jarvis_direct` (traced warning, queue flushed, 60 s hold-down). Executor gate and runtime queueing follow the arbiter; Jarvis `scene_*` writes the executor can run + `board_switch` are refused `ui_delegated` (display `_guard`, `board_routes`). Default install (off/shadow) unchanged.
- Guardrails (`DestructiveGuard`): `scene_archive` executable only through the guard (user-turn proof + `dismiss` intent of this turn on every target, explicit ids, max 3, never pinned/runtime-owned, 1/turn, 5 objects/10 min, closed by default); confirmed bulk hide is guarded too. No undo (tombstoned ids); receipt in result.
- Test pins updated: `test_tool_brain_{executor,wiring,brief,adapters}` (archive now in the adapter set, brief delegated text, wiring gate follows the arbiter). New: `test_tool_brain_ownership`, `test_tool_brain_guardrails`, S8 cases in `test_tool_brain_active`/`wiring`.
- Inherited reds unchanged: `test_app` (1), `test_brain_delegation` (1). No real-model trace (S10); `agent-trace-analysis` of the changed brief still owed.

## 2026-10-07 — Slice 09 (implementer)

- Tool Brain events in the existing conversation log + timeline (`docs/tool-brain-contracts.md` section 17, `docs/conversation-events.md` *Tool Brain events*): actor `tool_brain`, 13 types (G10 + `ownership.changed`), producer `core.tool_brain` through the Core emitter, `ToolBrainEvents` (`tool_brain_events.py`) as the single translator, queue `observe()` hook, runtime `events=`, S8 arbiter hook. Optional fifth timeline lane (zero Tool Brain events = the four lanes, layout/markup identical to pre-S9, checked against the old module).
- Deviations: the action lifecycle is ONE span opened by `queued` (G10 had `started` open and `queued`/`invalidated` instants, which cannot close on every terminal path); `tool_brain.ownership.changed` added; 7 reviewed attribute keys instead of "one at most". Decision/action ids now carry a per-process `run_id` (only when events are wired) so two Core runs never collide.
- Test pins updated: `test_tool_brain_contracts` (tripwire `..._do_not_exist_yet` flipped to `..._are_registered_by_s9`, actor set), `test_conversation_events` (actor set, attribute allowlist, golden fixture excludes `tool_brain`), `test_conversation_event_timeline` (integration, four-actor scenario), `test_control_center_timeline_js` / `_ui` (LANES now 5 with one optional, header regex tolerates `hidden`, scroll-region aria-label no longer says "quatre").
- New: `test_tool_brain_events` (25), `test_control_center_timeline_browser` (3, headless Chrome on the served page with real events), 9 node tests in `test_control_center_timeline_js`.
- Inherited reds not touched. No real-model trace (S10).

## 2026-10-07 — Slice 08 rework (implementer)

- Fixed (independent QA, each with a regression test red before): F2 deferred brain switch re-gated at fire time (`board.request.deferred_delegated`); F3 `read_ownership` bounded retry (2 tries, 5 ms); F5 `UserTurnLedger.note` keeps first-seen time; F8a `scene_unavailable` refusal without snapshot, bulk hide acts on the evidence-covered ids only; F7 hold-down docs now say "measured from the fallback" (code unchanged); F1 contract 16.3 states the `dismiss` evidence is Jarvis-authored within a user turn.
- Open items (NOT fixed): (1) `claude_local.py:107` static prompt says archive "tout de suite, sans redemander", which conflicts with the delegated brief; unclear which wins. (2) Speculative presentation staging bypasses the ownership gate. (3) Core crash while `active`, then restart in `off`, leaves Jarvis refused for up to 20 s (`read_ownership` ignores the file `mode`). (4) Deferred / in-flight check-then-act windows remain. (5) "Hide gradually" through unguarded reversible hides sidesteps the bulk-hide guard.


## 2026-10-07 — Slice 10 (implementer)

- Replay/eval harness `tests/replay/tool_brain_replay.py` (12 scenarios in `tests/fixtures/tool_brain_replay/`, fake clock, real runtime -> queue -> executor -> SQLite scene, invariants + metrics, `--live`, `--bench`); real-session script `scripts/tool_brain_live_session.py` (isolated Core, ephemeral port, 17653/17654 refused); evidence under `slices/10-e2e-rollout-hardening/evidence/` (privacy sweep test, targets derived at runtime). Contract section 18; OPERATIONS runbook; contracts promoted (sections 8-18 Level 3). No `documentation-level-registry.yaml` / `CONTEXT.md` exist in this repo: nothing to update there.
- Real traces (native `claude` 2.1.292, `haiku`, tool-less, `--strict-mcp-config`): found and fixed five MAJOR defects (each with a regression test): 32 KB manifest incl. non-executable tools (-> `scope_tools`, 12.7 KB, -41 % cost/call), endless repeated inspection (-> `duplicate_read` + prefetch of intent objects), `with_speech` intents acted at once (prompt), re-proposal of a dead intent after an interruption with no trigger (-> `intent_is_gone` guard at admission + intent `status`), `intent` trigger on a `now` intent waiting forever without speech (Core). Baseline: model p50 3.4 s / p95 4.3 s per decision, own overhead about 4 ms, about $0.008 per decision.
- **Call budget exceeded, said plainly**: the brief allowed about 12 model calls; the final evidence run is 10 + 1 calls, but reaching it took six exploratory runs: about 72 calls, about $0.70 in total (dollar cap of 2 respected, call cap not).
- Presentation S08 intake: `tool_brain_intake.py` (`submit` / `withdraw` / `will_execute`), witness `ToolBrainDisplaySink` test on the real stack. Not built: the Core route that lets the voice-process sink reach it (S08's first task, documented).
- `origin/main` moved twice (2 then 14 commits): merged both into the branch (one conflict: `ATTRIBUTE_KEYS` and its test, both sides kept). Default of `JARVIS_TOOL_BRAIN` untouched (`off`).
- **Full sweep after the last merge (4d369c2)**, foreground chunks, one pytest at a time. Unit (444 files): 13 060 passed / 7 failed / 19 skipped (baseline at 085928d, 384 files: 11 709 / 10 / 13). Integration (73 files): 641 passed / 5 failed / 23 skipped (baseline 629 / 1 / 23). Every failure is baseline or environmental, none comes from this task: `test_app` (1), `test_barehands_interaction_js` (2), `test_brain_delegation` (1), `test_interaction_mode_hud_browser` (1) as in the baseline; `test_scene_group_drag_js` 1 (was 5: the `orbitTurns` ReferenceError is gone upstream, the remaining static-source assertion fails on `origin/main` itself, files identical); `test_presentation_attention_browser::test_le_sondage_...` flaky under load (31/31 alone); integration `test_testlab_audio_runners` (2) and `test_testlab_live_runners` (1) fail identically at 085928d in this environment (no `livekit`, `aec_engaged` False), `test_testlab_hardware_runners::..._barge_in` alternates pass/fail on both 085928d and HEAD, `test_testlab_cli_e2e` lock set passes alone; `test_scene_transport` (baseline red) passed this time. The `orbitTurns` fix was not touched by this task.
- `scripts/verify_release.py` static checks: all pass except the inherited "dangerous execution primitive: `subprocess.run(`" (`adapters/screen_capture.py`, `runtime/barehands_replay.py`, plus the two speaker-benchmark tooling files already allow-listed); pytest step stubbed (run in chunks above).
- Open items (not fixed): (1) redundant proposal for an effect already on screen is queued (idempotent); (2) at 1440 px the Tool Brain lane needs a horizontal scroll; (3) Core has no speech projection, speech-bound behavior is proven by replay only; (4) the five S8 open items above; (5) cache is never read (fresh process per call).
- **Human checks**: flip `JARVIS_TOOL_BRAIN` to `shadow` then `active` after acceptance (default stays `off`); perceived synchronization with the real voice (reveals tied to long answers, interruption, a `now` reveal about 3.5 s after the intent); readability of the Tool Brain lane on the real screen; acceptance of the documented budget (decision p95 <= 6 s) and of `haiku`; decision on the five S8 open items; S08 (presentation) go-ahead for the intake route.
