# Slice 08 — Evidence (E2E proof, rollout, close-out)

Date 2026-09-29. Branch `task/jarvis-board-session-context-runtime`, from `601539c`.
Raw artefacts (not committed): `<scratchpad>/s8/` — `real_rt.py` (real-CLI
driver), `rt/runtime/trace.jsonl` + `rt/summary.json` (real run), `analyze.py`
(trace analysis), `reg/out_*.txt` (regression chunks).

## 1. Scenario matrix — `tests/integration/test_board_session_e2e.py`

Real `JarvisCoreApplication` + `LocalProtocolServer` (temp SQLite) and real
`ControlCenter.start` (HTTP, Board agent pool, background ledger), wired as in
`jarvis/app.py` (`CoreSessionTransport`, `CoreInteractionModeTransport`,
`ControlCenterBrainBackend`). `claude` = a real Python process speaking
stream-json (sub-agents, spontaneous relay with `origin`, flags `fail-start`,
`fail-resume`, `end-<task>`, `fail-<task>`). User turns go through Core
(`brain.submit`, as Voice does) -> Control Center -> CLI. Every scenario ends
with `assert_one_speech_authority()`: the timeline helper
`tests/integration/board_session_timeline.py` replayed over Core's bus
(`brain.speech.requested`, `board.voice_binding.changed`) **and** over
`trace.jsonl` (`core.session.opened`, `core.board.switched`,
`core.brain.notice_relayed`, `core.brain.speech_withheld_inactive_board`).

| # | Test | Covers | Result |
| --- | --- | --- | --- |
| 0 | `test_the_timeline_check_catches_a_second_speaker_and_a_gated_active_board` | the helper itself detects a second speaker and a gated active Board | pass |
| 1 | `test_a_v2_store_migrates_to_one_default_board_...` | v2 DB built programmatically (schema 2 + a conversation) + legacy CC mode `presentation`: v3, `.v2.bak`, one `default` Board, first Session adopts the v2 conversation, CC adopts it as foreground, legacy mode adopted once (`migrated`); Core restart: new conversation, no second default/backup, mode restored from the Board | pass |
| 2 | `test_a_b_a_reuses_each_binding_then_a_new_session_is_clean_...` | create B (UI route); A->B->A: same binding, same live CLI (A busy -> `background_running`); B idle -> suspended, then resumed with `--resume <its id>`; `visited_board_ids`; new Session on A (`expected_session_id`): new conversation, fresh CLI, old A CLI still running its sub-agent (`closed`, `background_running`), fresh CLI input contains nothing of the old Session and **does** contain the Board summary/refs; Board A summary/refs and B unchanged; second click -> 409 `session_closed`; old binding's sub-agent finishes -> relay `spoken:false`, Board A, no speech | pass |
| 3-4 | `test_inactive_board_completion_and_failure_are_attributed_alerts_that_survive_both_restarts` | two sub-agents on A, switch to B, one completes, one fails: `done` + `failed` + `said` alerts of A, zero speech, zero `notice_relayed`; `/api/status` sources name A. CC restart: unread counts kept, CC realigns on B. Core restart: new Session on B, CC realigns, alerts kept, no open old-Session binding. Go-to-Board = normal switch; ack persisted; after another CC restart nothing unread | pass |
| 5 | `test_each_board_restores_its_mode_and_an_unset_board_gets_the_default` | mode set with the UI route on B (`presentation`, stored `user`); switch to unset C -> assistant, C stays `unset`; back to B -> presentation; A -> assistant; Core restart on B -> presentation (`board_restore`) | pass |
| 6-7 | `test_mcp_tools_and_screen_routes_see_and_refuse_the_same_things_including_archive_guards` | `jarvis-console` tools (`ConsoleBoardTools`) against the live CC vs the screen routes: create (MCP) visible on screen, rename (screen) visible in MCP, switch/new Session applied (outside a turn), same active Board / Session on both; archive active -> `board_is_active` on both; archive default (MCP), then switch/rename -> `board_archived` on both; hidden from list, shown with `include_archived`; archive replayable; Core restart resumes the last non-archived Board | pass |
| 8 | `test_a_failed_switch_rolls_back_everything_and_a_dead_resume_id_falls_back_to_a_fresh_cli` | `fail-start`: 502 `board_activation_failed` with the CLI's own words; Session, binding, authority, foreground, mode, status block unchanged; no pool entry for the target; flag removed -> same switch passes. `fail-resume`: suspended B's saved id fails -> `board_brain.resume_failed_fresh_start`, fresh CLI id recorded, B's mode restored, next turn served | pass |

Runtime: 7 tests, ~25 s (3 consecutive runs green: 24.5 s, 25.3 s, 25.7 s).
No marker needed: the repository gates only networked/model tests
(`skipif` on env vars); this module uses loopback and no model, so it runs by
default.

### Defect found by the matrix and fixed in this Slice

**The Board never reached the CLI.** Core joined `context.board` to every
`/api/agent/ask` (Slice 04b), but `build_agent_brief` (Control Center) did not
render it: the fresh CLI of a new Session was hydrated by nothing of the Board
(locked requirement: "fresh interactive Brain conversation hydrated from the
active Board state"). Caught by scenario 2 (stub input log showed the brief
without any Board line). Fix: `jarvis/runtime/board_brief.py`
(`render_board_brief`), called from `build_agent_brief`; unit test
`tests/unit/test_board_brief.py` (3). Mutation: removing the call makes
scenario 2 fail on "hydrated from the Board block".

## 2. Real traces — real `claude` 2.1.284

Isolated Core 18793 + Control Center 18795 from this checkout
(`python -m jarvis core` / `control-center`, fresh data/runtime dirs),
`POST /api/agent/ask` with `context.addressing: "addressed"`.

### Turns

| # | Board | Input | Tool calls (in order) | Reply | Wall | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | default | « Crée un board Recherche et bascule dessus » | `ToolSearch select:board_create,board_switch,board_list` -> `board_create {title:"Recherche"}` -> `board_switch {board_id}` -> `scheduled` | « Le board Recherche est créé, on passe dessus juste après cette phrase. » | 9.3 s | $0.1688 |
| 2 | Recherche | « Lance un sous-agent en arrière-plan qui compte lentement jusqu'à 20, une seconde par nombre avec la commande sleep, puis réponds-moi tout de suite sans l'attendre. » | `Agent` (background, `general-purpose`, model haiku 4.5) | « C'est parti, un sous-agent compte jusqu'à 20 en arrière-plan, une seconde par nombre. » | 6.1 s | $0.1453 |
| — | Recherche (background) | sub-agent's own task-notification turn | — | `[pas-pour-moi]` (journaled `spoken:false`) | 2.6 s | $0.1891 |
| 3 | default | « Démarre une nouvelle session » | `ToolSearch select:session_new` -> `session_new` -> `scheduled` -> `board_list` | « Une nouvelle session s'ouvre après cette phrase, mais sur le board principal : on n'est plus sur Recherche, … Tu veux que je rebascule sur Recherche ? » | 7.7 s | $0.0484 |

**Total: 4 CLI results, $0.5516.** No error line in the trace (one
unrelated `calendar.backend` in-memory warning).

### Authority timeline (from `trace.jsonl`, `check_single_authority`: 0 violations)

| t (UTC) | Event | Speaking conversation |
| --- | --- | --- |
| 17:01:24.708 | `core.session.opened` (core_start), `default` | `160d7bb5…` (A) |
| 17:01:26.2 | CC adopts A as foreground; `core.board.host_aligned` | A |
| 17:01:34.8 | `board_switch` -> `board.request.deferred` (turn 1 still running) | A |
| 17:01:37.5–41.6 | turn ended + 1.5 s grace -> `core.board.switch_started` -> Recherche CLI started (`agent.ready` after the 4 s window) -> A idle -> `suspended` -> `core.board.switched` -> `deferred_applied` | `b383d55b…` (R) from 17:01:41.653 |
| 17:01:45.9 | `agent.subagent.started` (Board R) | R |
| 17:01:48.25 | UI `POST /api/boards/switch {default}` (`board.request.relayed`, origin user) | R |
| 17:01:52.43 | A resumed (`--resume`, 4 s window) -> R demoted **`background_running`** -> `core.board.switched` | A from 17:01:52.441 |
| 17:02:16.6 | `agent.subagent.finished` completed, `board_id` = R | A |
| 17:02:19.3 | R's relay turn -> `agent.unsolicited_result` `spoken:false`, `board_id` R; **no** `core.brain.notice_relayed` | A |
| 17:02:26.6 | turn 3: `session_new` -> `deferred` | A |
| 17:02:36.8 | fresh CLI ready, old A suspended, `core.session.closed` (new_session) -> `core.session.opened` | `cf1edc66…` (A, new Session) |

Segments: A (0 spoken / 0 withheld), R (0/0), A (0/0), A' (0/0). Speech in
this driver is the HTTP answer (turns bypass Core), so the timeline's only
possible speech path is the notice relay: it stayed at zero for R, which is
the proof that R's completion was never spoken. Status after the UI switch:
`[{default, foreground}, {Recherche, background_running}]`; after the new
Session: `[{Recherche, background_running, closed:true}, {default, foreground}]`.

### Alert

`GET /api/background`: `done` « Sous-agent terminé en 31 s : [fast] Compter
lentement jusqu'à 20 » and `said` « Tour spontané du brain, rien à dire »,
both `board_id` = Recherche. `/api/status` `background.sources`:
`[{board_id: Recherche, title: "Recherche", counts: {done:1, said:1}}]`.

### Trace analysis (agent-trace-analysis)

- **Functional / architecture:** correct. Switch and new Session requested
  by the brain were deferred to the end of the turn, then went through Core's
  transaction; the UI switch while R worked kept R's CLI alive
  (`background_running`) and its sub-agent finished there; its completion
  became an R-attributed alert and was never relayed to Voice. No bypass, no
  hidden retry, no error.
- **MINOR (turn 3):** after `session_new` the brain called `board_list`
  (redundant) and answered three sentences instead of the one short sentence
  the server instructions ask for. It even offered to go back to Recherche.
  Cost small (+2 model turns, $0.048); prompt-quality follow-up, not a
  runtime defect.
- **FLAGGED (relay turn):** the background task-notification turn answered
  the not-addressed marker `[pas-pour-moi]` ($0.19). Harmless here (never
  spoken, alert says "rien à dire"), but the alert carries no useful summary
  of the result; the `done` alert does.
- **FLAGGED (titles):** in `GET /api/background` read 4 s after the relay,
  both events had `board_title: null`; the title was filled at the next
  status beat (`sources` had it). The page polls `/api/status` at 1 Hz before
  any popover read, so the user sees the title; a direct API reader may not.
- **OPTIMIZATION:** each switch that starts or resumes a Claude CLI costs the
  4 s readiness window (accepted V1 limit 3): deferred switch 4.1 s, UI
  switch 4.2 s, new Session 4.0 s.
- **Missing evidence:** this driver posts to `/api/agent/ask` directly, so the
  per-turn `board` block (built by Core) is absent from these real turns;
  hydration is proven on the Core turn path by matrix scenario 2 and
  `test_board_brief.py`. Voice (audio) not exercised: HV-BOARD-VOICE-001.

## 3. Documentation

- `docs/boards.md`: header rewritten as the Level-3 entry (status, section ->
  code -> proof table; stale "Slice 01 … no route/UI/MCP yet, later Slices
  add …" removed); glossary gains the runtime terms (active Board, Board
  brain, speech authority, switch, new Session, `board` block,
  Board-attributed alert, default Board); new *System invariants (V1)* (8,
  each proven by the E2E module); `board` block *Rendering* paragraph;
  *Accepted V1 limits* 2 -> 8; new *End-to-end proof*. Fixed a broken table
  cell (literal newline/tab inside backticks).
- `docs/ARCHITECTURE.md`: ownership table gains "Board context of each turn
  (hydration)"; stale "rows above also name owners later Slices create"
  replaced by the V1-complete pointer.
- `docs/interaction-mode.md`, `docs/mcp/tool-contract.md` §10.9: re-read, no
  stale statement (mode per Board, replay retired, 9 tools, same routes);
  unchanged here. (Timeout wording in §10.9 / `boards.md` belongs to the S5/S6
  rework that follows.)
- `idees/2026-09-28-nouvelle-session-a-la-voix.md`: S5 marked it done; the
  `idees/README.md` convention also asks for the link to the `tasks/` folder
  at the head of the file -> added (`- Chantier : …`), plus the answers to its
  two open questions.

### Documentation levels (`docs/05-documentation-levels.md` vs reality)

The repository has no `docs/CONTEXT.md` nor level registry (audit A1);
Level 1 is met by the `docs/boards.md` glossary, linked from
`docs/ARCHITECTURE.md`.

| Concept | Required | Reached | Evidence |
| --- | --- | --- | --- |
| Board | 3 | **3** | glossary + contract `boards.md`; `workspace_board.py`, store, service; contract/store/service suites + E2E |
| Session vs Brain conversation | 2 | **3** | glossary separates Session / Core conversation / CLI session; `session_manager.py`; `test_session_*` + E2E scenario 2 |
| Brain foreground/background/suspended | 2 | **3** | *Lifecycle* + *Board agent pool*; `board_brains.py`; `test_board_brains*` + E2E 2/3/8 |
| Voice ownership | 3 | **3** | *Speech authority*; `speech_authority.py` + gate; `test_board_speech_authority.py`, `test_voice_board_rebind.py`, timeline check on every E2E scenario and on the real trace |
| Notifications (Board attribution) | 3 | **3** | *Alerts and absence*; `background_events.py`, `board_attribution.py`; `test_board_alerts*` + E2E 3-4 + real alert |
| Interaction mode, Board-scoped | 3 | **3** | `docs/interaction-mode.md` + *Interaction mode per Board*; `board_service.py`; E2E 1/5/8 |
| `jarvis-console` MCP parity | 3 | **3** | tool-contract §10.9; `console_boards.py`; `test_settings_mcp.py` route parity + E2E 6-7 |
| Galaxy map | 0 (deferred) | **0** | out of scope, named in V1 limit 8 |

## 4. Regression

`tests/unit` (319 files, 12 foreground chunks of ~26–27 files):

| Chunk | Result | Failures |
| --- | --- | --- |
| 00 | 718 passed, 1 failed | `test_barehands_calibration_events_js::test_a_refused_c_…` (B2) |
| 01 | 514 passed, 2 failed | `test_barehands_interaction_js` x2 (B2) |
| 02 | 441 passed, 1 skipped, 1 failed | `test_barehands_real_hands_js::test_a_real_open_c_…` (B2) |
| 03 | 536 passed, 1 failed | `test_brain_delegation::test_the_voice_agent_starts_with_the_rule…` (B2) |
| 04 | 583 passed | — |
| 05 | 726 passed, 1 skipped, 1 failed | `test_interaction_mode_hud_browser::test_le_mouvement_reduit…` (B2) |
| 06 | 1186 passed, 1 skipped | — |
| 07 | 848 passed, 5 failed | `test_scene_group_drag_js` x5 (B2) |
| 08 | 956 passed | — |
| 09 | 1420 passed | — |
| 10 | 551 passed | — |
| 11 | 941 passed | — |
| **Total** | **9420 passed, 3 skipped, 11 failed** | = the 11 B2 stable failures, exactly; no B2 flaky fired |

B2 baseline at `202333d`: 9009 passed, 5 skipped, 11 stable + flaky. No
failure outside B2 -> no investigation at `202333d` was needed (the `b8w`
worktree was not created).

`tests/integration` (67 files, 2 chunks): **583 passed, 22 skipped** (opt-in
live/model/real-DB tests), 0 failed.

## 5. Remaining risks

- Voice itself (microphone, speakers, rebind drain) is proven only by unit
  tests and the Core bus; the audio path is HV-BOARD-VOICE-001.
- The S5/S6/S7 (+04b NIT) QA rework landed after these commits (`66c1fdd`,
  `46e1f53`, `ee44ab7`, `51ecfb9`); the matrix was re-run with it (see §6).
- Brain wording after `session_new` (turn 3) is longer than instructed.
- The user's real `data/state/jarvis.sqlite3` migrates v2 -> v3 at the first
  start of this branch (backup `jarvis.sqlite3.v2.bak` next to it).

## 6. Re-run after the 05/06/07 QA rework

- E2E matrix + `test_boards_hud_browser.py` + `test_board_alerts_browser.py` +
  `test_board_brief.py`: 22 passed.
- `tests/unit` (12 chunks): **9445 passed, 3 skipped, 11 failed** = the B2
  stable list exactly.
- `tests/integration`: **583 passed, 22 skipped**, 0 failed.
