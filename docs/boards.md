# Boards and Sessions (contract)

Canonical contract, documentation **Level 3** (vocabulary, contract, reusable
implementation and conformance/E2E gates). Handoff
`tasks/jarvis-board-session-context-runtime/` (Slices 01–08, V1 implemented);
design record: `tasks/jarvis-board-session-context-runtime/docs/06-resolved-architecture.md`.
Where this page and the design record differ, this page describes the code.

A **Board** is the durable workspace and context boundary; a **Session** is
one human/Jarvis conversation episode that may visit several Boards. Voice
talks to the active Board's brain through Core; the runtime around it
(Sessions, Boards, bindings, switch, speech authority, alerts) is
deterministic — there is no global reasoning Brain.

| Section | What it fixes | Code | Proof |
| --- | --- | --- | --- |
| *Glossary*, *Values*, *Lifecycle*, *Invariants*, *Errors* | vocabulary, values, transitions | `jarvis/domain/workspace_board.py`, `jarvis/ports/workspace_board.py` | `tests/unit/test_workspace_board_contract.py` |
| *Board kind*, *Board memory*, *Non-activating inspection* | `board_kind`, memory locator and paths, memory errors, Board vs SessionContext ownership, memory disk store | `jarvis/domain/workspace_board.py`, `jarvis/domain/board_memory.py`, `jarvis/adapters/board_memory_store.py` | `tests/unit/test_board_memory_contract.py`, `tests/unit/test_board_memory_store.py` |
| *Persistence* | SQLite v3, default-Board migration, mode per Board | `jarvis/adapters/sqlite_workspace_board.py`, `jarvis/core/board_service.py` | `test_board_store_sqlite.py`, `test_board_service.py`, `test_board_protocol.py` |
| *Sessions* | Core start = resume the open Session, bindings, Voice conversation | `jarvis/core/session_manager.py` | `test_session_manager.py`, `test_session_protocol.py`, `test_voice_session_binding.py` |
| *Board agent pool* | one CLI per binding in the Control Center | `jarvis/runtime/board_brains.py` | `test_board_brains*.py` |
| *Switch and speech authority* | atomic switch, one speaker, Voice rebind, `board` block | `board_service.py`, `jarvis/core/speech_authority.py`, `brain_service.py`, `jarvis/runtime/board_routes.py`, `jarvis/runtime/board_brief.py` | `test_board_switch*.py`, `test_board_speech_authority.py`, `test_voice_board_rebind.py`, `test_board_brief.py` |
| *MCP tools* | `jarvis-console` parity with the screen | `jarvis/runtime/console_boards.py` | `test_settings_mcp.py`, `test_mcp_catalog.py` |
| *Control Center Boards control* | top-right Boards button and panel | `jarvis/runtime/control_center_boards.js` | `test_boards_hud_js.py`, `test_boards_hud_browser.py`, `test_boards_status.py` |
| *Alerts and absence* | Board-attributed, persisted alerts | `jarvis/runtime/background_events.py`, `jarvis/core/board_attribution.py` | `test_board_alerts*.py` |
| *End-to-end proof* | the whole runtime, real processes | — | `tests/integration/test_board_session_e2e.py` |

## Glossary

Words that look alike and must never be confused, then the runtime terms.

| Term | What it is | Where |
| --- | --- | --- |
| **Board** | The durable workspace and context boundary, like a ChatGPT Project: title, kind (`board_kind`), bounded context summary, task/artifact/project references, scene reference, interaction mode, plus a free-form **Board memory** folder. Survives Sessions. User-facing word: "Board". | `Board` in `jarvis/domain/workspace_board.py`; table `work_boards` |
| **Barehands board** | The pinned third-party AGPL stage (`stage.html`, port 8794) Jarvis presents on. Unrelated to Boards. Owns the unprefixed word `board` in code (`jarvis/ports/board.py`, config key `board`, `--no-board`). | `docs/ARCHITECTURE.md` › *Barehands (upstream board)* |
| **Session** (Jarvis Session) | One human/Jarvis conversation episode. Opens at the first Core start of a database or when a new Session is explicitly asked for; every later Core, Control Center or Brain restart **resumes** it (session-context-recording, D02); may visit several Boards; once closed, immutable history. Cross-module field `jarvis_session_id`, ids `jsess_…`. | `JarvisSession` |
| **Core conversation** | The Core `Conversation` (`conversation_id`) that carries the turns of one Session on one Board. One per binding. | `jarvis/domain/v2.py` |
| **CLI session** | The local agent's own resumable id (Claude `session_id`, Codex thread id). Stored as the binding's `agent_session_id`. Not a Session. | `jarvis/runtime/claude_local.py`, `codex_local.py` |

A **binding** (`BoardConversationBinding`) ties them together: for one
`(jarvis_session_id, board_id)` pair, the Core conversation, the agent CLI
kind and its CLI session, plus the agent process lifecycle.

| Runtime term | Meaning | Where |
| --- | --- | --- |
| **Active Board** | `active_board_id` of the open Session; `default` before the first Session | *Active Board (V1 pointer)* |
| **Board brain** | the agent CLI process of one binding, pooled in the Control Center; lifecycle `foreground` / `background_running` / `suspended` | `jarvis/runtime/board_brains.py` |
| **Speech authority** | the one conversation allowed to speak: the foreground binding of the open Session | `jarvis/core/speech_authority.py` |
| **Switch** | the Core transaction moving the active Board and the authority (`POST /v1/boards/switch`) | *Switch transaction* |
| **New Session** | closes the open Session and opens one on the same Board with a fresh conversation (`POST /v1/sessions/new`) | *New Session* |
| **`board` block** | the bounded Board context (title, summary, refs) Core joins to every turn; the only hydration of a Board brain | *`board` block of every turn* |
| **Board-attributed alert** | a background-event ledger entry carrying `board_id` / `board_title`; global, never speech | *Alerts and absence* |
| **Board memory** | free-form agent files of one Board under `<data_root>/boards/<board_id>/memory/`; not a SessionContext | *Board memory* |
| **Default Board** | `board_id="default"` (title « Board principal »), created by the migration | *Persistence* |

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
| `board_kind` | `BoardKind`: `empty` (default) \| `meeting` \| `presentation`, strict; a payload without the key decodes as `empty` (*Board kind*) |
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
`core_restart`) — set exactly when closed. `core_restart` is historical:
still decoded, never produced any more (Core start resumes the open Session,
*Core start = resume* below).

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
Session:   open ──close(new_session)──▶ closed   (terminal)
           [historical rows may carry core_restart]
Binding lifecycle (agent process):
           suspended ──promote──▶ foreground ──demote──▶ background_running | suspended
           background_running ──last sub-agent ended (+60 s)──▶ suspended
Binding status: open ──session closed──▶ closed  (never foreground again)
```

- `foreground`: live CLI, receives turns, sole speech authority.
- `background_running`: live CLI kept for its sub-agents; no turns, no speech.
  The domain does not forbid it for any `agent_cli`: keeping Codex out of it
  (a per-turn process has no live CLI to keep) is a `BoardBrainPool` rule
  (*Board agent pool*).
- `suspended`: CLI stopped; `agent_session_id` resumes it.

**A Session ends only on an explicit new Session** (D02 of
`tasks/jarvis-session-context-recording-runtime/`). `close_session` and
`close_session_with_bindings` refuse any reason but `new_session`
(`invalid_session`). A Core, brain or Control Center restart **resumes** the
open Session (*Core start = resume* below). A Session holds Contexts (one
active): [session-context.md](session-context.md).

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

## System invariants (V1)

What the running system guarantees, each proven end to end by
`tests/integration/test_board_session_e2e.py` (real Core + Control Center):

1. **One speech authority.** At any instant exactly one Core conversation may
   speak: the foreground binding of the open Session. Every other speech,
   notice, selection or wake is withheld and becomes an alert. Checked on the
   whole run by `tests/integration/board_session_timeline.py`
   (`check_single_authority`, over Core's bus and over `trace.jsonl`).
2. **No transition cancels work.** A switch or a new Session demotes the left
   brain; a CLI with running sub-agents stays `background_running` and
   finishes; only a Control Center / Jarvis restart ends CLI sub-agents
   (*Accepted V1 limits*).
3. **A switch is all or nothing.** Activation, mode and the SQLite commit
   succeed together or the previous Board, binding, CLI and mode stay
   (`board_activation_failed`, `board_switch_rolled_back`).
4. **A/B/A reuses; a restart resumes; a new Session is clean.** Within a
   Session a Board keeps its binding (same Core conversation, same or resumed
   CLI) — across Core restarts too (D02 of
   `jarvis-session-context-recording-runtime`). Only an explicit new Session
   gets a new conversation, a fresh CLI and a fresh active Context on the same
   Board; Boards, their summaries/refs, jobs and background work are
   untouched; the fresh CLI is hydrated only from the Board (`board` block)
   and its own Context (`session_context` block), never from an old
   conversation.
5. **Contexts never merge.** A turn carries only its own Board's block and
   the active Board's work (plus untagged work); other Boards' results reach
   the user as alerts, never as brain context.
6. **Mode per Board.** Entering a Board applies its stored mode; an `unset`
   Board gets the default (assistant), never the previous Board's mode; Core
   start restores the active Board's mode.
7. **Same semantics on screen and in MCP.** Both call the same Control Center
   routes and get the same codes.
8. **Absence is survivable.** Core start resumes the open Session (same id,
   active Board, conversation and active Context); the Control Center keeps or
   re-aligns its foreground on that binding and resumes its CLI thread
   (`agent_session_id`); alerts, their Board and their read state survive both
   restarts.

## Board kind

`Board.board_kind` (`BoardKind`, `jarvis/domain/workspace_board.py`) says what
a Board is for: `empty` (generic, default), `meeting`, `presentation`.
Management metadata only (handoff `jarvis-board-memory-workspace-inspector`, R1):

- stored in the Board payload JSON (`work_boards.data`): **no DDL**; a payload
  written before the field decodes as `empty`, and the next write adds it;
- edited through the existing path: `update_board(board_kind=…)`, Core
  `POST`/`PATCH /v1/boards*` (`parse_board_edits`, `EDITABLE_FIELDS`),
  relayed unchanged by the Control Center `/api/boards*`. Archived Board:
  `board_archived`. The `jarvis-console` MCP tools and the Boards panel do not
  expose it yet (Slices 06 and 08 of that handoff);
- **never** touches `interaction_mode` nor its origin, and the mode never
  changes the kind: a `meeting` Board may be in `assistant` mode. No meeting or
  presentation live behavior hangs on it.

## Board memory

**Contract (Slice 01 of `jarvis-board-memory-workspace-inspector`) and disk
store (Slice 02); the service, API, MCP and UI come in its Slices 03-08.**
Contract `jarvis/domain/board_memory.py` (pure); store
`jarvis/adapters/board_memory_store.py` (`FileBoardMemoryStore`, port
`jarvis/ports/board_memory.py`, folder rules: [local-data.md](local-data.md)).

A Board owns a free-form **memory workspace**: a folder its agents organize
themselves, with no imposed schema and no mandatory file. One convention:
`summary.md` at its root, when present, is the memory digest read by the
`board` block hydration (`MEMORY_SUMMARY_NAME`, case ignored: `Summary.md` is
the same file).

| Concept | Owns | Lives in | Lifetime |
| --- | --- | --- | --- |
| `Board` (structured) | identity, title, `board_kind`, status, timestamps, refs, scene ref, interaction mode: management metadata, validated and bounded | `work_boards.data` JSON | durable, across Sessions |
| Board memory | free-form agent files (notes, decisions, plans) | `<data_root>/boards/<board_id>/memory/` | durable, across Sessions; kept when the Board is archived (writes then refused `board_archived`) |
| `SessionContext` | the active agent's current cognitive workspace in **one** Session | `<data_root>/sessions/<jsess>/contexts/<jctx>/` ([session-context.md](session-context.md)) | one Session; no `board_id` |
| Artifact | media and derived payloads + provenance | artifact registry ([artifacts.md](artifacts.md)) | own lifecycle; linked to Boards by a link table (v8), never copied into the memory |

Board memory and SessionContext stay separate: a Board switch does not
switch, create or copy a Context, and a Context switch does not switch Boards.
`Board.artifact_refs` stay opaque legacy references, decodable and editable.

**Locator.** `board_memory_root(board_id)` gives `boards/<board_id>/memory`,
**relative** to the data root and derived from the `board_id` alone, which
must be `default` or `board_` + lowercase letters, digits, `_`, `-`
(`invalid_board` otherwise; stricter than `Board`, because the id becomes a
folder name). The adapter joins it under the data root with
`safe_folders.ensure_folder_tree` (links, junctions, Windows limits). A client
never passes an absolute path nor a root.

**`BoardMemoryPath`**: the only path a client passes. Relative POSIX inside
`memory/`, never the root itself, at most 240 characters. Refused:

| Input | Code |
| --- | --- |
| absolute (`/x`), backslash-rooted or UNC (`\x`, `\\host`), drive (`C:`, `a:b`), any `..` segment (with `/` or `\`) | `memory_path_escape` |
| empty, empty or `.` segment (`a//b`, `./a`, `a/`), backslash separator, NUL or control character, one of `<>:"\|?*`, segment starting or ending with a space or ending with `.`, Windows reserved name with or without extensions, stem cut at the **first** dot (`CON`, `nul.txt`, `aux.tar.gz`, `COM1`, `LPT9.log`, superscript `COM¹`/`LPT³`…), 8.3 short name (`~` + digits at the end of the stem, before at most one extension: `PROGRA~1`, `SUMMAR~1.MD`, `a~12.txt`; `notes~draft.md`, `~tmp`, `a~1.tar.gz` stay valid), above 240 characters, not a string | `memory_path_invalid` |

`locator(board_id)` gives `boards/<board_id>/memory/<path>`. Case is not
folded here (`Summary.md` and `summary.md` are distinct values); case and
links or junctions on disk are the adapter's job.

**Store (Slice 02).** `FileBoardMemoryStore` knows no Board: existence and
archive rules are the service's. Every operation re-finds the root with
`safe_folders.ensure_folder_tree` (created lazily, reads included) and
inspects every path component with `lstat`: a link, junction or reparse point
is never followed (`memory_path_escape`), a file where a folder is expected is
`memory_conflict`; an opened file is compared (`fstat`) to what `lstat` saw.
Returned paths are relative to `memory/`, never absolute.

**Case.** Names are case-insensitive on every system, as on NTFS (simple
per-character uppercase, not `casefold`: `ß` and `SS` stay distinct). Each
component is looked up in its folder, exact name first: `Summary.md` reads,
replaces or deletes the stored `summary.md`; `create`, `mkdir` over a file and
a `move` target that differ only by case from another entry are refused
(`memory_exists` / `memory_conflict`); `mkdir` reuses a folder stored under
another case. Returned paths (`stat`, `read`, `write`, `mkdir`, `move`,
`tree`) carry the names **as stored on disk**, so the ledger and the inspector
record the real name, not the client's spelling. A disk or root
failure is `BoardMemoryUnavailable` (`board_memory_unsafe` /
`board_memory_failed`, 500).

| Operation | Rule |
| --- | --- |
| `tree(path?, depth 1..8, max_entries 1..1000)` | depth-first, names sorted (case ignored), name + kind (`file`, `directory`, `link`) + size + mtime; links listed, never descended; `truncated` at the bound; write temporaries and unaddressable names counted in `skipped` |
| `stat(path)` | one entry |
| `read(path, offset, max_bytes 4..256 KiB)` | UTF-8 text only (`memory_not_text` on NUL or invalid UTF-8, or an offset inside a character); a page never splits a character (`next_offset`, `eof`); `sha256` of the whole file |
| `search(query, path?, limit 1..200)` | literal, case-insensitive, per line; text files of at most 256 KiB only (others in `files_skipped`); at most 500 files and 16 MiB read; `truncated` at any bound |
| `write(path, content, mode, expected_sha256?)` | at most 256 KiB per call; `create` (`memory_exists` if occupied, never overwrites even in a race), `replace` (create or overwrite), `append` (creates; final size at most 4 MiB; refused on a binary); `expected_sha256` mismatch or missing file is `memory_conflict`; parents created; temporary + `fsync` + replace |
| `mkdir(path)` | parents created; an existing folder is not an error |
| `move(source, target)` | file or folder; never over an existing entry (`memory_exists`), never into itself (`memory_conflict`); case-only rename of the same entry allowed (`a.md` -> `A.md`) |
| `delete(path, recursive=False)` | a non-empty folder needs `recursive` (`memory_conflict`); recursive removes links themselves, never their target, at most 10 000 entries (counted first) |

**Errors** (`BoardMemoryError(ValueError)`, `code` + `status`; Board-level
refusals stay `BoardErrorCode`: `board_not_found`, `board_archived`,
`invalid_board`):

| Code | HTTP | When |
| --- | --- | --- |
| `memory_path_invalid`, `memory_path_escape` | 400 | the table above |
| `memory_not_found` | 404 | no such file or folder |
| `memory_exists` | 409 | create on an occupied path |
| `memory_conflict` | 409 | `expected_sha256` mismatch, file where a folder is expected or the reverse |
| `memory_too_large` | 413 | read or write above `MAX_MEMORY_IO_BYTES` (256 KiB per call) |
| `memory_not_text` | 415 | binary or non-UTF-8 file (listed with its size, never read) |

**Ledger.** Memory mutations and Board-artifact links append
`session_activity` events of family `board` (no DDL: `kind` has no CHECK):
`board.memory.written`, `board.memory.moved`, `board.memory.deleted`,
`board.artifact.linked`, `board.artifact.unlinked`; `data` carries the
`board_id` and relative paths, never file content ([artifacts.md](artifacts.md)
› *Activity ledger*).

## Non-activating inspection

Reading any Board, Session or memory (current, other or archived) is
**side-effect free** on the foreground: it never calls the switch, never
changes the open Session's `active_board_id` nor `visited_board_ids`, never
creates, promotes or demotes a binding, never touches speech authority, the
interaction mode or `last_opened_at`. Only `POST /v1/boards/switch` (and a new
Session) activates a Board. This holds for every inspection surface: UI, MCP
and delegated sub-agents. Writing another Board's memory is allowed only
through the explicit `board_id`-targeted workspace operations, and is still
non-activating.

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
is open (only before Core start: every Core start resumes or opens a
Session). Slice 04b moves it by writing the Session (`commit_switch`) — a
second pointer would be a second truth.

### Interaction mode per Board

At Core start, before any route: `ensure_default()`, then the Session opens
(*Sessions* below), then `BoardService.start(ensure_default=False)`
re-applies the active Board's mode
(`source="board_restore"`; skipped for an `unset` Board), then subscribes to
`InteractionModeService` (`add_listener(..., with_state=True,
with_unchanged=True)`: the listener receives the change's own state, so its
`source` is never read later from the service, and also the requests that
changed nothing — a user choosing the mode already effective is a choice, and
is stored on the active Board without any mode event; Slice 04b QA rework, S1). Each change is written on the active Board by a background task
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
| `POST /v1/boards` | `{title, board_kind?, context_summary?, task_refs?, artifact_refs?, project_refs?, scene_ref?, runtime_metadata?}` | 201 `{board, active}`; 400 `invalid_title` / `invalid_board` / `context_summary_too_long` |
| `GET /v1/boards/active` | — | 200 `{board, active: true}` |
| `GET /v1/boards/{board_id}` | — | 200 `{board, active}`; 404 `board_not_found` |
| `PATCH /v1/boards/{board_id}` | any non-empty subset of the editable fields | 200 `{board, active}`; 404; 409 `board_archived`; 400 |
| `POST /v1/boards/{board_id}/archive` | empty | 200 `{board, active}` (replayable); 409 `board_is_active`; 404 |
| `POST /v1/boards/switch` (Slice 04b) | `{board_id}` | 200 `{session, binding, board, previous_board_id, changed}`; 404 `board_not_found`; 409 `board_archived`; 400 `invalid_board`; 502 `board_activation_failed`; 500 `board_switch_rolled_back`; 503 `core_unavailable` |

Unknown fields and query parameters are 400; a body above 128 KiB is 400.
`board_kind` is editable on create and `PATCH` (strict internal value, `invalid_board` otherwise) and never changes the mode. `interaction_mode` is not an editable field: the mode changes through
`/v1/interaction-mode` and the listener stores it. The Control Center relays
these routes as `/api/boards*` (Slice 04b, *Switch and speech authority*);
client methods `LocalCoreClient.list_boards`, `active_board`, `get_board`,
`create_board`, `update_board`, `archive_board`, `switch_board`.

## Sessions

**Slice 03.** Service `jarvis/core/session_manager.py` (`SessionManager`,
wired as `JarvisCoreApplication.sessions`), over the same
`SQLiteBoardRepository`. Suites: `tests/unit/test_session_manager.py`,
`test_session_protocol.py`, `test_voice_session_binding.py`.

### Core start = resume

Since Slice 03 of `jarvis-session-context-recording-runtime` (D02, D-SESS), a
restart is not a Session boundary. In `JarvisCoreApplication.start()`, after
`state.initialize()` and before the protocol server starts (so no route ever
sees Core without a Session):

1. `BoardService.ensure_default()`.
2. `SessionManager.start()`:
   - **a Session is open** (left by the previous life): it is **resumed** —
     same `jarvis_session_id`, active Board and conversation of the active
     binding; nothing is closed, no conversation is created, and nothing is
     written when the store is already consistent (`core.session.resumed`,
     with `reconciled_bindings` and `has_agent_session_id`). Repeated calls are
     idempotent. Bindings are reconciled by `resume_session_bindings`: the
     active Board's binding stays (or becomes again) `foreground` — it is the
     speech authority and the binding `align_host` re-activates, resuming its
     CLI by `agent_session_id` exactly like an A/B/A return; any other
     `foreground` binding becomes `suspended` (its CLI died with the old
     process); `background_running` / `suspended` keep their lifecycle (a
     snapshot the pool corrects itself). *Deviation from the letter of D-SESS,
     argued:* D-SESS says « foreground → suspended, then `align_host` resumes
     it »; the foreground binding is by invariant the active Board's binding,
     which is re-promoted at once, so it is kept `foreground` instead of being
     written twice — as a new Session's binding is written `foreground` before
     its CLI exists. If the active Board is archived or missing, the Session
     visits the fallback Board (`core.session.last_board_unavailable`); if its
     binding is missing (damaged store), it is rebuilt with a new conversation
     (`core.session.binding_rebuilt`, warning);
   - **no Session is open** (empty store, or a stop right after a closure): a
     new Session opens on the **last active Board** (the newest Session's
     `active_board_id`); `default` if that Board is
     archived or missing (`core.session.last_board_unavailable`, warning); the
     first active Board if `default` is unusable too; one `commit_switch`
     writes it with its first active Context;
   - its binding for that Board is `foreground` with a **new** Core
     conversation. Exception: when **no Session row has ever existed**
     (`list_sessions(limit=1)` empty), the first Session adopts the most
     recently updated Core conversation (`ConversationService.latest()` →
     `StateRepository.latest_conversation()`), in the same `commit_switch`, so
     the voice conversation in progress survives the upgrade. The decision does
     not depend on who created `default`: a crash between `ensure_default()`
     and this step, or a store where Slice 02 already created `default`, still
     adopts at the next start. Later runs never adopt.
3. The open Session's active Context is guaranteed (`ensure_context`:
   adopted once for a Session that predates Contexts) and its folder created;
   a failure there is logged and does **not** stop Core
   ([session-context.md](session-context.md), *Workspace folder failure*).
4. `BoardService.start(ensure_default=False)`: mode of that Board restored.

A Session failure raises (`core.session.start_failed`, error): Core does not
start without a Session.

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
| `GET /v1/sessions/current` | — | 200 `{session, binding, context?}` (`binding.conversation_id` is Voice's conversation; `context` = active Context, absolute folder and `sessions_root` — [session-context.md](session-context.md); a Context read failure gives `context_error` instead, the Session still answers); 503 `core_unavailable` when Core is not ready |
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

A pool stop is **deliberate** (Slice 04b QA rework, S3): the pool calls
`stop(reason=demoted|idle|cap|cli_switch|shutdown)` when the agent accepts it,
and the Claude agent then journals its process end as `agent.exit` at
**info** with `{reason, requested: true}` (`agent.stop` carries the reason
too). Only an exit nobody asked for (crash, non-zero code) stays an `agent.exit`
error in `errors.jsonl` and the Error Logs viewer. The request names **the process** it
stops, and is recorded only if that process was still running and its
output had not already ended: a crash just before the stop stays an error,
and a stop requested for a previous process never covers the next one
(QA 06/07 rework).

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
- **Ready means ready** (04a QA rework, A1). An activation or a new Session
  succeeds only once the CLI is really up. Claude:
  `ClaudeLocalAgent.wait_ready(settle_s)` after `start()` — ready on its
  `system/init` event, or when the process is still alive after
  `READY_SETTLE_S` (4 s). The real `claude -p --input-format stream-json`
  writes nothing before its first input (measured on 2.1.x), so there is no
  earlier "started" signal; a doomed start exits inside the window (unknown
  option 0.24 s, `--resume` of a missing session 3.3 s with a `result` error).
  An exit inside the window raises `RuntimeError` with the exit code and the
  CLI's stderr / error result -> the pool stops the agent
  (`stop(reason="start_failed")`), forgets a created entry and re-raises ->
  502 `board_activation_failed`, nothing committed by Core. Only a start pays
  the window: A/B/A on a live CLI does not. Codex has no process between
  turns: its readiness is `start()`, which resolves the binary and has it
  answer `--version` (`cli_catalog.probe`); a missing binary fails the
  activation the same way.
- **Dead resume id -> fresh CLI (V1 behaviour, 04a QA rework).** When the
  failed start was a `--resume <id>` of a saved id (Claude session file
  deleted or expired), the pool retries **once**, in the same activation,
  with a fresh CLI (no `--resume`): journal
  `board_brain.resume_failed_fresh_start` (warning, `board_id`,
  `old_agent_session_id`, `exit_detail`). The conversation thread is lost;
  the Board context is not — the `board` block of every turn hydrates the
  fresh CLI. The stale id is dropped: the activation answer carries the fresh
  CLI's id (or `null` until it is known — the real CLI names its session only
  at the first turn, which then reports it through
  `POST /v1/sessions/bindings/report`), and Core's binding records it. A fresh
  start that fails too -> 502 `board_activation_failed`, the entry keeps its
  old id, nothing committed. A Board therefore never becomes unswitchable
  because of a dead resume id. **Codex:** `start()` never runs
  `exec resume`, so a stale thread id is not detectable at activation; it
  surfaces at the first turn (`codex exec resume <id>` fails), not here.
- **One open Session in the pool** (04a QA rework, A2). Activating (or
  starting fresh) a binding of Session S marks **every** entry bound to
  another Session `closed`: the previous foreground and the background
  entries of the old Session alike. A closed entry already `suspended` is
  forgotten at once (the `_suspend` eviction rule); a closed entry still
  working stays `background_running`, `closed: true`, and leaves when it
  suspends. After a new Session `/api/status` `boards.bindings` therefore
  never shows an entry of the old Session as open (a Core restart resumes
  the same Session: nothing is closed).
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
`board_activation_failed` (the CLI could not start, or exited during its
readiness window — see *Ready means ready*; nothing changed, the previous
foreground still is). The target is brought up **before** the
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
| 4. target Board's mode applied, `source="board_switch"` (an `unset` Board gets the default mode, assistant — never the previous Board's mode; nothing is written on it) | previous binding re-activated on the host, 500 `board_switch_rolled_back` | nothing |
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

**Relay timeout** (Slice 04b QA rework, S2). The Control Center relays
`POST /v1/boards/switch` and `POST /v1/sessions/new` (both `/api/boards/switch`
/ `/api/sessions/new` and the `/api/agent/restart` path) with
`CORE_TRANSITION_TIMEOUT_S = 150 s` (`jarvis/runtime/core_sessions.py`), not
the client's default 10 s: Core's transaction waits for this same Control
Center (`ControlCenterBoardHost.TIMEOUT_S`, 60 s) and, when the host state is
unknown, once more to restore the previous brain. Past that deadline the
answer is truthful: 504 `core_transition_timeout` ("the outcome is unknown,
Core may still commit it; read `GET /api/sessions/current`",
`board.request.core_timeout` warning), and the restart path journals
`agent.restart.session_timeout` — never "nothing changed".
Only these two transitions may answer 504: any other relayed request whose
Core call times out (10 s client default: a read or a simple write during a
Core stall) answers **503 `core_unreachable`** (`board.request.core_unreachable`),
a write adding that its outcome is unknown (QA 06/07 rework). The page and the
`jarvis-console` tools wait longer than this relay (165 s and 170 s) and treat a
504 as "outcome unknown", never as a failure.

### Core start and Control Center re-alignment

Core start resumes the open Session (or opens the first one) and sets the
authority on its active binding; `BoardService.align_host()` then activates
that binding on the host in the background (a surviving Control Center keeps
its live CLI; a restarted one resumes the CLI thread by the binding's
`agent_session_id` — `board_brain.relaunched` / `--resume`) (`core.board.host_aligned`, or `core.board.host_align_deferred`
warning when the Control Center is down). The Control Center closes the
remaining gap itself: at its own start it adopts `GET /v1/sessions/current`
(Slice 04a), and when a turn names a conversation the pool does not know
while its foreground is bound to another one, it re-reads
`/v1/sessions/current` and activates that binding before serving the turn
(`board_brain.realigned`). A pool activation whose binding belongs to another
Session marks every pool entry of other Sessions closed (one open Session at a
time; suspended ones are forgotten); a binding Core says is open is never kept closed (rollback
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

**Two gates, no `await` between the second and the publish** (Slice 04b QA
rework, B1). The first gate may await (it reads the conversation's Board);
the path then awaits again (outcome retention, turn promotion, the
orchestrator lock, a selection write) and a switch can commit in between. So
every speakable publish (`brain.speech.requested` from `_emit_speech`, which
carries notices and error speech too, and from `select_outcome`) re-checks
`SpeechAuthority.allows()` synchronously right before `_publish`
(`_late_withheld`); a late refusal is the same withheld line with
`late: true`, and the durable outcome stays retained. A late-refused question
opens no question in the working state (it is recorded after the publish);
a late-refused notice returns `False`; a late-refused selection is 409
`brain_not_foreground` (a selection already written stays written, unspoken).
`wake_for_work_attention` publishes nothing speakable itself: its turn's
speech goes through `_emit_speech`.

**Unbound conversations are not gated.** A conversation bound to no Board
(created before Boards, or outside any Session) is not a Board: its speech
passes both gates, even while the authority moves. Only a conversation that
is the foreground binding, or whose Board lookup names a Board, is gated. A
failed Board lookup withholds by caution (`core.brain.speech_board_unknown`,
warning).

Each refusal is one `core.brain.speech_withheld_inactive_board` line
`{board_id, conversation_id, origin: speech|notice|outcome_selection|work_wake,
active_board_id, active_conversation_id, late}` an `attention` alert of that
Board (*Alerts and absence*). A `work_wake` line names the work's own Board and
`conversation_id: null` (a work note does not carry its conversation), never
the speaking conversation. Turns themselves are never refused: a background
Board keeps working, it only never speaks. Before the first Session (no
authority) the gate lets everything through.

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
**serialized** compact JSON — escapes and the `omitted_refs` / `summary_clipped`
keys included; the block never exceeds it (Slice 04b QA rework):

1. title (<= 120) and summary (<= 1 500) are kept whole — the Board contract
   bounds them and refuses longer summaries, it never truncates. Exception:
   a summary whose **escaped** form cannot fit on its own (quotes, backslashes
   and newlines cost two characters each: 1 500 quotes serialize to 3 000) is
   clipped in this block only, with `summary_clipped: true`, and no reference
   is sent (all counted in `omitted_refs`). The Board itself is never changed;
2. references are added whole, tasks then artifacts then projects, each in
   Board order, while the serialized block (with the `omitted_refs` count it
   would carry) stays within the budget;
3. the first reference that does not fit stops the addition; it and all later
   ones are counted in `omitted_refs`. A reference is never cut.

**Rendering (Slice 08).** The Control Center writes the block into the
agent's brief (`build_agent_brief` -> `jarvis/runtime/board_brief.py`,
`render_board_brief`): `Board : « <title> »` with a one-line scope rule, then
`Résumé du Board`, the non-empty reference lists, and a note when
`omitted_refs` > 0. Found missing by the Slice 08 E2E matrix: the block was
sent but never rendered, so a fresh CLI (new Session, dead resume id) was not
hydrated by anything. A turn posted straight to `/api/agent/ask` without
Core (tests, drivers) carries no block.

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

**Pending requests** (Slice 05 QA rework, B1) — accepted, not yet sent to
Core. The Control Center serves one turn at a time, so they come from the turn
in flight (or the one that just ended, during the grace):

- a second **new Session** while one is pending is **merged** (202
  `merged: true`, `board.request.deferred_merged` info): one Session opens;
- a **switch** to the same Board is merged; to another Board it **replaces**
  the pending one (202 `replaced_board_id`, `board.request.deferred_replaced`
  info): the brain's last word wins, one switch is sent. A switch back to the
  current Board replaces a pending switch too (Core then records a no-op);
- pending requests are sent **in the order they were made**, one by one; a turn
  that starts during the grace is waited for as well;
- `GET /api/boards/pending` → `{ok, pending: [{action, board_id}]}` lists
  them (the `board_switch` tool reads it, below);
- a deferred new Session that Core refuses `session_closed` (another Session
  was opened meanwhile, e.g. from the screen) is **stale**, not a failure:
  `board.request.deferred_stale` at info. Every other refusal stays
  `board.request.deferred_failed` (error).

### Control Center routes

| Control Center | Core |
| --- | --- |
| `GET/POST /api/boards` | `GET/POST /v1/boards` |
| `GET /api/boards/active` | `GET /v1/boards/active` |
| `GET /api/boards/pending` | — (Control Center only: pending brain requests) |
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

## MCP tools

**Slice 05.** Server `jarvis-console` (`jarvis/runtime/settings_mcp.py`,
always declared to the brain), logic `jarvis/runtime/console_boards.py`,
typed results `jarvis/runtime/mcp_results.py`, metadata
`jarvis/runtime/mcp_tool_meta.py`. Full table (routes, classes, results,
error codes, context cost): [mcp/tool-contract.md](mcp/tool-contract.md) §10.9.

| Tool | Does | Control Center route |
| --- | --- | --- |
| `board_list` | Boards + active id (summary rows) | `GET /api/boards` |
| `board_get` / `board_get_active` | one Board as the screen shows it | `GET /api/boards/{id}` / `/active` |
| `board_create` | new Board; does **not** switch | `POST /api/boards` |
| `board_update` | title, summary, refs (a list replaces the previous one) | `PATCH /api/boards/{id}` |
| `board_archive` | archive (never the active Board) | `POST /api/boards/{id}/archive` |
| `board_switch` | conversation and voice move to that Board; the left Board keeps its background work | `POST /api/boards/switch`, `origin: brain` |
| `session_current` | open Session, active Board, visited Boards | `GET /api/sessions/current` |
| `session_new` | a clean conversation on the **same** Board; Boards and tasks untouched (« nouvelle conversation / session ») | `POST /api/sessions/new`, `origin: brain` |

- **Same routes as the UI**, never Core; tested by resolving every request
  of the tools against `BoardSessionRoutes.routes()` and end to end on a real
  Control Center + Core (`tests/unit/test_settings_mcp.py`).
- **Brain requests.** Called during the brain's turn (the normal case), a
  switch or a new Session is answered `status: "scheduled"` and applied once
  the turn ends (*Brain-originated requests* above); outside a turn,
  `applied`. The model is told to announce it, not to claim it done. A second
  `session_new` in the same turn is merged (`merged: true`, one Session); a
  second `board_switch` replaces the first (`replaced_board_id`). A
  `board_switch` to the active Board is `unchanged` only when no switch is
  pending (`GET /api/boards/pending`); otherwise it is sent and cancels the
  pending one (`scheduled`, « Tu restes sur … »).
- **Unknown outcome.** The tools wait 170 s (longer than the relay's 150 s);
  the relay's 504 `core_transition_timeout` on a switch or new Session is
  returned as `status: "unknown"` (« Je vérifie si c'est fait. »), never as
  a failure; the brain re-reads `session_current`.
- **Voice replies** (Slice 05 QA rework, B2). `note` is one short sentence
  the brain can say as is, without internal words (« Nouvelle session à la fin
  de ta réponse. », « Passage sur « X » à la fin de ta réponse. »). The facts
  (voice follows, background work continues, Boards and tasks untouched) live
  in the tool descriptions and the server instructions, which also say: one
  short sentence.
- **Errors** keep the stable `BoardErrorCode` (tool error `Refus <code> : …`,
  the real message kept and attributed: `(Core : …)` for a Core code,
  `(Control Center : …)` for the relay's own refusals — `invalid_request`,
  `core_unreachable`, `core_unconfigured`, `core_transition_timeout`,
  `http_error` — and for a body that is not the JSON envelope). No
  `bind_voice`, `attach_brain` or speech-authority tool, and `origin` is not a
  model argument.
- Diagnostics (MCP server journal): `board.tool` (info), `board.tool_failed`
  (warning, `code`, `route`, `status`).

## Control Center Boards control

**Slice 06.** Module `jarvis/runtime/control_center_boards.js`
(`window.JarvisBoards`, installed as `window.JarvisBoardsControl`), inserted by
`ControlCenter.index` (`BOARDS_SCRIPT_MARKER`). Suites:
`tests/unit/test_boards_hud_js.py` (node, DOM double),
`tests/unit/test_boards_hud_browser.py` (headless Chrome, served page, `fetch`
double), `tests/unit/test_boards_status.py` (`boards` status block, real Core +
Control Center), z-index registry in `tests/unit/test_scene_renderer_logic.py`.
No Galaxy map or minimap (V1 non-goal).

**Placement.** Two slots declared in `control_center.html`: `#boardsHud` inside
`.topbar`, right next to the voice/agent state (top-right; top-left in the
Cosmos theme, where the bar moves) — the bar cuts pointer events, the slot
gives them back (`pointer-events:auto`); `#boardsPanel` outside the bar
(z-index 36, Cosmos 51: above dock, side panel and GPT-Live banner, below
toasts and the page confirmation), anchored under the button and clamped to the
viewport. The module refuses to install, by name (`boards.install_failed`,
`boards_host_missing`), when a slot is missing, without breaking the other page
modules.

**Button.** Always shows the active Board's title (`Board` label + title,
ellipsis, full title in `title`/`aria-label`). Tones: `ready`; `pending` (a
switch shows the target title and `Bascule · N s`, a new Session `Nouvelle
session · N s`, with a moving bar); `unavailable` (Core without Boards or
unreachable: `Indisponible` + a French phrase such as `Core ne répond pas`,
dashed; the code stays in the tooltip / `aria-label`, never as body text);
`unknown` (the status poll
itself failed: `Inconnu`, dashed). The sub-line counts other Boards whose agent
still works (`N en arrière-plan`).

**Panel** (`role="dialog"`, Escape closes and returns focus to the button,
arrow keys / Home / End move between Boards, outside click closes):

| Element | Behaviour | Route |
| --- | --- | --- |
| Board list | Core order, archived hidden; active one marked (filled dot, `aria-current`, `Actif`); other Boards whose agent is `background_running` show `En fond`. Loaded at each opening and when the status shows another active Board or Session | `GET /api/boards`, `GET /api/sessions/current` |
| Switch | click a Board; the active one just closes the panel | `POST /api/boards/switch {board_id}` |
| Create | `Nouveau Board` field + `Créer` (Enter); title trimmed, 1–120 code points, one printable line, checked before sending; refusal shown under the field; the new Board is **not** opened (focus moves to it) | `POST /api/boards {title}` |
| Rename | pencil → inline field, Enter saves, Escape cancels; unchanged title sends nothing | `PATCH /api/boards/{id} {title}` |
| Archive | page confirmation (`confirmDialog`, danger; says it is irreversible in V1); **disabled for the active Board** (`aria-disabled`, still focusable: clicking it explains why, no request) | `POST /api/boards/{id}/archive` |
| Nouvelle session | page confirmation: new conversation on the same Board; Board, tasks and background work kept; sends the Session it read as `expected_session_id` (second click / other tab → `session_closed`) | `POST /api/sessions/new` |

**No optimistic painting.** The active Board shown always comes from the
`boards` status block (1 Hz) or the list re-read after an action. A request
never marks anything active; after success **and** failure the control
re-reads `/api/status` and the list, so a failure "rolls back" by showing the
server truth, then says why.

**Pending and deadlines.** One action at a time: while one is in flight every
other action is inert (`aria-disabled`), so no double submit. One word for the
wait, `Bascule`, with a live counter in the button (`Bascule · N s`), the
Board's row and the panel note (`Bascule… N s`). Client deadlines: **165 s**
for a switch or a new Session — longer than the relay's
`CORE_TRANSITION_TIMEOUT_S` (150 s), itself longer than Core's host activation
and its restore (2 × 60 s), so the page never gives up before the server has
settled (QA 06/07 rework) — and 15 s otherwise.

**Unknown outcome.** When a switch or new Session passes its client deadline,
or the relay answers 504 `core_transition_timeout`, the control does **not**
say it failed: it keeps the action busy and shows `Résultat inconnu,
vérification… N s` (button `Vérification · N s`, note "Ne recommencez pas"),
re-reads `/api/status`, the list and `/api/sessions/current` every 2 s, then
says the verdict once (toast and note agree): done (the target Board is active
/ a new Session is open) as a success; unchanged for 20 s of readable state
as `La bascule n’a pas eu lieu : « X » reste actif. Vous pouvez recommencer.`;
still unreadable after 90 s as `Résultat toujours inconnu … Vérifiez la liste
des Boards avant de recommencer.` A late answer of the original request is
ignored; only the verification decides (`boards.switch_unknown`,
`boards.switch_confirmed`). Other actions past 15 s say the outcome is unknown
and ask to check before retrying.

**Errors.** Stable codes become French sentences (`REFUSAL` in the module:
every `BoardErrorCode`, plus `core_unreachable`, `core_unconfigured`,
`board_store_*`, `invalid_request`, network, timeout); the server's own message
stays visible under it (`code · message`). A failed switch or new Session also
raises a toast. The page `api()` now unfolds the `{"error": {"code",
"message"}}` envelope (message and `e.code`); before, it produced
`[object Object]`. Console lines `[boards] <event> {json}` for the normal path
(`boards.*_requested`, `_done`, `panel_opened`) and failures (`boards.*_failed`,
`boards.list_failed`, error level). There is no browser-to-ErrorLogs channel in
this page; the server side of each refusal is already journaled by Core
(`core.board.*`) and the Control Center relay (`board.request.*`).

**Reduced motion.** The waiting bar stops (static full bar), the panel opens
without animation; the counters keep counting.

### `/api/status` → `boards`

Read once per status beat together with the interaction mode (one
`GET /v1/boards/active`, 1 s timeout, never raises):

| Field | Value |
| --- | --- |
| `available` | Core has Boards and answered |
| `active` | `{board_id, title}` of Core's active Board, `null` when unreadable |
| `jarvis_session_id` | Session of this Control Center pool's foreground binding (the speaking one) |
| `bindings` | pool entries `{board_id, lifecycle, agent_cli, closed}`: the open Session's, plus old-Session entries still working (`closed: true`) |
| `error` | `null`, or `{code, message}`: `core_unconfigured`, `core_boards_unsupported`, `core_unreachable`, Core's code |

## Alerts and absence

**Slice 07.** The existing background-event system (`BackgroundEventLedger`,
`GET /api/background`, `POST /api/background/ack`, `#bgPills` and its
popover) carries the source Board; no second notification system. Modules:
`jarvis/runtime/background_events.py` (classification, `board_id`,
persistence), `jarvis/core/board_attribution.py` (Core stamping),
`jarvis/runtime/control_center_boards.js` (`alertBoardOf`, `elsewhereOf`,
`pillLabelOf`, `goToBoardFromAlert`), `control_center.html` (pills, popover).
Suites: `tests/unit/test_board_alerts.py` (ledger, store, Core gate, real Core +
Control Center), `tests/unit/test_board_alerts_js.py` (node, DOM double),
`tests/unit/test_board_alerts_browser.py` (headless Chrome, served page).

**Attribution path.** Every alert names the Board its trace line names:

1. A pool agent writes under its bound journal (`RuntimeJournal.bind`,
   `{board_id, jarvis_session_id}`): sub-agent finished / failed, unspoken
   notices, failed spontaneous turns.
2. Core wraps its diagnostic sink in `BoardAttributingSink`: any diagnostic
   whose `data` names a `conversation_id` and no `board_id` gets the Board of
   that conversation from `SessionManager.cached_board_of` (the bindings cache,
   no I/O; every created or read binding goes through it). An explicit
   `board_id` is never replaced (the speech gate computes its own).
3. Fallback in the Control Center: a line with a `conversation_id` but no
   `board_id` is resolved through the pool's bindings
   (`ControlCenter._board_of_conversation`).
4. Titles: the Control Center keeps `board_id -> title` from the active Board
   of each status beat and, for other Boards, a bounded
   `GET /v1/boards?include_archived=true` (2 s timeout, at most every 30 s, in
   the background, `background.board_titles_failed` on failure). The title is
   stored with the alert, so it survives a restart with Core down; a renamed
   Board is shown under its new name.

**Classification** (added to the existing table):

| Trace line | Category | Detail |
| --- | --- | --- |
| `core.brain.speech_withheld_inactive_board` | `attention` | `réponse retenue` / `relais retenu` / `résultat retenu` / `réveil retenu` (from `origin`) |
| `agent.unsolicited_result` with `spoken: false` (a background agent's notice) | `said` | — |
| `agent.subagent.finished` of a Board agent | `done` / `failed` (`failed`, `killed`, `interrupted`, `stopped`) | description |

**Never speech.** Alerts are a screen projection only: the ledger writes to
no Core route and to no brain context. A Board without the speech authority
keeps working; its completion or failure is withheld by the Core gate
(*Speech authority*) and becomes an alert. Proven by
`test_an_inactive_board_completion_never_speaks_but_raises_an_attributed_alert`
(no `brain.speech.requested`, the withheld lines become `attention` alerts of
Board A, and B's next turn context contains nothing of them).

**Global visibility.** The ledger is one per Control Center, independent of
the active Board and of the Session: every alert is visible from any Board and
after a new Session.

**Labels (decision).** In the popover, an attributed alert **always** shows its
Board: discreet `Ce Board · <title>` for the active Board, accent
`Board « <title> »` for another one. Always, because the list is global and a
label that appeared only "elsewhere" would change meaning at every switch;
the emphasis, not the presence, marks what comes from elsewhere. An alert
whose line named no Board (voice process, pre-Board history) shows no label.
The pills cannot list alerts: a pill that counts unread alerts from another
Board carries a small filled satellite dot and its label says
`… · dont N sur « <title> »`. When the active Board is unknown (Core without
Boards or unreachable, status without `boards`), nothing is marked as
"elsewhere": the pills carry no satellite, and in the popover every attributed
alert gets the neutral `Board « <title> »` label (tooltip "Board actif inconnu
pour l’instant") with **no** accent and **no** go-to action — a switch could
not succeed anyway (`alertBoardOf` returns `elsewhere: false`, like
`elsewhereOf`; QA 06/07 rework, point 4).

**Go to Board.** An alert from another (known) Board offers a button that
names its target, `Aller sur « <title> » →` (QA 06/07 rework, point 9). It
calls `JarvisBoardsControl.switchTo(board_id, {title})`, the same transaction
as the Boards panel: `POST /api/boards/switch {board_id}` (nothing else is
sent, no context travels), one action at a time, the Boards button shows
`Bascule · N s`, the clicked button shows `Bascule… N s` (`aria-busy`), a
refusal is said next to the button (`REFUSAL` sentence + `code · message`)
and in a toast, success closes the popover and re-reads the status. The
button frees itself after the control's deadline plus its verification
(165 s + 90 s) even if the request never settles (`boards.alert_jump_expired`);
an unknown outcome is verified like a panel switch. Another Boards action in
flight: nothing is sent, and it is said. Console lines
`[background] boards.alert_jump_*`. The alert stays unread after navigation
until acknowledged.

**Persistence** — `runtime/background-events.json` (`BackgroundEventStore`):

```json
{"version": 1,
 "ledger": {"seq": 12, "acknowledged": 9,
            "entries": [{"seq": 10, "ts": "...", "category": "failed", "kind": "agent.subagent.finished",
                         "label": "...", "detail": "...", "task_id": "", "board_id": "default",
                         "board_title": "Board principal", "seen": false}]},
 "trace": {"offset": 48213, "head": "<sha1 of the trace's first line>"}}
```

- Bounded to `MAX_ENTRIES` (60). Atomic write: `background-events.json.tmp`,
  `fsync`, `os.replace`.
- Written at once when a follow pass keeps an entry, on every acknowledgement
  (`POST /api/background/ack` answers `persisted`; its body is `{}` / absent
  = everything, `{seq}` = up to that sequence, `{category}` = one pill; a
  `seq` that is not a non-negative integer — string, boolean, `null`, float —
  or a malformed body is **400** `invalid_request` and acknowledges nothing,
  QA 06/07 rework point 8), and at Control Center
  stop; an offset that moves without a new entry is written at most every
  10 s. Lossless: lines re-read after a hard kill are exactly those that
  produced no entry.
- **Catch-up.** Without a file the follower starts at the end of the trace (no
  replay of old days, unchanged). With a file it resumes at the saved offset:
  lines written while the Control Center was down are read (1 MiB per pass).
- **Oversized line** (QA 06/07 rework, point 5). A trace line longer than the
  1 MiB read budget is skipped **whole**, up to its newline, so the cursor
  always rests on a line boundary (`TraceFollower.skipped_lines`, journal
  `background.trace_line_skipped`, warning). While that line is still being
  written, the cursor does not move. Before, the cursor was advanced into the
  middle of the line: the next pass failed the continuity check, re-read the
  trace from 0 (duplicates, the next alert lost) and that bad offset was
  persisted.
- **Rotation / truncation.** The saved `head` is checked once on resume: a
  trace replaced while down (deleted, rotated, truncated and regrown) has
  another first line and is re-read from 0; a trace shorter than the offset or
  gone restarts at 0; the existing continuity check (byte before the offset is
  a newline) still applies. `TraceFollower.resets` counts these restarts.
- **Corrupt file.** Unreadable JSON, wrong version, bad header or offset: the
  file is moved to `background-events.corrupt.json`, the ledger restarts empty
  (follower at the end), and the warning is visible: journal
  `background.store_unreadable` at `error` (Errors badge), `store_warning` in
  the `background` status block (one toast per page) and in
  `GET /api/background` (shown at the top of the popover). Single unreadable
  entries are dropped and counted (`N notification(s) … écartée(s)`); an
  entry whose `seq` repeats an earlier one is loaded once (counted as dropped).
  A failed
  write is `background.store_save_failed` (`error`, once per failure streak).

**`/api/status` → `background`** gains, only when non-empty: `sources`
(`[{board_id, title, counts}]`, unread alerts per source Board, newest first)
and `store_warning`. Events of `GET /api/background` gain `board_id` and
`board_title` (`null` when unknown).

## Accepted V1 limits

1. **Shared global scene.** `scene_ref` points at the one global
   constellation; per-Board scene isolation is deferred
   (`tasks/jarvis-board-session-context-runtime/Issues/per-board-scene-isolation.md`).
2. **CLI sub-agents do not survive a Control Center / Jarvis restart** (they
   are Control Center child processes). They are reported interrupted and
   Board-attributed. Core jobs survive. Survival across a Board switch and a
   new Session is met.
3. **Claude readiness costs ~4 s** on every switch or new Session that has to
   start or resume a CLI (`READY_SETTLE_S`: the real CLI writes nothing before
   its first input). A/B/A on a live CLI does not pay it.
4. **Codex:** never `background_running`; a stale thread id surfaces at the
   first turn, not at activation.
5. **Claude <-> Codex switch** in the settings stops the foreground's previous
   CLI even with sub-agents running.
6. **Archive is one-way** (no unarchive route or tool in V1).
7. **Core's stored binding lifecycle is a snapshot** taken at transitions; the
   pool suspends a background CLI 60 s after its last sub-agent without telling
   Core. `/api/status` `boards.bindings` is the live view.
8. **No cross-Board reasoning.** V1 exposes deterministic Board metadata to
   the brain (`board_list`, `board_get`); it never loads another Board's
   conversation. No Galaxy map / minimap.

## End-to-end proof

`tests/integration/test_board_session_e2e.py` (Slice 08, ~25 s, runs by
default): real `JarvisCoreApplication` + `LocalProtocolServer` and real
`ControlCenter.start` on temporary directories, pointed at each other as in
`jarvis/app.py`; `claude` replaced by a real Python process speaking
stream-json (sub-agents, relays, `fail-start`, `fail-resume`, `fail-<task>`
flags). Scenarios: v2 store migration (backup, default Board, adopted voice
conversation, legacy mode adopted once, idempotent restart); A/B/A binding
reuse, `--resume` of a suspended Board, new Session clean and hydrated from
the Board with its background work still running; inactive-Board completion
and failure as attributed alerts with no speech, surviving a Control Center
restart with re-alignment and a Core restart that resumes the same Session; mode per Board incl. `unset` default and
Core-start restore; MCP tools vs screen routes incl. archive guards; failed
switch rollback and dead-resume fallback. Every scenario ends with the
single-authority timeline check. Real-CLI evidence (real `claude`, isolated
Core + Control Center):
`tasks/jarvis-board-session-context-runtime/slices/08-e2e-rollout/EVIDENCE.md`.
