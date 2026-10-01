# Session Context (contract)

Canonical contract of the **Context** of a Jarvis Session. Documentation
**Level 2** for now (vocabulary + contract + pure implementation and unit
gate); persistence, service, folders and agent hydration land in later Slices
of `tasks/jarvis-session-context-recording-runtime/` and will raise it to
Level 3. Design record: that handoff's `docs/01-decision-log.md` (D02–D06) and
`slices/00-project-manager/READINESS.md` (D-SESS, D-CTX). Where they differ,
this page describes the code.

| Section | Code | Proof |
| --- | --- | --- |
| *Session lifetime* | `jarvis/domain/workspace_board.py` (`SessionEndReason`, `close_session`) | `tests/unit/test_workspace_board_contract.py` |
| *Value*, *Transitions*, *Workspace path*, *Errors* | `jarvis/domain/session_context.py` | `tests/unit/test_session_context.py` |
| *Persistence*, *Adoption* | `jarvis/ports/session_context.py`, `jarvis/adapters/sqlite_session_context.py`, `jarvis/core/session_contexts.py`, `sqlite_state._MIGRATIONS[5]` | `tests/unit/test_session_context_store.py`, `tests/unit/test_schema_migrations.py` |
| *Workspace folder* | `jarvis/adapters/context_workspace.py` | `tests/unit/test_session_context_store.py` |

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
- Transitional: Core start still closes the open Session through
  `legacy_close_on_core_restart`, its only caller being
  `SessionManager._open_at_start`. **Resume-on-restart lands in Slice 03**
  (same `jarvis_session_id`, active Board and conversation; bindings
  reconciled), which removes that function
  ([legacy/core-restart-session-close.md](legacy/core-restart-session-close.md)).

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

- `get_context`, `list_contexts(session)` (oldest first), `active_context(session)`;
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
once. A closed Session gets nothing (`None`). An open Session whose Contexts
have no active one is surfaced as `context_conflict`, not repaired. Called at
Core start by `SessionManager` from Slice 03 (not wired yet).

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
bindings) will apply these transitions under its lock, in the same
transaction as the Session they belong to (decision of Slice 01; service in
Slice 03). Persistence: `jarvis.sqlite3` v5 (Slice 02, *Persistence* above).
