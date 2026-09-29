# Slice 00 - Readiness report

- Date: 2026-09-29
- Branch: `task/jarvis-board-session-context-runtime`, created from `origin/main@202333d` (= planning snapshot; no `dev` branch in this repository).
- Handoff origin: remote (Drive `to-do/jarvis-board-session-context-runtime`, id `1Aea1lm8ZFrsrDt4yegO9Z5xZ1g7gmFnD`). The first upload was an empty folder skeleton; the Human re-uploaded it. The Drive connector cannot move folders: the Human moves it to `current`.
- Mirror: 39 files, Google-Docs escapes removed, all JSON parse, committed as `2a03d16 S0`.

## Declared state

**`READY`** - decided by agent 0 (Human delegated autonomy, 2026-09-24).

- D1. Workspace Task Type gate waived: no vocabulary exists in the repository (audit B1 topic 9). `task_type` stays `null`; each `metadata.json` carries `task_type_resolution`.
- D2. The handoff's generic Slice contracts are replaced by a code-grounded architecture: `docs/06-resolved-architecture.md` (authoritative) and a `## Slice 00 contract` section appended to every `SLICE.md`.
- D3. Slice 04 split: **04a** Board agent pool in the Control Center (folder `04-brain-voice-switch`) and **04b** switch transaction, speech authority and Voice rebind (new folder `04b-switch-speech-authority`). HV-BOARD-VOICE-001 moved to 04b. Dependencies of 05/06/07/08 repaired. Commit prefixes `S4a` / `S4b`.
- D4. Core owns Board store, Sessions, bindings, switch and speech authority; the Control Center owns only the Board agent pool, UI and MCP entry points (06 section A).
- D5. One agent process per binding, pooled (06 section B), because stopping a Claude CLI kills its sub-agents (`agent_tasks.py:364-370`, `claude_local.py:1362-1388`). This is the only way "background work survives a Board switch / new Session" holds.
- D6. "Jarvis start = new Session" is taken from the locked design session (`grill-session.md`), not a new decision; it changes today's behavior (Voice reuses `.voice_conversation` across restarts, `voice_v2.py:457-475`).
- D7. Accepted V1 limits (06 section J): shared global scene (`Issues/per-board-scene-isolation.md`); CLI sub-agents do not survive a Control Center/Jarvis restart (reported interrupted, Board-attributed).
- D8. Naming: code uses `workspace_board*` / table `work_boards` to avoid the Barehands `board`; ids `board_*`, `jsess_*`; user-facing "Board".

## B1. Blind audit - README facts

Explore agent forbidden to open this handoff, at `202333d`.

| # | README fact | Verdict | Evidence / nuance |
|---|---|---|---|
| a | `control_center.py` exposes agent restart and `new_conversation` | Confirmed | one route `POST /api/agent/restart` (:974, handler :4594-4630) with optional `{new_conversation}`; only Claude honours `resume=False`; neither touches Core `conversation_id` nor `.voice_conversation`; no Python test covers the body |
| b | `live_frontend_session.py` separates Live session id and holds `conversation_id` | Confirmed | uuid at `connect()` (:134), `attach_core` (:236-246); "migration facade" |
| c | `BackgroundEventLedger` classifies completion/failure/attention | Confirmed | categories `failed/attention/done/said`; in memory (60), fed by `trace.jsonl`; no conversation/board id |
| d | Interaction mode persisted globally, Core owns effective mode | Confirmed | `interaction_mode_settings.py:44-47,194`; `core/interaction_mode.py:167`; `ARCHITECTURE.md:342-361` |
| e | `settings_mcp.py` defines `jarvis-console` + parity rule | Confirmed | only 3 settings tools (:922-957); no agent/session tool |
| f | `mcp_catalog.py` + `mcp_tool_meta.py` canonical | Confirmed | procedure `docs/mcp/tool-contract.md` §10.2 |
| g | `control_center.html` top bar + notification layering | Partly | top bar exists but is `pointer-events:none` with **no top-right controls**; controls live in the right-middle dock; z-index registry `:1-49` |

Additional facts:
- A1. No workspace/project/galaxy concept exists; "board" = Barehands board. No `CONTEXT.md`, no `docs/adr/`.
- A2. Single LLM process in CC (`control_center.py:1000-1023`); Claude `session_id` in memory only (`claude_local.py:432`).
- A3. Core targets volunteered speech at `_last_conversation_id` (`brain_service.py:316,515`) and the brain work context is not scoped -> addressed in 04b.
- A4. `SpeechScheduler` already drops other-conversation `brain.*` events in continuous mode (`speech_scheduler.py:1126-1137`), not in legacy mode -> Core gate required.
- A5. Scene is a DB singleton; `WorkRef` has no Board.
- A6. Stale comment `v2_app.py:104-106` ("schema 1") -> fixed in 02.

## B2. Inherited red tests - "not yours, do not fix"

Full `tests/unit` (295 files, 12 foreground chunks) at `202333d` in detached `C:/Projects/jarvis/bwt`: **9026 collected, 9009 passed, 5 skipped, 12 failed** (11 stable + 1 flaky).

- `test_scene_group_drag_js.py` x5: `test_a_group_move_keeps_recorded_offsets_and_leaves_unplaced_members_behind`, `test_dragging_n_objects_posts_one_translate_selection_and_confirms_every_layer`, `test_a_refused_group_move_rolls_every_layer_back_and_nothing_moving_sends_nothing`, `test_a_group_pushed_into_a_corner_keeps_every_orbiting_member_on_screen`, `test_the_page_commits_a_group_drag_through_one_command_and_a_single_drag_unchanged`
- `test_barehands_interaction_js.py` x2: `test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`, `test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`
- `test_barehands_calibration_events_js.py::test_a_refused_c_tells_the_assistant_its_real_cause_not_just_out_of_band`
- `test_barehands_real_hands_js.py::test_a_real_open_c_at_0_6_palm_is_refused_for_its_fingers_not_its_gap`
- `test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` (system prompt now carries the settings section)
- `test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo` (reproduces alone)
- Flaky: `test_presentation_attention_browser.py::test_ecarter_l_avertissement_n_emet_aucune_requete` (stray `GET /favicon.ico`; passes alone and on file rerun).
- Flaky (found by Slice 03 QA, 2026-09-29): `test_presentation_integration.py::test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee` (passes alone and on file rerun).

Raw chunk outputs: `<scratchpad>/board-baseline/`.

## B3. Freshness rule

Before every later dispatch: `git fetch` and `git rev-list --left-right --count origin/main...HEAD`; if `origin/main` moved, check the Slice's files for overlap. Before close-out, merge `origin/main` INTO the task branch.

## B4. Execution constraints

- Host RAM is low (~0.5-2 GB free): pytest in the foreground, chunked; no background test jobs.
- One implementer per working tree; no `git stash` (shared across worktrees; `bwt` belongs to other tasks too).
- `data/state/jarvis.sqlite3` is live runtime state, dirty, never committed by this task.
