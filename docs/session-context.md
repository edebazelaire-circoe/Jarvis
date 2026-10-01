# Session Context (contract)

Canonical contract of the **Context** of a Jarvis Session. Documentation
**Level 3** for the lifecycle (contract, persistence, Core service, folders
and agent hydration, with conformance tests); HTTP/MCP surfaces land in Slice
09 of `tasks/jarvis-session-context-recording-runtime/`. Design record: that handoff's `docs/01-decision-log.md` (D02–D06) and
`slices/00-project-manager/READINESS.md` (D-SESS, D-CTX). Where they differ,
this page describes the code.

| Section | Code | Proof |
| --- | --- | --- |
| *Session lifetime* | `jarvis/domain/workspace_board.py` (`SessionEndReason`, `close_session`) | `tests/unit/test_workspace_board_contract.py` |
| *Value*, *Transitions*, *Workspace path*, *Errors* | `jarvis/domain/session_context.py` | `tests/unit/test_session_context.py` |
| *Persistence*, *Adoption* | `jarvis/ports/session_context.py`, `jarvis/adapters/sqlite_session_context.py`, `jarvis/core/session_contexts.py`, `sqlite_state._MIGRATIONS[5]` | `tests/unit/test_session_context_store.py`, `tests/unit/test_schema_migrations.py` |
| *Workspace folder* | `jarvis/adapters/context_workspace.py` (`FileContextWorkspaces`), port `ContextWorkspaceStore` | `tests/unit/test_session_context_store.py` |
| *Session lifetime* (resume), *Service*, *Workspace folder failure* | `jarvis/core/session_manager.py` | `tests/unit/test_session_manager.py`, `tests/unit/test_session_context_service.py`, `tests/integration/test_board_session_e2e.py` |
| *Agent hydration* | `BrainSessionContext` (`jarvis/domain/brain_context.py`), `jarvis/runtime/session_context_brief.py`, `--add-dir` (`claude_local.py`), `writable_roots` (`codex_local.py`), `BoardBrainPool.relaunch` | `tests/unit/test_session_context_hydration.py` |

## Session lifetime

A **Session** (`JarvisSession`, see [boards.md](boards.md)) is the durable,
user-controlled continuity boundary: it stays `open` until an **explicit new
Session** (`start_new_session`). A Core, brain or Control Center restart is
not a close reason.

- `close_session` / `close_session_with_bindings` accept only
  `end_reason = new_session`; any other reason is `invalid_session` and
  nothing changes.
- `core_restart` stays a valid **historical** value: rows closed by a Core
  start before this change decode as they are and are never rewritten.
  Nothing produces it any more.
- **Resume** (Slice 03): Core start resumes the open Session — same
  `jarvis_session_id`, active Board, conversation of the active binding and
  active Context; bindings reconciled by `resume_session_bindings`
  ([boards.md](boards.md), *Core start = resume*); trace
  `core.session.resumed`. Idempotent; a restart never creates nor closes a
  Session. `start_new_session()` is the only boundary: in the **same
  transaction** as the close, the old Session's active Context goes dormant
  (`dormant_contexts_of_closed_session`) and the new Session is born with a
  fresh active Context (`core.context.created`, `origin: new_session`).

## Value

`SessionContext` — the free-form working area of one Session. The backend
owns identity, lifecycle and location; never the content (D04).

| Field | Rule |
| --- | --- |
| `context_id` | `jctx_` + **lowercase** ASCII letters, digits, `_`, `-` (≤ 128); new ids `jctx_<uuid hex>`. Lowercase only: NTFS ignores case, `jctx_a` and `jctx_A` would be one folder |
| `jarvis_session_id` | owning Session; `jsess_` + the same safe lowercase characters. `check_session_id` is **stricter** than `JarvisSession` (prefix only) and fails closed: a Session whose id is not a safe path segment gets no Context and no folder (`invalid_context`); generated ids (`jsess_<uuid hex>`) pass. **No `board_id`** (D06) |
| `status` | `active` \| `dormant` |
| `origin` | `created` \| `adopted` (default Context of an open Session that predates Contexts) |
| `created_at` ≤ `activated_at` ≤ `last_active_at` | timezone-aware. `activated_at`: last (re)activation; `last_active_at`: last instant it was active (touched, or put to sleep) |
| `title` | optional, one printable line ≤ 120, no surrounding spaces. The codec refuses surrounding spaces; `create_context` strips them first and turns an empty or blank title into « no title » |
| `source_context_ids` | optional handoff sources (D05), ≤ 8 valid context ids, no repeat, not itself. References only: the new Context does not inherit the old folder |
| `runtime_metadata` | flat map of JSON scalars, same bounds as a Board's (≤ 16 keys, token keys ≤ 64, strings ≤ 256) |

Wire form: `to_payload()` / `from_payload()` over plain JSON dicts.
`from_payload` is strict — unknown or missing keys, wrong types, naive or
non-ISO timestamps, unknown enum values, and a `workspace_path` key are all
`invalid_context`. Validation refuses, never truncates.

## Transitions

Pure functions; each takes `now` explicitly and returns new frozen values.
Creation and activation return a `ContextTransition` (`active`, `dormanted`,
the full `contexts` set, and `changed` = the values to write **in one
transaction**).

| Function | Effect |
| --- | --- |
| `create_context(session, contexts, now=…)` | new `active` Context, origin `created` (only `adopt_context` makes `adopted`); the previous active one becomes `dormant` in the same result. `context_id=None` generates one; a given id, empty included, is validated as is |
| `activate_context(session, contexts, context_id, now=…)` | explicit reactivation of a dormant Context; the current active one sleeps. Already active: no change (`changed` empty). Unknown: `context_not_found` |
| `adopt_context(session, contexts, now=…)` | one `adopted` active Context for an open Session with none; refused once it has any (`context_conflict`) |
| `touch_context(context, now=…)` | records activity; refused on a dormant Context |
| `ensure_active(context)` | guard for implicit writes: dormant → `context_dormant` |
| `dormant_contexts_of_closed_session(closed, contexts, now=…)` | on a new Session, the closed Session's active Context goes dormant (written with the close) |
| `check_contexts(session, contexts)` | set invariants below |

Invariants:

1. Every Context of the set belongs to the Session, ids are unique.
2. An **open** Session with Contexts has **exactly one** `active`; an open
   Session with none is not adopted yet. A **closed** Session has none.
3. Nothing is created, activated or adopted in a closed Session
   (`session_closed`).
4. A dormant Context is readable but never an implicit write target; only an
   explicit reactivation (or, later, an explicitly targeted edit) touches it.
5. Clock going backwards: `create_context` and `activate_context` refuse a
   `now` behind the active (or target) Context's last activity
   (`invalid_context`). `touch_context` and putting a Context to sleep
   (`create`/`activate` of another one, `dormant_contexts_of_closed_session`)
   keep `last_active_at = max(now, last_active_at)`: the recorded last
   activity never moves back.

## Workspace path

`context_workspace_path(jarvis_session_id, context_id)` derives the folder
**relative to the data root**: `sessions/<jarvis_session_id>/contexts/<context_id>`
(`PurePosixPath`). Both ids are validated as safe path segments, so `..`,
separators, drive letters or non-ASCII never reach the filesystem. A path is
never accepted as input. Creating the folder: *Workspace folder* below.

## Persistence

`jarvis.sqlite3` **v5** (`sqlite_state._MIGRATIONS[5]`, frozen snapshot
`tests/schema/jarvis_state.v5.sql`, backup `jarvis.sqlite3.v4.bak` before the
step). Lifecycle and index only; the Context's documents live in its folder.

| Table / index | Content |
| --- | --- |
| `session_contexts` | `context_id` (PK), `jarvis_session_id` (FK → `jarvis_sessions`), `status` (`active`/`dormant`), `origin` (`created`/`adopted`), `created_at`, `activated_at`, `last_active_at`, `data` = `to_payload()`. No `board_id` |
| `idx_one_active_session_context` | unique, partial `WHERE status='active'`: at most one active Context per Session, in the file |
| `idx_one_adopted_session_context` | unique, partial `WHERE origin='adopted'`: adoption once per Session, even across two processes |
| `idx_session_contexts_session` | `(jarvis_session_id, status, created_at, context_id)` |

Port `ContextRepository` (`jarvis/ports/session_context.py`), separate from
`BoardRepository`; adapter `SQLiteContextRepository` on the shared connection
and lock (`run_serialized`):

- `get_context`, `list_contexts(session)` (oldest first), `active_context(session)`,
  `session_is_open(session)`;
- `commit_contexts(changed)` writes a transition's `changed` in **one**
  `BEGIN IMMEDIATE` transaction, dormant rows first. Refusals, all or
  nothing: a second active Context (`context_conflict`, from the unique
  index), a changed identity — session, origin or `created_at` of an existing
  row (`context_conflict`), an active Context in a closed Session
  (`session_closed`), an unknown Session (`invalid_context`). Two activations
  computed from the same snapshot: the second is refused, never two actives;
- `insert_adopted_if_absent(context)` inserts only into an open Session that
  has no Context, atomically;
- every read decodes `data` strictly and cross-checks the key columns; a bad
  row is `ContextStoreError` (`context_store_unreadable`), a SQLite failure
  `ContextStoreUnavailable` (`context_store_failed`). Both subclass the Board
  store errors, so existing 500 handling covers them. Never repaired;
- `put_context(conn, context)` is the module-level statement, for a later
  transaction that also writes a Session (Slice 03: close + dormant Context).

## Adoption

The migration inserts **no** row: an id and a clock are Python's, and a
migration never carries product data. `ensure_context(repository, session,
now=…)` (`jarvis/core/session_contexts.py`) gives an open Session that has no
Context one `adopted` active Context dated `now` (no back-dated history), and
returns `EnsuredContext(context, adopted)` for the caller to log. Repeated
calls return the same Context with `adopted=False`; concurrent calls adopt
once. A closed Session gets nothing (`None`), including one that closes
between the read and the conditional insert (re-read by `session_is_open`). An open Session whose Contexts
have no active one is surfaced as `context_conflict`, not repaired. Called by
`SessionManager` at Core start (under its lock) and again at every access
(each turn's block, `current_context`), so a failed adoption is retried.

## Workspace folder

`ensure_context_workspace(data_root, jarvis_session_id, context_id)`
(`jarvis/adapters/context_workspace.py`) creates or finds
`<data_root>/sessions/<jarvis_session_id>/contexts/<context_id>/` and returns
`ContextWorkspace(path, created)`.

- Path from `context_workspace_path` only; an invalid id is
  `invalid_context` before any disk access.
- The data root must be absolute and exist; it is resolved once, and the
  final folder must resolve to itself under it.
- Each component under the root is checked with `lstat`: a symbolic link, a
  junction or any Windows reparse point, or a file where a folder is
  expected, is `context_workspace_unsafe`; nothing is created through it.
- Created one `os.mkdir` at a time: a folder exists whole or not at all, so
  no temporary name is needed (the folder is created empty). An interrupted
  creation leaves a prefix of the chain, completed by the next call; a
  concurrent creation (`FileExistsError`) is accepted after the same check.
  Other OS failures are `context_workspace_failed`.
- Idempotent; never deletes nor empties anything.
- Threat model: local. The checks run component by component, so a process
  that swaps a component for a junction **between** its inspection and the
  next `mkdir` can make one empty folder appear outside the root before the
  final check refuses (`context_workspace_unsafe`); nothing is ever written
  or returned through it.
- Windows: a final path longer than 248 characters (folder limit without long
  paths: `MAX_PATH` 260 minus an 8.3 name) is refused before any disk access,
  `context_workspace_failed` with an explicit message, instead of a misleading
  `FileNotFoundError` half-way (possible with 128-character ids or a deep data
  root; generated ids are 38 characters).

## Service

`SessionManager` (Core, under its lock) is the only writer of Contexts, as of
Sessions. No HTTP or MCP route yet (Slice 09); the brain reads its Context
through the per-turn block below, and `GET /v1/sessions/current` carries
`context` for the Control Center.

| Call | Effect |
| --- | --- |
| `start()` | resumes or opens the Session, then guarantees its active Context (`ensure_context`) and folder |
| `start_new_session()` | old active Context dormant and new Session's Context created **in the close transaction** (`commit_switch(contexts=…)`) |
| `current_context()` | active Context (adopted if needed) + absolute folder + `workspace_error` |
| `list_contexts()` | Contexts of the open Session, oldest first |
| `create_context(title?, handoff_summary?, source_context_ids?)` | new active Context, previous one dormant (one transaction). Explicit **handoff** (D05): `source_context_ids` must be Contexts of the same Session (`context_not_found`), `handoff_summary` ≤ 8 000 characters (`invalid_context`, never truncated); together they become `handoff.md` in the **new** folder — summary text plus source ids, titles and relative folders. The old folder is never copied. Written after the commit (atomic replace); a failure is returned as `handoff_error` and logged (`core.context.handoff_failed`), the Context exists. Nothing is written without summary nor sources |
| `activate_context(context_id)` | explicit reactivation; the active one sleeps; already active: nothing written |
| `session_context(conversation_id)` | the per-turn `BrainSessionContext` (*Agent hydration*) |

**Activity ledger (Slice 04).** Every transition above also appends its
facts to the Session activity ledger ([artifacts.md](artifacts.md#activity-ledger)),
**in the same transaction** as the rows: `session.opened` (start without an
open Session, new Session), `session.resumed` (once per Core start),
`session.closed`, `context.created` (including adoption,
`context_origin: adopted`), `context.activated`, `context.dormant` (the
previous active Context, written before the new one). A refused transition
writes no event; a refused event writes no transition. Nothing is written for
an activation of the already active Context or for a repeated `start()`.

**Captures crossing a transition (Slice 05).** After each committed
`create_context`, changing `activate_context` and `start_new_session`,
`SessionManager` calls its association listeners (`add_association_listener`;
a failure is logged as `core.session.listener_failed`, never raised). The
capture owner keeps every running capture going with its **start**
association and writes `capture.association_changed` in the newly active
Session/Context ([capture.md](capture.md#session-and-context)).

Traces: `core.context.adopted`, `core.context.created` (`origin`
`core_start` / `new_session` / caller), `core.context.activated`,
`core.context.workspace_ready`, `core.context.workspace_failed`,
`core.context.handoff_written`, `core.context.summary_unreadable`,
`core.context.ensure_failed`, `core.context.read_failed`.

## Workspace folder failure

Decision (Slice 03): **Core keeps serving.** A Context folder that cannot be
created or is refused (`context_workspace_failed` / `context_workspace_unsafe`)
never stops Core start, voice, Boards or a turn: blocking the voice function
for a convenience folder would be the worse failure. The Context row stays
valid; the failure is logged once per Context and code
(`core.context.workspace_failed`, error, with the expected path), the turn's
block carries `workspace_error` and the brief tells the agent the folder is
unavailable and not to write there. Every later access (each turn,
`current_context`) retries the idempotent creation; the first success logs
`core.context.workspace_ready`. Same policy when the Context store itself is
unreadable at start (`core.context.ensure_failed`): the Session serves, the
turn leaves without the block.

## Agent hydration

Each turn Core joins `session_context` (`BrainSessionContext.to_payload()`)
next to the `board` block: Session id, active Context id and title, absolute
folder, `sessions_root`, `summary.md` of the active Context bounded to
**2 048 bytes** (same order as the 2 KB `board` block; cut on a whole UTF-8
character, `summary_clipped`), and at most **8** dormant Contexts by id and
title only, most recently active first (`omitted_dormant` counts the rest).
Jarvis never injects a dormant Context's content into the block or the brief
(D03). `summary.md` is read
only if it is a regular file inside the folder: a link, junction or folder
named so is refused (`context_workspace_unsafe`, `core.context.summary_unreadable`),
so a summary cannot make the brain read another file. A conversation of a
closed Session gets no block. Because the block travels with every turn, a
Context switch shows at the very next turn.

The Control Center renders it (`render_session_context_brief`) under
`[Contexte actif]` with the rule « C'est ton seul espace de travail implicite ;
ne modifie pas les Contexts dormants sauf demande explicite. » and the write
rule « Tu peux lire `summary.md` ; n'écris dans ce dossier que si
l'utilisateur le demande ou pour y ranger un travail substantiel. » Decision
(PM, QA rework of Slice 03): a voice turn does no bookkeeping; the agent may
read `summary.md` and writes the active folder only on request or to save
substantive work product. Keeping `summary.md` up to date is the job of the
Slice 08 enrichment worker, not of each turn.

**CLI thread is Session-scoped (decision D-THREAD, agent 0).** One CLI
conversation thread per Session is kept across Context switches: it is the
conversation memory (D02), and a Context switch never restarts the CLI. That
thread may still remember files it read or wrote in earlier turns, including
in a Context that is now dormant: Jarvis does not inject dormant content, but
it does not erase the model's memory of the Session either. The explicit,
selective handoff (`handoff.md`, D05) is the only sanctioned carry-over, and
the brief rule forbids writing dormant Contexts.

**Folder grant (`--add-dir`).** The CLI's `cwd` is the repository, so the
Context folder must be granted:

- **Scope: `<data_root>/sessions`** (`sessions_root`), not the single Context
  folder nor the Session's `contexts/`. It is constant for Core's life, so a
  Context switch or a new Session never relaunches a CLI (a relaunch would cut
  a running sub-agent — *no transition cancels work*); a per-Context grant
  would relaunch at every switch, and a new Session's folder does not exist
  yet when its fresh CLI is activated (activation precedes the commit). It
  covers only Session workspaces (not `state/`, `history/`, `memory/`). The
  rule in the brief, not the grant, keeps dormant Contexts and other Sessions
  untouched: with the default `bypassPermissions` the grant is **not** an
  authorization boundary, it lets the file tools accept the path.
- **Claude**: `--add-dir <sessions_root>` on `conversation` launches only
  (`ClaudeLocalAgent.add_dirs`, `launched_add_dirs`; verified on the installed
  CLI: `--add-dir <directories...>`, variadic, so always followed by an
  option). A relative path, a line break or a `cmd.exe` metacharacter through a
  shim is refused (`agent.add_dir_refused`, `agent_add_dir_unsafe`, logged once
  per path) and the CLI starts without it. The Control Center compares the
  root with what the launch **requested** (`requested_add_dirs`), not with
  what was granted: a refused root is attempted once per launch or root
  change, never by a relaunch at every turn.
- **Codex**: `codex exec resume` has no `--add-dir`; the config override
  `-c sandbox_workspace_write.writable_roots=['<sessions_root>']` works for
  both forms and is sent in `workspace-write` only. `danger-full-access` (the
  default) writes anywhere already; **`read-only` cannot write the Context
  folder — accepted limitation**. Not trace-verified on a real Codex turn.
- The Control Center learns `sessions_root` from `GET /v1/sessions/current`
  (`context.sessions_root`) at its start-up adoption, and from each turn's
  block. Every pool agent gets it at birth; a live Claude CLI launched without
  it is relaunched once, resumed (`BoardBrainPool.relaunch`,
  `board_brain.relaunched`), only when no turn is in flight and it has no
  work — otherwise `agent.relaunch_deferred` / `board_brain.relaunch_deferred`
  and the next safe point. A turn that arrives during a relaunch waits for it
  (same `_agent_lock`) instead of writing to the CLI being stopped.
- **Resumed thread.** At Control Center start its agent is launched fresh
  before Core names the binding. Adopting a resumed binding keeps its
  `agent_session_id`; an agent that has served no turn yet is relaunched with
  `--resume <id>` (same fallback to a fresh CLI as an A/B/A resume when the id
  is dead).

## Errors

`SessionContextError(ValueError)` with a stable `code`
(`SessionContextErrorCode`) and `status`:

| Code | HTTP |
| --- | --- |
| `invalid_context` | 400 |
| `context_not_found` | 404 |
| `context_conflict` — two active, repeated id, Context of another Session, second adoption | 409 |
| `context_dormant` — implicit write on a dormant Context | 409 |
| `session_closed` — same wire value as `BoardErrorCode.SESSION_CLOSED` | 409 |

## Ownership

Core owns Contexts. `SessionManager` (already the only writer of Sessions and
bindings) applies these transitions under its lock, in the same transaction
as the Session they belong to when a Session changes (*Service*). Folders go
through the port `ContextWorkspaceStore` (adapter `FileContextWorkspaces`,
built by `v2_app`); Core never touches the filesystem itself. Persistence:
`jarvis.sqlite3` v5 (*Persistence* above).
