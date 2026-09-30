# 06 - Resolved architecture (Slice 00, authoritative)

Written by agent 0 at Slice 00 from the blind audit and a code-grounded design pass at `202333d`.
Where this file and `02-architecture.md` differ, this file wins. Line numbers are at `202333d`.

## A. Ownership

| Concern | Owner | Where |
|---|---|---|
| Board store, Sessions, bindings | **Core** | new `jarvis/core/board_service.py`, `jarvis/core/session_manager.py`; tables in `jarvis.sqlite3` via `sqlite_state.py` migration v3 (`_MIGRATIONS` :35, `_SCHEMA_VERSION` :25) |
| Switch transaction, speech authority | **Core** | `board_service.py` coordinator; gate in `brain_service.py` |
| Board Brain processes | **Control Center** | new `jarvis/runtime/board_brains.py` (`BoardBrainPool`) |
| UI / MCP entry points | Control Center | `/api/boards*`, `/api/sessions*` proxy to Core `/v1/boards*`, `/v1/sessions*` (same pattern as `/api/interaction-mode`); `jarvis-console` MCP calls the same `/api/*` routes |
| Effective interaction mode | Core `InteractionModeService` (unchanged) | persisted selection moves to the Board row |

Why Core: it already owns conversations and public brain state (`docs/ARCHITECTURE.md:192`, `v2_app.py:156`), Voice talks only to Core, and only Core has a migrating durable store. Core reaches CC through an optional capability on the existing `ControlCenterBrainBackend` (discovered like `next_notices`, `v2_app.py:185`) calling a new CC route `POST /api/agent/bindings/activate`. CC re-aligns at startup from `GET /v1/sessions/current` (same pattern as the mode replay, `control_center.py:1482`).

## B. What a Board Brain is

Verified: stopping a Claude CLI kills its sub-agents (`agent_tasks.py:364-370` `process_stopped`, `claude_local.py:1362-1388` `stop`; `restart` = stop+start `:1334-1348`). So today's `/api/agent/restart {new_conversation:true}` already kills background work.

**One agent instance per binding** (not per Board), pooled in CC: `conversation_id -> ClaudeLocalAgent | CodexLocalAgent`, exactly one foreground.

- `foreground`: live CLI, receives turns.
- `background_running`: live CLI kept because `subtasks.counts()` shows running tasks; no turns routed, notices not spoken.
- `suspended`: `stop()`; Claude `session_id` (`claude_local.py:502-504`) saved on the binding, later `--resume` (`:767`).
- Demotion: idle CLI suspended at once; background CLI auto-suspends 60 s after its last sub-agent ends.
- Cap: 3 live CLIs; the cap only suspends idle ones; never cancels work (exceed with a warning trace).
- `ControlCenter.agent` (`:1000-1023`) becomes the pool's foreground (call sites unchanged). `_switch_agent` (`:1079-1110`) applies Claude<->Codex to the foreground binding only. Per-agent wiring (`TrackerWorkObserver`, `work_ingress.on_resync`, `conversation_events`) becomes per pool entry.
- Routing: `agent_ask` (`:4636`) routes by `conversation.conversation_id` (`control_center_brain.py:147`) to the pool; no conversation id -> foreground; non-foreground binding -> 409 `brain_not_foreground`.
- Notices: `/api/agent/notices` reads only the foreground (`:4942`). On promotion record a notice watermark so an epoch change (`:4955`) does not replay notices produced while in background.
- Codex: per-turn process, `codex exec resume <thread_id>` (`codex_local.py:6,253-256`); thread id stored as binding `agent_session_id`; never `background_running`; the pool never calls Codex `restart()` (`:568-575` clears the thread).

## C. Binding and Session semantics

`BoardConversationBinding`: `session_id, board_id` (unique), `conversation_id` (Core conversation, `ConversationService.create` `v2_services.py:262`), `agent_cli`, `agent_session_id` (nullable, reported by CC on activate and on each ask result), `lifecycle`, `created_at`, `last_active_at`, `status`.

- A/B/A in one Session: same binding, same Core conversation, same live CLI (or `--resume`).
- New Session: close old (`UPDATE ... WHERE status='open'`; never updated again), open new, create active-Board binding with a new Core conversation and a fresh CLI; the old binding's CLI is demoted, not killed. Other Boards bind lazily.
- Jarvis (Core) start = new Session (locked in `grill-session.md`: "starting Jarvis ... starts a new Session"). The open Session is closed with `end_reason=core_restart`.
- Voice pointer `runtime/.voice_conversation` (`voice_switch.py:163-176`) becomes a cache; Core's active binding is the truth.

## D. Voice rebind and speech authority

- Scheduler already drops `brain.*` events of another conversation in continuous mode (`speech_scheduler.py:1126-1137`), mode events routed before the filter (`:1120-1124`). It is not sufficient (legacy mode, rebind gap).
- **Authoritative gate in Core**: active conversation checked at `_emit_speech` (`brain_service.py:1865`) and `select_outcome` (`:361`); refusal traced `core.brain.speech_withheld_inactive_board {board_id}` and surfaced as an alert.
- `announce_notice` (`:755`) and `wake_for_work_attention` (~`:870`) target the active binding instead of `_last_conversation_id` (`:316`, `:515`).
- Work context: `WorkItem`/`WorkObservation` (`domain/work_state.py:485`) gain emitter-supplied `board_id`; `BrainContextBuilder` keeps active-Board + untagged work; wakes only for active-Board work.
- Voice at activation reads `GET /v1/sessions/current` before `voice_v2.py:457`, pointer as fallback. During an active voice session Core publishes `board.voice_binding.changed {conversation_id}`; the scheduler forwards it (before the filter); runtime drains the current utterance, `mute(reason="board_switch")`, sets the conversation id, `activate()` again. Live path (`live_frontend_session.py:236`) follows the same close/reopen; the one-unresolved-live-session index (`sqlite_state.py:207`) is respected because `mute` finalizes.
- Switch transaction (Core, under lock): validate -> get/create binding -> `host.activate(target)` (fail: abort, nothing committed) -> apply target mode (fail: `host.activate(previous)`, abort) -> one SQLite transaction (active Board, visited, binding times, lifecycles) -> in-memory authority -> publish `board.switched`.
- Brain-originated switch/new-session (MCP during a turn): `origin=brain`; CC defers until the agent's pending ask resolves; tool returns `{status:"scheduled"}`.
- No low-level model-controlled bind_voice / attach_brain / speech-authority tools.

## E. Scene / workspace scoping (V1 limitation, decided)

The scene is one global constellation (`scene_meta` singleton `sqlite_scene.py:125`; `WorkRef` has no Board `domain/scene.py:475`). V1 stores `scene_ref={"kind":"global","scene_id":..,"revision_at_leave":n}` per Board; the scene stays shared. Per-Board scene isolation is deferred (recorded in `Issues/`). V1 persists per Board: `context_summary` (bounded text, edited via UI/MCP or by the Board's own brain through `board_update`), `task_refs`, `artifact_refs`, `project_refs`, `scene_ref`, `interaction_mode`, bindings.

Hydration: `_turn_context` (`control_center_brain.py:80`) adds a bounded (~2 KB) `board` block (title, summary, refs) to every turn.

## F. Interaction mode per Board

`work_boards.interaction_mode`. `BoardService` listens to `InteractionModeService` changes (`v2_app.py:191` mechanism) and writes the active Board. On switch and Core start, apply the Board's mode with `source="board_switch"|"board_restore"`. CC's global replay (`control_center.py:1482-1535`) stays only as migration input and no-Boards fallback. Update `docs/interaction-mode.md` (`core/interaction_mode.py:171` currently says CC owns the preference).

## G. Alerts

- `RuntimeJournal` (`runtime/journal.py:11`) gets an optional bound context merged into `data`; each pool agent's journal carries `{board_id, jarvis_session_id}`. Core diagnostics carrying a `conversation_id` get `board_id` from `BoardService`.
- `BackgroundEvent` (`background_events.py:~203`) gains `board_id` (payload too).
- Background agents' notices journaled `spoken:false` -> `SAID` alerts; withheld inactive-Board speech -> `ATTENTION`.
- Unread across restart: persist ledger entries, ack cursor and follower offset to `runtime/background-events.json` (bounded 60). `TraceFollower` currently starts at EOF (`:~384`). Core's `notifications` table is not reused (delivery semantics, full scan per create `v2_services.py:1019-1026`).
- Go-to-Board action calls `POST /api/boards/switch`.

## H. Default-Board migration

Idempotent, keyed on "boards table empty": v3 creates tables; `ensure_default()` inserts `board_id="default"` (`interaction_mode_origin="unset"`); the first Session's default binding adopts the most recent Core conversation (only in the run that created the default Board); CC's existing replay posts the legacy mode once (origin -> `migrated`); CC adopts the already-running agent as the default binding's foreground. Tests: v2->v3 with backup, double run, crash mid-migration.

## I. Naming

"board" already names the Barehands board (`jarvis/ports/board.py`, config key `board` `config.py:112`, `--no-board`). Code uses `workspace_board*` modules and table `work_boards`; user-facing routes/MCP/UI say "Board". "session" is overloaded: cross-module fields use `jarvis_session_id`, ids prefixed `jsess_`. Glossary in the new canonical `docs/boards.md`.

## J. Accepted V1 limits

1. Shared global scene (E).
2. CLI sub-agents do not survive a Control Center / Jarvis restart (they are CC child processes); they are reported interrupted, Board-attributed. Core jobs survive. The locked requirement is survival across Board switch and new Session, which V1 meets.
