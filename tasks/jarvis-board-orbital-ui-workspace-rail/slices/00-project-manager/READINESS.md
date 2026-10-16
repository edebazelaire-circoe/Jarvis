# Slice 00 - Readiness

## Declared state

| Item | Value |
|---|---|
| Planning reference | `57f28a7472577f8a193303023a99b026855f09ba` |
| `origin/main` | `57f28a74` (0 commits ahead of planning reference) |
| Task branch | `task/jarvis-board-orbital-ui-workspace-rail`, worktree `C:/Projects/jarvis/bor` |
| Handoff mirror commit | `c8e753e5` |
| Current HEAD | `b956fd49` = merge of `task/jarvis-unified-chat-and-board-drop` `e614669d` (Chat tab/panel, Board drop overlay/tray, moved `.toasts`) |
| Baseline/QA worktree | `C:/Projects/jarvis/boq`, still detached at `c8e753e5`: move it to `b956fd49` before the baseline sweep |
| Drive | handoff still in `to-do`; the Human moves it to `current` |

## Blind-audit summary (verified at `b956fd49`)

Full table with `file:line`: `../../docs/06-resolved-architecture.md` §1 (F1-F26). Corrections to the blind audit:

- `.sc-status` carries five other scene notes; only the hidden-objects note is replaced (F10).
- A canonical per-browser scene view-pref store with a filter-toggle precedent exists (`JarvisSceneView.showEphemeral`, F11).
- Audio capture accepts any input device token, not only the default; enumeration exists only in the Control Center process (F16).
- `docs/boards.md` placement statement is accurate ("top-right; top-left in Cosmos"), not stale (F23).
- Presentation rail dialog rank 9400 and all unified-chat ranks are missing from the registry comment (F3, F4).
- `CONTROL_SELECTOR` already misses `#interactionModeHud`, `#chatTab`, `#presentationRail`, `#boardDropTray` (F24).
- Two more tests couple to `.voicehint`: `test_control_center_chat_ui.py:77`, `test_control_center_chat_browser.py:385` (F25).
- Default theme is `circuit-board`; the user runs Cosmos; the two themes are two layouts (F2).

## Decisions D0-D13

Resolved in `../../docs/06-resolved-architecture.md` §3-§8. Summary:

| D | Resolution |
|---|---|
| D0 | Task Type `waived` |
| D1 | built on `b956fd49`, lands after unified-chat; shell owns chat/drop/toasts placement |
| D2 | `docs/control-center-shell.md` (S01) + `test_control_center_shell_layers.py` parsing base + Cosmos CSS |
| D3 | wheel = new module `control_center_tool_wheel.js`; captures via capture controller; no `data-bh-tool` |
| D4 | secondary = `contextmenu` (right-click, thumb+middle pinch, `ContextMenu`/`Shift+F10`); no long press |
| D5 | Mouse = BH `off` via `JarvisBarehands.disable()`; Bare Hands = HUD `choose('active')` path; no new field; takeover on trusted non-BH pointer events (click immediate; movement path+net within window, tunable, logged); BH tools in the Bare Hands sub-arc |
| D6 | new `GET /v1/captures/targets` (displays + Core-side mics, name tokens); single entry shown as informative only choice; no window/system audio |
| D7 | preview + lightbox Open + Delete with `.cdialog` + Send via Core allowlist widening (`screenshot`, same Session) and `JarvisChat.attachExisting`; Annotate implemented as gated S05.B (derived `screenshot` artifact, `derived_from`) |
| D8 | failed / attention / done / said (canonical); ids kept; `#voiceHint` removed, key hint moves to `.state` description |
| D9 | `showHidden` field in `JarvisSceneView`; ghosts + per-object "Réafficher"; list menu kept on secondary |
| D10 | Stage A preview ref + engine type from Core rail; yellow = additive `unreviewed` key in `rail.json` (no SQLite), set by brain work success, cleared by user `review`; Stage B adapter over `/api/workspace/artifacts` |
| D11 | CHANGED: Board control stays in the top state line as in the approved target; bottom-left fallback specified; Human check HV-08-01 |
| D12 | tiers: S01-S03 ui, S04 critical, S05 ui+adversarial, S06-S09 ui, S10 docs; isolated runtime only |
| D13 | one implementer per worktree; S02 // S07 after S01, S02 merges first |

## Planning repairs

1. "Long-press" wording replaced by the secondary channel (D4) in `README.md` (:56, :57, :143), `docs/01-decision-log.md` (D08), `docs/04-testing-and-quality.md`; SLICE files had none. `06-resolved-architecture.md` wins over `02`/`03` on any conflict.
2. Task Type set to `waived` in `task.json` and every `metadata.json`; `qa_tier` added.
3. S01 scope extended: geometry unification of both themes, `data-shell-control` + shared `CONTROL_SELECTOR`, registry rows for chat/drop/rail-dialog ranks.
4. S04 gains a Core route (`/v1/captures/targets`) and Core relay change; QA tier critical.
5. S05 split into S05.A (preview, Open, Delete, Send) and S05.B (Annotate, gated); Send changes a Core attachment rule -> `agent-trace-analysis` required.
6. S06 removes `#voiceHint` and the `sc-hidden` note; owns the `.voicehint` test migrations.
7. S07 gains Core changes (rail row `preview`/`type`, `unreviewed` key, `review` action); still no SQLite migration.
8. D11 changed (Board stays top state line); S08 no longer moves `#boardsHud` unless the Human picks the fallback.
9. Dependencies refreshed: S06 depends on S01 and S04 (recording indicators); S08 depends on S06, S07; S09 on S03-S08.
10. Issues to be opened by their slice if triggered: `bh-left-reveal-gesture.md` (S02), `barehands-return-latency.md` (S03, only if > 3 s), `screenshot-annotate.md` (S05, only if S05.B fails).

## Blockers

None found. Non-blocking dependency: unified-chat must land in `main` before this task lands (D1).

## Verdict

**READY** (pending agent 0 review and the baseline sweep below).

## Baseline failures

Wide sweep at the branch point `c8e753e5` (= `origin/main` 57f28a74 + mirror), worktree `boq`, isolated `JARVIS_DATA_ROOT`, foreground chunks, HEAD checked before/after each chunk. Totals: unit 804 files — 21 493 passed, 19 failed (13 reproducible, 6 flaky), 123 skipped; integration 76 files — 650 passed, 1 failed, 26 skipped; e2e 1 passed.

**Reproducible at the branch point — not this task's, do not fix:**

| File | Test(s) | Cause |
|---|---|---|
| `tests/unit/test_app.py` | `test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings` | stale fixture (`SimpleNamespace` lacks `data_root`) |
| `tests/unit/test_barehands_interaction_js.py` | `…practice_frame_is_moved_by_one_zone…`, `…practice_frame_resizes_only_on_two_distinct_compatible_zones` | geometry drift |
| `tests/unit/test_brain_capability_parity.py` | `test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt` | `ui_intent_publish` undocumented |
| `tests/unit/test_brain_delegation.py` | `test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` | voice prompt gained a settings section |
| `tests/unit/test_scene_artifacts.py` | `…other_prompts_are_byte_identical` | prompt hash drift |
| `tests/unit/test_scene_query_tools.py` | `…other_prompts_stay_byte_identical` | prompt hash drift |
| `tests/unit/test_control_center_voice_architecture.py` | `test_async_browser_render_does_not_restore_a_previous_panel` | `agenda_reminders` undefined |
| `tests/unit/test_scene_group_drag_js.py` | `test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged` | source fragment no longer present |
| `tests/unit/test_tool_brain_choices.py` | `test_ui_projection_is_consistent_in_the_single_metadata_copy` | `memory_propose` reversibility |
| `tests/unit/test_tool_brain_intents.py` | 3 tests | `BrainOrchestrator.publish_ui_intent` missing |
| `tests/unit/test_memory_context.py` | `test_recall_over_2000_notes_…_stays_in_budget` | 30 s readiness timeout (load-sensitive) |
| `tests/integration/test_settings_redesign_migration.py` | `test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation` | assembled JS SyntaxError |

**Flaky under load (passed alone):** `test_control_center_timeline_browser.py` (3), `test_presentation_render_service.py` (1), `test_self_dev.py` (1), `test_wake_word_settings_browser.py` (2).

**Inherited from the unified-chat merge (`b956fd49`), measured by the S01 implementer before its change:** `test_interaction_mode_hud_browser.py` 3, `test_workspace_presentations_js.py` 1. (`test_boards_hud_browser.py` 6 and `test_control_center_chat_browser.py` 9 were also red before S01 and S01 made them green.)

**Environment:** browser tests leave ~12 MB Chrome profiles in `%TEMP%\jarvis-*-cdp-*`; 1 106 (~14 GB) filled C: during the sweep. Every agent cleans its own profiles after a run.
