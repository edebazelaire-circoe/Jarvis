# Slice 00 — Readiness report

- Date: 2026-09-28
- Branch: `task/jarvis-voice-stale-speech-presentation`, created from `origin/main@202333d` (= planning snapshot; no `dev` branch exists in this repository)
- Handoff origin: remote (Drive `to-do/jarvis-voice-stale-speech-presentation`, id `1vUWdSQcUDmzplnu-VlRWqSHtjjf2zGwd`). The Drive connector cannot move folders: the Human moves it to `current`.
- Mirror: 32 files, byte-identical to Drive, committed as `2cd9fd6 S0`.

## Declared state

**`READY`** — decided by agent 0 (Human delegated autonomy, 2026-09-24).

- D1. Workspace Task Type gate waived; `task_type` stays `null` in every Slice metadata (fifth waiver of this kind).
- D2. Planning blocker "session of 28/09 not in any local journal" is **void**: it is in the main journal (see B2). No Human question needed.
- D3. Baseline evidence = main journal read **without its WAL** (see B3), over 2026-09-18..21 and the 28/09 session.

## B1. Blind audit — the six README facts

Audit made by an Explore agent forbidden to open `tasks/`, before reconciliation. Lines at `202333d`.

| # | README fact | Verdict | Evidence |
|---|---|---|---|
| 1 | Live never emits `realtime.response_done`; `_await_output` only released by it | **Confirmed**, and worse | `LiveFrontendSession._legacy_events` (`live_frontend_session.py:455-495`) emits no `response_done`; `_await_output` `speech_scheduler.py:2147-2178`, release `:1006-1016`. Additionally Live outputs are named `live-output-<uuid>` (`adapters/openai_live_frontend.py:408,428`) while the scheduler reserves its own uuid (`:2045`), so `_output_still_alive` never matches either: every Live speech returns after the first 30 s timeout with `status="unknown"` → `INTERRUPTED/delivery_not_complete` (`:2122-2130`) and its chain blocked. `_note_live_output_quiescent` (`realtime_audio.py:2767-2806`) only reaches the surface (`_rest_surface`). |
| 2 | `_eligibility` carries over RESULT/QUESTION/ERROR of past intents | **Confirmed** | `speech_scheduler.py:1484-1511`, `TRANSIENT_SPEECH_KINDS` `domain/v2.py:422` |
| 3 | Selection by priority then created_at → older answer first at equal priority; comment says the opposite | **Confirmed** | `_pop_next` `:1777-1788`; `ordering_key = (-priority, created_at)` `domain/v2.py:511-514`, intent absent from the key; comment `:1492-1504` ("après ce que celle-ci a déjà en file") and Decision 47 contradicted |
| 4 | Core hands replies to the brain while they stay speakable (race) | **Confirmed** | `_take_pending_replies` `brain_service.py:993-1032`; nothing invalidated with the flag off (`:1028-1029`); entries popped from `_spoken_works` → handed only once, even if still unsaid |
| 5 | `announce_notice` = RESULT/NORMAL, no work_id/TTL/supersedes_key, incl. `CALIBRATION_ANALYSIS_ACK` | **Confirmed** | `brain_service.py:755-827` (request `:806-815`); sole caller `v2_app.py:342`; ACK `barehands_calibration.py:315` published `control_center.py:3263`; analysis `:3305` |
| 6 | Asymmetric interruption | **Confirmed** | thinking: `_abandon_brain_turn` → `abandon_turn` purges that correlation only (`speech_scheduler.py:865-926`); speaking: `note_interruption` (`:1018-1042`) purges nothing |

### Additional facts
- **A1. Live barge-in mutes the surface for the rest of the incarnation.** `_barge_in` calls `suppress_playback_until_session_end()` (`realtime_audio.py:1762-1764`, `live_frontend_session.py:365-373`). Anything queued after a Live barge-in is inaudible until the Live session ends — relevant to Slices 04/05 (a "revalidated" speech could be spoken into a muted surface). Recorded in `Issues/live-barge-in-mutes-incarnation.md`; Slice 05 must decide in its freshness-check whether it is in scope.
- **A2. `presentation_decided` / `carried_over` and `output_stalled` exist only in `trace.jsonl`**, not in the conversation-events journal — the timeline cannot show them today. Locked constraint "every new state/reason is traced and visible in the conversation timeline" therefore requires S02/S04 to add journal mapping (`runtime/conversation_event_trace.py:94-100`) for the new reasons.
- **A3. Doc path correction.** `docs/05-event-contracts.md` (cited by `docs/02-architecture.md` and `05-documentation-levels.md`) does not exist. The canonical event contract doc is `docs/conversation-events.md` ("Mouth speech identity" `:506`). Decision log of the realtime brain: `docs/handoff-realtime-brain/docs/01-decision-log.md` (Decisions 15 `:143`, 35 `:480`, 47 `:969`); user quote of 19/09 in `docs/fixes/stale-answer-carried-over/resolution-report.md:10`.
- **A4.** No existing test covers a Live completion reaching the scheduler, nor carried-over vs current-intent ordering.

## B2. Baseline measurement (conversation events)

Scripts kept for the Slice 06 re-measure: `<scratchpad>/baseline/{snapshot_dbs.py,analyze.py,reproduce_claim.py}` — to be copied into the repo by Slice 06 if kept (surface = `correlation_id` prefix `live:` / `realtime:`).

Main journal, all dates, started speeches:

| Surface | Terminal | Reason | Count |
|---|---|---|---|
| Live | interrupted | `delivery_not_complete` | **93 — all 30.001–30.020 s, played_ms=0** |
| Live | interrupted | `voice_background` | 7 |
| Live | completed | — | **0** |
| Realtime | completed | — | 70 |
| Realtime | interrupted | `user_barge_in` | 30 |
| Realtime | interrupted | `delivery_not_complete` | 3 (none near 30 s) |

- **Correction of the README figure:** 18–21/09 gives **32 of 63** interrupted speeches at 29.5–30.5 s (not 36/74, which reproduces under no DB/window/timezone). A strict 29.9–30.0 filter matches 0 (values are 30.001–30.02).
- **Session of 28/09:** present in the main journal at **12:54–12:58Z** (the transcript times are UTC): 8 Live speeches, each `delivery_not_complete` after 30.00–30.02 s with 0 ms played, one still open at 12:58:08Z. It is the direct evidence of cause 1.
- Announce-notice path (no work_id, RESULT): 17 speeches, 9 started (1 completed, 5 `delivery_not_complete`, 1 barge-in, 2 background), 6 still open.
- `output_stalled` (trace only, up to 21/09): 22, of which 14 Live with `still_active=False`.

**Slice 06 target, restated with this baseline:** Live `completed` > 0 with `completion_basis=local_quiescence`, 0 Live `delivery_not_complete` at ~30 s.

## B3. Corrupt WAL on the live journal (non-blocking, out of scope)

`data/state/jarvis.sqlite3` opened with its 4.1 MB `-wal` fails `integrity_check` ("malformed") and silently stops at 2026-09-21 15:34Z; the main file alone passes and runs to 28/09. Any reader applying the WAL sees wrong data. Recorded in `Issues/journal-wal-corrupt.md`. Not touched.

## B4. Inherited red tests — "not yours, do not fix"

Full `tests/unit` (295 files, 8 foreground chunks of 37) at `202333d` in detached `C:/Projects/jarvis/bwt`: **9011 passed, 5 skipped, 10 failed.**

- `tests/unit/test_barehands_calibration_events_js.py::test_a_refused_c_tells_the_assistant_its_real_cause_not_just_out_of_band`
- `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`
- `tests/unit/test_barehands_interaction_js.py::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
- `tests/unit/test_barehands_real_hands_js.py::test_a_real_open_c_at_0_6_palm_is_refused_for_its_fingers_not_its_gap`
- `tests/unit/test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` (system prompt text mismatch, `:140` — **inside this task's gate file**, unrelated to speech)
- `tests/unit/test_scene_group_drag_js.py` × 5: `test_a_group_move_keeps_recorded_offsets_and_leaves_unplaced_members_behind`, `test_dragging_n_objects_posts_one_translate_selection_and_confirms_every_layer`, `test_a_refused_group_move_rolls_every_layer_back_and_nothing_moving_sends_nothing`, `test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`, `test_a_group_pushed_into_a_corner_keeps_every_orbiting_member_on_screen`

## B5. Task gate suite (every Slice reruns it)

31 files — `docs/04-testing-and-quality.md` list plus the barge-in / duplex files found by the audit:

```
tests/unit/test_v2_speech_scheduler.py
tests/unit/test_speech_presentation_scheduler.py
tests/unit/test_speech_presentation.py
tests/unit/test_speech_scheduler_review_races.py
tests/unit/test_brain_interrupted_speech.py
tests/unit/test_realtime_audio_lifecycle.py
tests/unit/test_openai_live_frontend*.py
tests/unit/test_brain_delegation.py
tests/unit/test_back_brain_delegation.py
tests/unit/test_barehands_calibration_*.py
tests/unit/test_testlab_virtual.py
tests/unit/test_voice_duplex.py
tests/unit/test_v2_barge_in.py
tests/unit/test_barge_in_while_thinking.py
tests/unit/test_owner_barge_in.py
tests/unit/test_barge_in_sustain.py
tests/integration/test_testlab_virtual_runners.py
tests/integration/test_voice_replay_regressions.py
tests/integration/test_background_failure_speaks.py
tests/integration/test_speech_presentation_race.py
tests/integration/test_duplex_orb_states.py
tests/integration/test_live_openai_thinking_barge_in.py
```

Baseline at `202333d`: **733 passed, 1 skipped, 2 failed** (the two inherited ones above from `test_brain_delegation.py` and `test_barehands_calibration_events_js.py`). Runs in ~2 min in one foreground process.

## B6. Concurrency check

- Drive `current`: `jarvis-presentation-interaction-mode`, `jarvis-category2-test-lab`, `jarvis-subagent-routing-continuous-self-dev` — none touches speech scheduling/brain notices beyond what is already merged.
- No local branch is ahead of `origin/main`.
- Dormant uncommitted edits in other worktrees touching in-scope files, left untouched: `.claude/worktrees/agent-a61c9d34042ce8a60` (`speech_scheduler.py` +53, `voice_v2.py`, 16/09), `.claude/worktrees/agent-abfdef1b5004dd50b` (`claude_local.py` +1, 21/09), `sub-agents/jarvis-session-par-lancement` (`v2_app.py`, `domain/v2.py`, `control_center.py`, 21/09). Their branches are merged into `main`; if the Human revives one, expect conflicts with S02/S04.

## B7. Planning repairs applied

1. Every reference to `docs/05-event-contracts.md` means `docs/conversation-events.md`.
2. Baseline figure 36/74 → 32/63 (18–21/09) and the 28/09 session measured directly.
3. S02 and S04: new reasons must also reach the conversation-events journal/timeline (A2).
4. S05: freshness-check must decide on `suppress_playback_until_session_end` (A1).
5. S02 ∥ S03 each in its own worktree (one implementer per worktree).
