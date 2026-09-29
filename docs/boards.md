# Boards and Sessions (contract)

Handoff `tasks/jarvis-board-session-context-runtime/`. Authoritative design:
`tasks/jarvis-board-session-context-runtime/docs/06-resolved-architecture.md`.

**Slice 04b — switch transaction, speech authority, Voice rebind**, section
*Switch and speech authority* below: `POST /v1/boards/switch` with rollback,
one speaking conversation gated in Core, Board-scoped work context, per-turn
`board` block, Voice rebind without restart, `/api/boards*` / `/api/sessions*`
relayed by the Control Center.

**Slice 04a — Board agent pool**, section *Board agent pool* below:
`BoardBrainPool` in the Control Center, one agent per binding, `ask` routing,
`POST /api/agent/bindings/activate`, new Session from `/api/agent/restart`.

**Slice 03 — Sessions and bindings**, section *Sessions* below:
`SessionManager`, Core start = new Session, `/v1/sessions*`, Voice reads its
conversation from the open Session.

**Slice 02 — persistence and interaction mode per Board**, section
*Persistence* below: SQLite store (schema v3), `BoardService`, `/v1/boards*`.

**Slice 01 — the domain contract.** Pure vocabulary:
`jarvis/domain/workspace_board.py` (values, errors, transitions) and
`jarvis/ports/workspace_board.py` (`BoardRepository`, `BoardBrainHost`);
conformance suite `tests/unit/test_workspace_board_contract.py`. No I/O, no
persistence, no route, no UI, no MCP yet. Later Slices add the SQLite store
(02), live bindings (03), the Control Center agent pool (04a), the switch
transaction and speech authority (04b), MCP (05), the UI (06) and
Board-attributed alerts (07).

## Glossary

Five words that look alike and must never be confused.

| Term | What it is | Where |
| --- | --- | --- |
| **Board** | The durable workspace and context boundary, like a ChatGPT Project: title, bounded context summary, task/artifact/project references, scene reference, interaction mode. Survives Sessions. User-facing word: "Board". | `Board` in `jarvis/domain/workspace_board.py`; table `work_boards` |
| **Barehands board** | The pinned third-party AGPL stage (`stage.html`, port 8794) Jarvis presents on. Unrelated to Boards. Owns the unprefixed word `board` in code (`jarvis/ports/board.py`, config key `board`, `--no-board`). | `docs/ARCHITECTURE.md` › *Barehands (upstream board)* |
| **Session** (Jarvis Session) | One human/Jarvis conversation episode. Starts when Jarvis (Core) starts or when a clean conversation is asked for; may visit several Boards; once closed, immutable history. Cross-module field `jarvis_session_id`, ids `jsess_…`. | `JarvisSession` |
| **Core conversation** | The Core `Conversation` (`conversation_id`) that carries the turns of one Session on one Board. One per binding. | `jarvis/domain/v2.py` |
| **CLI session** | The local agent's own resumable id (Claude `session_id`, Codex thread id). Stored as the binding's `agent_session_id`. Not a Session. | `jarvis/runtime/claude_local.py`, `codex_local.py` |

A **binding** (`BoardConversationBinding`) ties them together: for one
`(jarvis_session_id, board_id)` pair, the Core conversation, the agent CLI
kind and its CLI session, plus the agent process lifecycle.

Other "session" words that are **not** a Jarvis Session: the Voice realtime
session, the Live frontend session (`live_frontend_session.py`), the
conversation-event `session_id`, the Presentation session.

## Values

### Board

| Field | Rule |
| --- | --- |
| `board_id` | `"default"` (migration Board) or `board_<hex>` |
| `title` | 1–120 chars, single printable line, no surrounding spaces (`invalid_title`) |
| `status` | `active` \| `archived` |
| `created_at`, `updated_at`, `last_opened_at` | timezone-aware; `updated_at ≥ created_at`; `last_opened_at` optional |
| `context_summary` | ≤ **1 500** chars, printable text plus `
` and `	` only (`invalid_board` otherwise). Refused above (`context_summary_too_long`), never truncated: the editor (UI, MCP, the Board's own brain) condenses. The limit keeps the per-turn `board` block (title + summary + refs) near 2 KB. |
| `task_refs`, `artifact_refs`, `project_refs` | a list or tuple (a string is refused, never split into characters) of opaque ids/paths, ≤ 64 each, ≤ 256 chars each, unique |
| `scene_ref` | optional `{kind:"global", scene_id, revision_at_leave}`; V1 scene is shared |
| `interaction_mode` | `InteractionMode` internal value (`assistant`, `presentation`, `meeting`), strict |
| `interaction_mode_origin` | `unset` (never chosen), `migrated` (legacy global setting adopted once), `user` |
| `runtime_metadata` | flat map, ≤ 16 token keys, JSON scalar values (strings ≤ 256); frozen |

### Session

`jarvis_session_id`, `started_at`, `status` (`open` \| `closed`),
`active_board_id`, `visited_board_ids` (first-visit order, no duplicate,
contains `active_board_id`), `ended_at` and `end_reason` (`new_session` \|
`core_restart`) — set exactly when closed.

### Binding

`jarvis_session_id`, `board_id`, `conversation_id`, `agent_cli` (short token,
e.g. `claude`, `codex`), `agent_session_id` (nullable until the Control Center
reports it), `lifecycle`, `created_at`, `last_active_at`, `status`
(`open` \| `closed`).

Wire form: every value has `to_payload()` / `from_payload()` over plain JSON
dicts (SQLite JSON columns, HTTP bodies). `from_payload` is strict: unknown
keys, missing required keys, wrong types, naive timestamps and unknown enum
values are refused with the value's `invalid_*` code.

## Lifecycle

```text
Board:     active ──archive──▶ archived        (refused for the active Board)
Session:   open ──close(new_session | core_restart)──▶ closed   (terminal)
Binding lifecycle (agent process):
           suspended ──promote──▶ foreground ──demote──▶ background_running | suspended
           background_running ──last sub-agent ended (+60 s)──▶ suspended
Binding status: open ──session closed──▶ closed  (never foreground again)
```

- `foreground`: live CLI, receives turns, sole speech authority.
- `background_running`: live CLI kept for its sub-agents; no turns, no speech.
  The domain does not forbid it for any `agent_cli`: keeping Codex out of it
  (a per-turn process has no live CLI to keep) is a `BoardBrainPool` rule,
  enforced in Slice 04a.
- `suspended`: CLI stopped; `agent_session_id` resumes it.

## Invariants

1. **Closed Sessions are immutable.** Every Session transition goes through
   `ensure_open`; closing, visiting, binding or promoting in a closed Session
   raises `session_closed`. `close_session` refuses an end before the start
   (`invalid_session`) rather than clamping it. A Session closes **with** its
   bindings (`close_session_with_bindings`): all become `closed`, the
   foreground one takes the lifecycle the caller chooses, a
   `background_running` one keeps finishing its work. Closing an already
   closed binding is a no-op.
2. **One foreground binding per Session** (`check_bindings`,
   `promote_binding(session, bindings, target)`): the Session must be open and
   own `target`; promoting demotes the previous foreground of **that**
   Session only, to the lifecycle the caller chooses. The rule is per Session,
   not global; since one Session is open at a time and a Session closes with
   its bindings, only the open Session has a foreground, so one Board has
   speech authority.
3. **One binding per `(Session, Board)`.** A/B/A in one Session returns the
   first binding (`find_binding`): same Core conversation, same CLI or its
   `--resume`. `new_binding` on an already-bound pair raises
   `binding_conflict`.
4. **Visiting** (`visit_board`) makes a Board active, appends it to
   `visited_board_ids` on first visit only; visiting the active Board is a
   no-op. Archived Boards cannot be visited, opened, edited or bound
   (`board_archived`).
5. **The active Board is never archived** (`board_is_active`).
6. **No transition cancels work.** Demotion and closure only change the
   lifecycle; the Control Center keeps a CLI with running sub-agents.
7. **Legacy mode is adopted once** (`adopt_legacy_interaction_mode`): only an
   `unset` Board takes it (→ `migrated`); a re-run never overwrites a choice.
8. Every transition takes `now` explicitly; values are frozen dataclasses.

## Errors

`BoardError(ValueError)` with a stable `code` (`BoardErrorCode`) and `status`:

| Code | HTTP |
| --- | --- |
| `board_not_found`, `session_not_found`, `binding_not_found` | 404 |
| `board_archived`, `board_is_active`, `session_closed`, `binding_conflict` | 409 |
| `invalid_title`, `context_summary_too_long`, `invalid_board`, `invalid_session`, `invalid_binding` | 400 |
| `brain_not_foreground` — a turn aimed at a binding without speech authority (pool routing, 04a) | 409 |
| `board_activation_failed` — the host (Control Center) could not activate the target agent; switch aborted, nothing written (04b) | 502 |
| `board_switch_rolled_back` — a step after activation failed (mode refused, write); previous activation restored, nothing committed, previous Board still active (04b). Server-side failure, hence 500 | 500 |

`*_not_found` are raised by services from a repository miss; the domain raises
`binding_not_found` only when `promote_binding` is given a binding outside the
set.

## Ownership

| Concern | Owner | Where |
| --- | --- | --- |
| Board store, Sessions, bindings | Core | `jarvis/core/board_service.py`, `jarvis/core/session_manager.py`; `jarvis.sqlite3` migration v3 (Slice 02–03) |
| Switch transaction, speech authority | Core | `board_service.py` coordinator; gate in `brain_service.py` (Slice 04b) |
| Board Brain processes (one agent per binding) | Control Center | `jarvis/runtime/board_brains.py` `BoardBrainPool` (Slice 04a), reached by Core through `POST /api/agent/bindings/activate` (`BoardBrainHost`, implemented by `ControlCenterBoardHost`, Slice 04b) |
| UI / MCP entry points | Control Center | `/api/boards*`, `/api/sessions*` relaying Core `/v1/boards*`, `/v1/sessions*` (`jarvis/runtime/board_routes.py`, Slice 04b); `jarvis-console` MCP calls the same routes (Slices 05–06) |
| Effective interaction mode | Core `InteractionModeService` | persisted selection lives on the Board row |

There is no global reasoning Brain: Voice talks to the active Board's brain
through Core; the runtime around it is deterministic.

## Persistence

**Slice 02.** Store: tables of `jarvis.sqlite3` created by migration **v3**
(`sqlite_state._MIGRATIONS[3]`); adapter `jarvis/adapters/sqlite_workspace_board.py`
(`SQLiteBoardRepository`, same file, connection and lock as `SQLiteStateRepository`
through `run_serialized`); service `jarvis/core/board_service.py`
(`BoardService`, wired as `JarvisCoreApplication.boards`). Suites:
`tests/unit/test_board_store_sqlite.py`, `test_board_service.py`,
`test_board_protocol.py`.

| Table | Key | Extracted columns | Guards in the file |
| --- | --- | --- | --- |
| `work_boards` | `board_id` | `status`, `created_at`, `updated_at` | `status` CHECK |
| `jarvis_sessions` | `jarvis_session_id` | `status`, `started_at`, `active_board_id` | unique partial index: at most one `open` row; upsert updates only `WHERE status='open'` |
| `board_conversation_bindings` | `(jarvis_session_id, board_id)` | `conversation_id`, `lifecycle`, `status`, `created_at` | FKs to both tables; unique partial index: one `foreground` per Session |

Each row's `data` is the value's `to_payload()`; every read decodes it with
the strict `from_payload` and cross-checks the key columns. A damaged row
raises `BoardStoreError` (route: 500 `board_store_unreadable`, message naming
table and key); it is never skipped nor repaired. Any other SQLite failure
(`database is locked`, I/O) is raised as its subclass `BoardStoreUnavailable`
(route: 500 `board_store_failed`, SQLite's words and the operation kept).

- **Closed Session guard.** Saving any value over a `closed` row raises
  `session_closed`; the row is untouched. A second `open` Session is refused
  (`invalid_session`); a second foreground binding, or a binding to a missing
  Session/Board, is `binding_conflict`.
- **Closed binding guard.** A `closed` binding row never goes back to
  `status=open` nor to `lifecycle=foreground` (`session_closed`, row
  untouched); its lifecycle may still move between `background_running` and
  `suspended`, which `list_live_bindings` relies on.
- **`commit_switch`** writes Boards, Sessions and bindings in **one**
  `BEGIN IMMEDIATE` transaction; any failure (including the closed-Session
  guard) rolls back everything. It orders closing Sessions before the opening
  one and demoted bindings before the promoted one, so the partial unique
  indexes hold statement by statement.
- **Migration.** v2 → v3 is one transaction (DDL + version bump), preceded by
  the one-time backup `jarvis.sqlite3.v2.bak` ([state-model.md](state-model.md));
  a crash mid-step leaves v2 intact and the next start retries. The migration
  carries no product data.
- **Default Board** (06 section H). `BoardService.ensure_default()` inserts
  `board_id="default"` (`interaction_mode_origin="unset"`) only when
  `work_boards` is empty, in one transaction (`insert_board_if_empty`):
  idempotent across restarts and concurrent starts. The **first Session** of
  the store (no Session row yet) adopts the most recent Core conversation into
  its binding (*Sessions* below).

### Active Board (V1 pointer)

No separate pointer table: the active Board is `active_board_id` of the
**open Session** (`jarvis_sessions`, persisted), and `default` when no Session
is open (only before Core start: since Slice 03 every Core start opens a
Session). Slice 04b moves it by writing the Session (`commit_switch`) — a
second pointer would be a second truth.

### Interaction mode per Board

At Core start, before any route: `ensure_default()`, then the Session opens
(*Sessions* below), then `BoardService.start(ensure_default=False)`
re-applies the active Board's mode
(`source="board_restore"`; skipped for an `unset` Board), then subscribes to
`InteractionModeService` (`add_listener(..., with_state=True)`: the listener
receives the change's own state, so its `source` is never read later from the
service). Each change is written on the active Board by a background task
(`drain()` waits for them; `BoardService.stop()`, called by Core `stop()`
before closing the DB, unsubscribes then drains). A background write never
raises: every failure, including an unexpected one, is a
`core.board.interaction_mode.persist_failed` error line with `code` and
`exception_type`:

| `source` of the change | Active Board `unset` | Active Board `migrated`/`user` |
| --- | --- | --- |
| `startup`, `core_restart` (Control Center replay) | adopted once → `migrated` | not overwritten; Board mode re-applied (`board_restore`) |
| `board_restore`, `board_switch` (from the Board itself) | nothing written | nothing written |
| anything else (`control_center`, `save_retry`, `protocol`, …) | stored → `user` | stored → `user` |

Diagnostics (`runtime/trace.jsonl`): `core.board.default_created`,
`core.board.default_absent` (warning), `core.board.created` / `updated` /
`archived`, `core.board.interaction_mode.restore_skipped`, `.applied`,
`.migrated`, `.persisted`, `.legacy_replay_overridden` (warning),
`.apply_failed` / `.restore_failed` / `.persist_failed` (error, with the real
cause). Ids, codes and mode values only.

### Core routes

Authenticated like every `/v1` route; errors are
`{"error": {"code", "message"}}` with the `BoardErrorCode` and its status.

| Route | Body | Answer |
| --- | --- | --- |
| `GET /v1/boards[?include_archived=true]` | — | 200 `{boards: [...], active_board_id}` |
| `POST /v1/boards` | `{title, context_summary?, task_refs?, artifact_refs?, project_refs?, scene_ref?, runtime_metadata?}` | 201 `{board, active}`; 400 `invalid_title` / `invalid_board` / `context_summary_too_long` |
| `GET /v1/boards/active` | — | 200 `{board, active: true}` |
| `GET /v1/boards/{board_id}` | — | 200 `{board, active}`; 404 `board_not_found` |
| `PATCH /v1/boards/{board_id}` | any non-empty subset of the editable fields | 200 `{board, active}`; 404; 409 `board_archived`; 400 |
| `POST /v1/boards/{board_id}/archive` | empty | 200 `{board, active}` (replayable); 409 `board_is_active`; 404 |
| `POST /v1/boards/switch` (Slice 04b) | `{board_id}` | 200 `{session, binding, board, previous_board_id, changed}`; 404 `board_not_found`; 409 `board_archived`; 400 `invalid_board`; 502 `board_activation_failed`; 500 `board_switch_rolled_back`; 503 `core_unavailable` |

Unknown fields and query parameters are 400; a body above 128 KiB is 400.
`interaction_mode` is not an editable field: the mode changes through
`/v1/interaction-mode` and the listener stores it. The Control Center relays
these routes as `/api/boards*` (Slice 04b, *Switch and speech authority*);
client methods `LocalCoreClient.list_boards`, `active_board`, `get_board`,
`create_board`, `update_board`, `archive_board`, `switch_board`.

## Sessions

**Slice 03.** Service `jarvis/core/session_manager.py` (`SessionManager`,
wired as `JarvisCoreApplication.sessions`), over the same
`SQLiteBoardRepository`. Suites: `tests/unit/test_session_manager.py`,
`test_session_protocol.py`, `test_voice_session_binding.py`.

### Core start = new Session

In `JarvisCoreApplication.start()`, after `state.initialize()` and before the
protocol server starts (so no route ever sees Core without a Session):

1. `BoardService.ensure_default()`.
2. `SessionManager.start()`, one `commit_switch`:
   - the Session left open by the previous life is closed with
     `end_reason=core_restart`, its bindings with it (foreground →
     `suspended`; a `background_running` one keeps its lifecycle);
   - a new Session opens on the **last active Board** (the closed Session's
     `active_board_id`, else the newest Session's); `default` if that Board is
     archived or missing (`core.session.last_board_unavailable`, warning); the
     first active Board if `default` is unusable too;
   - its binding for that Board is `foreground` with a **new** Core
     conversation. Exception: when **no Session row has ever existed**
     (`list_sessions(limit=1)` empty), the first Session adopts the most
     recently updated Core conversation (`ConversationService.latest()` →
     `StateRepository.latest_conversation()`), in the same `commit_switch`, so
     the voice conversation in progress survives the upgrade. The decision does
     not depend on who created `default`: a crash between `ensure_default()`
     and this step, or a store where Slice 02 already created `default`, still
     adopts at the next start. Later runs never adopt.
3. `BoardService.start(ensure_default=False)`: mode of that Board restored.

A failure raises (`core.session.start_failed`, error): Core does not start
without a Session.

### Operations

| Operation | Effect |
| --- | --- |
| `current()` | open Session + binding of its active Board. `session_not_found` (404) before start; `binding_not_found` (404) if the active Board has no binding (damaged store, never filled in silently) |
| `start_new_session(expected_session_id=None)` | one transaction: open Session closed (`new_session`) with its bindings; new Session on the **same** active Board; foreground binding with a new conversation. Boards, jobs and the interaction mode are not touched. `expected_session_id` naming a closed Session → `session_closed` (409), nothing opened (second click, two tabs) |
| `binding_for(session_id, board_id)` | get-or-create: A/B/A in one Session returns the first binding (same conversation). A new one is `suspended` with a new conversation; promotion is the switch (04b). Closed Session → `session_closed`; archived Board → `board_archived` (checked before any conversation is created) |
| `history(limit=20)` | Sessions newest first, `1 ≤ limit ≤ 100` (`invalid_session` otherwise). Read-only |

`agent_cli` is `pending` on a binding until the Control Center pool reports
the real CLI (see *Board agent pool* below).

Diagnostics: `core.session.opened` (`origin` `core_start` or `protocol`,
`adopted_conversation`), `core.session.closed` (`end_reason`, binding count),
`core.session.binding_created`, `core.session.last_board_unavailable`
(warning), `core.session.start_failed` (error). Ids and codes only.

### Session routes

Same authentication and error envelope as `/v1/boards*`
(`{"error": {"code", "message"}}`, `BoardErrorCode` and its status).

| Route | Body | Answer |
| --- | --- | --- |
| `GET /v1/sessions/current` | — | 200 `{session, binding}` (`binding.conversation_id` is Voice's conversation); 503 `core_unavailable` when Core is not ready |
| `GET /v1/sessions[?limit=N]` | — | 200 `{sessions: [...]}` newest first; 400 `invalid_session` (limit out of 1..100), `invalid_request` (not an integer, unknown parameter) |
| `POST /v1/sessions/new` | `{}` or `{expected_session_id}` | 201 `{session, binding, closed_session}`; 409 `session_closed`; 404 `session_not_found`; 400 `invalid_session` (unknown field, wrong type); 502 `board_activation_failed`; 500 `board_switch_rolled_back`; 503 `core_unavailable` |
| `POST /v1/sessions/bindings/report` | `{jarvis_session_id, board_id, agent_cli, agent_session_id}` (Control Center, Slice 04a) | 200 `{binding}`; 404 `session_not_found` / `binding_not_found`; 400 `invalid_binding`; 503 `core_unavailable` |

Client: `LocalCoreClient.current_session`, `list_sessions`, `new_session`,
`report_binding_agent`. The Control Center relays them as `/api/sessions*`
(Slice 04b).

### Voice conversation

At each activation (`PersistentVoiceRuntime.activate`) Voice reads
`GET /v1/sessions/current` and uses `binding.conversation_id`
(`voice.session.selected`; `voice.session.rebound` when it replaces a
remembered id). The pointer `runtime/.voice_conversation` (and the
conversation id of a voice switch handoff, `jarvis/app.py`) is still written,
as a **cache**: it is read only when Core does not support Sessions — a client
without the method, or a 404 whose code is `http_error` (route absent on an
older Core: aiohttp answers in text) or `session_not_found` (no open Session);
`voice.session.unsupported`, warning — and then the historical path applies
(pointer, create on 404). Any other refusal, `binding_not_found` included
(damaged store, never filled in silently), is raised like a
`context()` failure, never bypassed with a possibly stale pointer. A new
Session is followed at the next activation.

## Board agent pool (Control Center)

**Slice 04a.** Module `jarvis/runtime/board_brains.py` (`BoardBrainPool`,
`BoardBrain`), wired in `jarvis/runtime/control_center.py`; Core transport
`jarvis/runtime/core_sessions.py` (`CoreSessionTransport`). Suites:
`tests/unit/test_board_brains.py` (pool, stubbed CLI process),
`tests/unit/test_board_brains_control_center.py` (routes, real Core).

One agent per **binding**, keyed by the binding's Core `conversation_id`;
exactly one **foreground**. `ControlCenter.agent` is the foreground's agent for
the CLI chosen in the settings, so every existing `/api/agent*` route reads the
foreground unchanged; `_switch_agent` (Claude <-> Codex) applies to the
foreground only.

| Lifecycle | Process | Turns | Notices |
| --- | --- | --- | --- |
| `foreground` | live | yes | read by Core (`/api/agent/notices`) and spoken |
| `background_running` | kept live: sub-agents running, or a turn not answered yet | refused (409) | stay in the agent's queue, journaled `spoken: false` |
| `suspended` | `stop()`; Claude `session_id` kept | — | — |

- **Demotion never cancels work.** An idle agent is suspended at once; a busy
  one becomes `background_running` and suspends itself **60 s after its last
  sub-agent ends** (a new sub-agent cancels the countdown).
- **Resume** = `start(resume=True)` with the saved id: `--resume <session_id>`.
  A binding activated with a stored `agent_session_id` of the same CLI resumes
  it too (Control Center restarted).
- **Cap: 3 live CLIs.** On activation, the oldest *idle* non-foreground agents
  are suspended; busy ones never are. Still above the cap:
  `board_brain.cap_exceeded` (warning), nothing is stopped.
- **Codex** (one process per turn): never `background_running`, never
  `restart()` by the pool (it clears the thread). Demoted: `suspended`, not
  stopped while a turn is in flight; its thread id resumes it.
- **Start-up adoption.** The pool starts with one unbound foreground. The
  Control Center reads `GET /v1/sessions/current` in the background (Core may
  start later: retry 1 → 30 s) and adopts the running agent as that binding's
  foreground, without restarting it. A Core without Sessions (404 text) keeps
  the single-brain behaviour (`board_brain.sessions_unsupported`).
- **Journal context.** Each pool agent's `RuntimeJournal` is bound to
  `{board_id, jarvis_session_id}` (`RuntimeJournal.bind`), merged into the
  `data` of every line it (and its sub-agent tracker) writes.
- **Work relay.** Each Claude agent gets its own `TrackerWorkObserver`;
  `work_ingress.on_resync` resends the state of **every** pool agent.

### Routing and notices

- `POST /api/agent/ask` routes by `conversation.conversation_id` (sent by
  Core's `ControlCenterBrainBackend`): unknown or absent -> foreground; a
  demoted binding -> **409** `{ok:false, code:"brain_not_foreground"}`
  (`BoardErrorCode.BRAIN_NOT_FOREGROUND`, journal `board_brain.ask_refused`).
  Core's adapter keeps that code instead of a generic HTTP error.
- `GET /api/agent/notices` reads the foreground only. On promotion the pool
  records a **watermark** `(notice_epoch, last_notice_seq)`: the epoch change
  that follows would otherwise replay, from 0, what the agent relayed while in
  background.

### Reporting the CLI to Core

`agent_cli` / `agent_session_id` reach the binding two ways:

1. **Core-initiated activation** reads them in the answer of
   `POST /api/agent/bindings/activate` (Slice 04b's host capability).
2. **Control-Center-initiated changes** (start-up adoption, new Session,
   Claude <-> Codex switch, and after each `/api/agent/ask` once the CLI
   session id is known) call Core `POST /v1/sessions/bindings/report`
   `{jarvis_session_id, board_id, agent_cli, agent_session_id}` ->
   `SessionManager.record_agent` (`record_agent_session`). Deduplicated per
   binding; a failure is a `board_brain.report_failed` warning and is retried
   at the next turn. Accepted on a closed binding (its CLI may still finish
   work); unknown binding -> 404 `binding_not_found`; bad body -> 400
   `invalid_binding`.

### `POST /api/agent/bindings/activate` (internal, Core -> Control Center)

Body: the binding payload (`BoardConversationBinding.to_payload()`, strict,
<= 8 KiB). Answer 200 `{ok, conversation_id, board_id, jarvis_session_id,
agent_cli, agent_session_id, lifecycle, closed, previous}` — `previous` is
`{conversation_id, lifecycle}` of the demoted foreground (Slice 04b: Core
stores that lifecycle), `null` when nothing was demoted. Refusals, all
`{ok:false, code, error}`: 400 `invalid_binding`, 409 `session_closed`
(closed binding), 413 (body too large, code `invalid_binding`), 502
`board_activation_failed` (the CLI could not start; nothing changed, the
previous foreground still is). The target is brought up **before** the
previous foreground is demoted.

**Authentication.** Same model as `/api/agent/ask`, which Core already calls
without a token: the Control Center listens on loopback only. The route is
stricter: every method under `/api/agent/bindings` is in
`READ_GUARDED_ROUTES` (loopback `Host`, loopback `Origin` when present, never
`Sec-Fetch-Site: cross-site`), so a browser page cannot activate a brain.

### New Session from the Control Center

`POST /api/agent/restart {"new_conversation": true}` calls Core
`POST /v1/sessions/new`, whose transaction (Slice 04b) activates the new
binding on this Control Center **before** committing: the new binding gets a
**fresh** CLI, the old foreground is demoted (never killed) and, its Session
being closed, leaves the pool once suspended. Only when Core has no host (its
answer names a binding the pool did not activate) does the Control Center
start the fresh CLI itself (`BoardBrainPool.start_fresh`). The answer is the
new agent's snapshot plus `board_brain`. A Core refusal or an unreachable Core
changes nothing on either side: 503 with Core's code
(`agent.restart.session_failed`, error). Without Core Sessions (404 text) the
historical behaviour applies (same CLI restarted without resume;
`agent.restart.session_unavailable`). A plain restart (no body) still restarts
the foreground agent, Codex included, as the user asked.

**Accepted V1 limit:** a Claude <-> Codex switch in the settings stops the
foreground's previous CLI even if it has sub-agents running (`_switch_agent`:
two CLIs writing the same repository must never run side by side). A Board
brain resumed after such a switch never reuses the other CLI's session id
(`BoardBrain.resume_id`): it starts fresh on the new CLI.

**Notices.** `GET /api/agent/notices` names the binding its notices come from
(`conversation_id`); Core passes it to `announce_notice`, whose gate withholds a
notice of a Board without the speech authority. A foreground demoted while a
poll waits returns no notice at all, with the new foreground's epoch
(`board_brain.notices_withheld`).

Diagnostics (`runtime/trace.jsonl`): `board_brain.adopted`, `.activated`,
`.started`, `.resumed`, `.demoted`, `.suspended` (`reason`
`demoted`/`idle`/`cap`), `.cap_exceeded` (warning), `.ask_refused` (warning),
`.activation_failed` (error), `.activation_refused`, `.reported`,
`.report_failed` (warning), `.adopt_deferred` (warning), `.sessions_unsupported`,
`.stop_failed` (warning), `.suspend_failed` (error); Core
`core.session.agent_reported`.

## Switch and speech authority

**Slice 04b.** Transaction in `jarvis/core/board_service.py` (`BoardService.switch`),
authority in `jarvis/core/speech_authority.py` (`SpeechAuthority`), gate in
`jarvis/core/brain_service.py`, host in `jarvis/adapters/control_center_brain.py`
(`ControlCenterBoardHost`), Control Center relay in
`jarvis/runtime/board_routes.py`, Voice rebind in `jarvis/runtime/voice_v2.py`
and `jarvis/runtime/speech_scheduler.py`. Suites:
`tests/unit/test_board_switch.py` (transaction, rollbacks, new Session),
`test_board_speech_authority.py` (one speaker, A/B/A, withheld notice/wake,
work scoping, board block), `test_board_switch_control_center.py` (real Core
<-> real Control Center: proxy, switch, Core restart, deferral),
`test_board_context_and_host.py` (host adapter, board block, route),
`test_voice_board_rebind.py` (scheduler forward, drain, rebind without restart).

### Switch transaction

`POST /v1/boards/switch {board_id}` (Control Center: `POST /api/boards/switch`).
Under `SpeechAuthority.lock` — the same lock as a new Session, always taken
before `SessionManager`'s own lock:

| Step | Failure | Committed |
| --- | --- | --- |
| 1. validate: open Session, Board exists and is not archived; the active Board is a no-op (`changed: false`) | 404 `board_not_found`, 409 `board_archived`, 400 `invalid_board` | nothing |
| 2. `binding_for(session, board)` (A/B/A returns the first binding) | as `binding_for` | only a new `suspended` binding, reused by the next visit |
| 3. `host.activate(target)` -> `POST /api/agent/bindings/activate` | 502 `board_activation_failed` (the host's own `session_closed` / `invalid_binding` keep their code); when the host state is **unknown** (timeout, unreadable answer) the previous binding is re-activated first | nothing |
| 4. target Board's mode applied, `source="board_switch"` (an `unset` Board keeps the current mode) | previous binding re-activated on the host, 500 `board_switch_rolled_back` | nothing |
| 5. `commit_promotion`: one `commit_switch` — Session (active + visited), bindings (target foreground with the CLI the host reported, previous demoted to the lifecycle the host reported: `background_running` if it works, else `suspended`), Board `last_opened_at`; everything re-read under the lock | host and mode restored, 500 `board_switch_rolled_back` | nothing (one SQLite transaction) |
| 6. `SpeechAuthority.set(target)` — no `await` between the commit and this line | — | — |
| 7. publish `board.switched`, then `board.voice_binding.changed {conversation_id, board_id, jarvis_session_id, reason}` | — | — |

Without a host (`JarvisCoreApplication` whose brain backend has no
`board_host`: tests, headless Core) steps 3 and the host restore are skipped.
The binding lifecycle stored by Core is a snapshot taken at transitions: the
pool later suspends a background CLI 60 s after its last sub-agent without
telling Core.

### New Session

`SessionManager.start_new_session` runs under the same lock: the new Session
and binding are built without writing, `host.activate(new binding)` starts a
fresh CLI (failure: 502, nothing written; the new conversation stays an
orphan), one `commit_switch` closes the old Session with its bindings (the old
foreground takes the lifecycle the host reported) and opens the new one
(failure: old binding re-activated, 500 `board_switch_rolled_back`), then the
authority moves and `board.voice_binding.changed` (`reason: new_session`) is
published. The Control Center's own `/api/agent/restart {new_conversation:true}`
goes through this same transaction (04a QA rework): Core activates the fresh
CLI on it before committing, and the Control Center only starts one itself
when its foreground is not already the new binding (Core without a host) — no
double activation, and a failure leaves both sides unchanged (the route
answers 503 with Core's code; only an older Core without Sessions keeps the
historical restart).

### Core start and Control Center re-alignment

Core start opens a new Session (Slice 03) and sets the authority on its
binding; `BoardService.align_host()` then activates that binding on the host in
the background (`core.board.host_aligned`, or `core.board.host_align_deferred`
warning when the Control Center is down). The Control Center closes the
remaining gap itself: at its own start it adopts `GET /v1/sessions/current`
(Slice 04a), and when a turn names a conversation the pool does not know
while its foreground is bound to another one, it re-reads
`/v1/sessions/current` and activates that binding before serving the turn
(`board_brain.realigned`). A pool activation whose binding belongs to another
Session than the previous foreground marks that foreground closed (one open
Session at a time); a binding Core says is open is never kept closed (rollback
of a new Session).

### Speech authority (Core gate)

One conversation speaks: `SpeechAuthority.conversation_id`, the foreground
binding of the open Session. In `BrainOrchestrator`:

- `_emit_speech`: after the outcome is retained (durable), a speech of another
  conversation is withheld;
- `select_outcome`: refused with 409 `brain_not_foreground`;
- `announce_notice` targets the authority's conversation (not the last turn
  received); an explicit inactive conversation is withheld;
- `wake_for_work_attention` targets the authority's conversation; a wake whose
  notes all belong to other Boards is skipped (`reason: inactive_board`).

Each refusal is one `core.brain.speech_withheld_inactive_board` line
`{board_id, conversation_id, origin: speech|notice|outcome_selection|work_wake,
active_board_id, active_conversation_id}` (Slice 07 turns it into an
ATTENTION alert). Turns themselves are never refused: a background Board keeps
working, it only never speaks. Before the first Session (no authority) the
gate lets everything through.

### Board-scoped work context

`WorkObservation` / `WorkItem` / `WorkAttention` carry an optional `board_id`
(first Board affirmed wins; wire key `board_id`, `null` when unknown). Tagged
by the emitter: each pool agent's `TrackerWorkObserver` stamps its entry's
Board; Core jobs (back-brain included) resolve `requested_by_conversation_id`
through the bindings (`SessionManager.board_of`, cached). `BrainContextBuilder`
keeps the active Board's work **and** untagged work; notes of other Boards stay
pending (not delivered, not consumed) until their Board is active again, and
never wake the brain (`WorkAttentionPolicy`). `core.brain.work_context` counts
`other_boards`.

### `board` block of every turn

`BrainContext.board` (`BrainBoardContext.from_board`, the Board of the turn's
conversation) reaches the agent as `context.board` on every
`/api/agent/ask`: `board_id`, `title`, `context_summary`, `task_refs`,
`artifact_refs`, `project_refs`, and `omitted_refs` when some did not fit.
Truncation rules, budget `MAX_BRAIN_BOARD_CONTEXT_CHARS = 2 048` characters of
compact JSON:

1. title (<= 120) and summary (<= 1 500) are kept whole — the Board contract
   bounds them and refuses longer summaries, it never truncates;
2. references are added whole, tasks then artifacts then projects, each in
   Board order, while the compact JSON stays within the budget;
3. the first reference that does not fit stops the addition; it and all later
   ones are counted in `omitted_refs`. A reference is never cut.

### Voice rebind

`SpeechScheduler.handle_core_event` routes `board.voice_binding.changed`
before its conversation filter: it freezes (every later brain event, old or
new conversation, is ignored with `reason: board_rebind`), drops its reflex
and calls `PersistentVoiceRuntime.request_board_rebind`. The `run()` loop then
executes `rebind_board()`:

1. `SpeechScheduler.drain(BOARD_REBIND_DRAIN_S = 6 s)`: what is playing and
   what was already queued (authorised before the switch) may finish; at the
   deadline the rest expires (`voice.board.rebind_drained`, warning);
2. `mute(VoiceStopReason.BOARD_SWITCH)`: for Live the durable lease is closed
   before anything reopens, so the one-unresolved-live-session index holds; an
   unconfirmed close stops here (`voice.board.rebind_failed`,
   `voice_rebind_close_pending`) — never a second session over the first;
3. `activate()`: reads `GET /v1/sessions/current`, reopens on that
   conversation (`voice.board.rebound`). Voice itself never restarts.

Voice in background: nothing to reopen (`voice.board.rebind_deferred`), the
next activation reads Core. Legacy (half-duplex) mode has no scheduler; its
next activation reads Core. **No dual authority during the gap:** from step 6
of the transaction Core withholds every speech of the old Board; the frozen
scheduler accepts nothing new; the new Board's speech published before the new
scheduler subscribes is not replayed (Decision 31) but stays a durable outcome.

### Brain-originated requests

`POST /api/boards/switch` and `POST /api/sessions/new` accept
`origin: "user" | "brain"` (default `user`, never relayed to Core). A `brain`
request while an `/api/agent/ask` is in flight would move the authority under
the turn's own answer: it answers 202 `{ok: true, status: "scheduled",
action}` and runs once no turn is in flight plus `BRAIN_DEFER_GRACE_S`
(1.5 s, time for Core to publish the answer), bounded by 1 860 s. Outcome
journaled `board.request.deferred_applied` / `_failed` / `_expired` /
`_cancelled`. No turn in flight: relayed at once.

### Control Center routes

| Control Center | Core |
| --- | --- |
| `GET/POST /api/boards` | `GET/POST /v1/boards` |
| `GET /api/boards/active` | `GET /v1/boards/active` |
| `POST /api/boards/switch` | `POST /v1/boards/switch` |
| `GET/PATCH /api/boards/{board_id}` | `GET/PATCH /v1/boards/{board_id}` |
| `POST /api/boards/{board_id}/archive` | `POST /v1/boards/{board_id}/archive` |
| `GET /api/sessions/current` | `GET /v1/sessions/current` |
| `GET /api/sessions` | `GET /v1/sessions` |
| `POST /api/sessions/new` | `POST /v1/sessions/new` |

Transparent: Core's status and JSON (error envelope `{"error": {code,
message}}` included). Core down: 503 `core_unreachable`
(`board.request.core_unreachable`, warning); no Core transport: 503
`core_unconfigured`. There is no model-facing `bind_voice`, `attach_brain`
or speech-authority tool: the brain only switches Boards / opens Sessions
through these routes (MCP, Slice 05), and the runtime keeps every invariant.

Diagnostics: Core `core.board.switch_started`, `.switched`, `.switch_noop`,
`.switch_rolled_back` (error, `step`, `cause_code`), `.activation_failed`
(error, `host_state`), `.host_restored`, `.host_restore_failed` (error),
`.host_aligned`, `.host_align_deferred` (warning), `core.session.new_rolled_back`
(error), `core.brain.speech_withheld_inactive_board`, `core.job.board_unknown`
(warning), `core.brain.board_context_failed` (warning); Control Center
`board.request.*`, `board_brain.realigned`, `board_brain.realign_failed`;
Voice `voice.board.rebind_requested`, `.rebind_drained`, `.rebinding`,
`.rebound`, `.rebind_deferred`, `.rebind_failed`.

## Accepted V1 limits

1. **Shared global scene.** `scene_ref` points at the one global
   constellation; per-Board scene isolation is deferred
   (`tasks/jarvis-board-session-context-runtime/Issues/per-board-scene-isolation.md`).
2. **CLI sub-agents do not survive a Control Center / Jarvis restart** (they
   are Control Center child processes). They are reported interrupted and
   Board-attributed. Core jobs survive. Survival across a Board switch and a
   new Session is met.
