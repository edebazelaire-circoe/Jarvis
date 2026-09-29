# Boards and Sessions (contract)

Handoff `tasks/jarvis-board-session-context-runtime/`. Authoritative design:
`tasks/jarvis-board-session-context-runtime/docs/06-resolved-architecture.md`.

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
| Board Brain processes (one agent per binding) | Control Center | `jarvis/runtime/board_brains.py` `BoardBrainPool`, behind `BoardBrainHost` (Slice 04a) |
| UI / MCP entry points | Control Center | `/api/boards*`, `/api/sessions*` proxying Core `/v1/boards*`, `/v1/sessions*`; `jarvis-console` MCP calls the same routes (Slices 05–06) |
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
table and key); it is never skipped nor repaired.

- **Closed Session guard.** Saving any value over a `closed` row raises
  `session_closed`; the row is untouched. A second `open` Session is refused
  (`invalid_session`); a second foreground binding, or a binding to a missing
  Session/Board, is `binding_conflict`.
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
  idempotent across restarts and concurrent starts. Adopting the most recent
  Core conversation into the first Session's binding is Slice 03.

### Active Board (V1 pointer)

No separate pointer table: the active Board is `active_board_id` of the
**open Session** (`jarvis_sessions`, persisted), and `default` when no Session
is open. Until Slice 03 opens a Session at Core start, the active Board is
therefore always `default`. Slices 03/04b move it by writing the Session
(`commit_switch`) — a second pointer would become a second truth the moment
Sessions exist.

### Interaction mode per Board

`BoardService.start()` (at Core start, before any route) runs
`ensure_default()`, then re-applies the active Board's mode
(`source="board_restore"`; skipped for an `unset` Board), then subscribes to
`InteractionModeService`. Each change is written on the active Board by a
background task (`drain()` waits for them; Core `stop()` drains before closing
the DB):

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

Unknown fields and query parameters are 400; a body above 128 KiB is 400.
`interaction_mode` is not an editable field: the mode changes through
`/v1/interaction-mode` and the listener stores it. The Control Center
`/api/boards*` proxy is Slice 05; the client methods already exist
(`LocalCoreClient.list_boards`, `active_board`, `get_board`, `create_board`,
`update_board`, `archive_board`).

## Accepted V1 limits

1. **Shared global scene.** `scene_ref` points at the one global
   constellation; per-Board scene isolation is deferred
   (`tasks/jarvis-board-session-context-runtime/Issues/per-board-scene-isolation.md`).
2. **CLI sub-agents do not survive a Control Center / Jarvis restart** (they
   are Control Center child processes). They are reported interrupted and
   Board-attributed. Core jobs survive. Survival across a Board switch and a
   new Session is met.
