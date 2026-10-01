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
| `context_id` | `jctx_` + letters, digits, `_`, `-` (≤ 128); new ids `jctx_<uuid hex>` |
| `jarvis_session_id` | owning Session; `jsess_` + the same safe characters. **No `board_id`** (D06) |
| `status` | `active` \| `dormant` |
| `origin` | `created` \| `adopted` (default Context of an open Session that predates Contexts) |
| `created_at` ≤ `activated_at` ≤ `last_active_at` | timezone-aware. `activated_at`: last (re)activation; `last_active_at`: last instant it was active (touched, or put to sleep) |
| `title` | optional, one printable line ≤ 120, no surrounding spaces |
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
| `create_context(session, contexts, now=…)` | new `active` Context; the previous active one becomes `dormant` in the same result |
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
5. A clock behind the current active Context's last activity is refused
   (`invalid_context`), never clamped.

## Workspace path

`context_workspace_path(jarvis_session_id, context_id)` derives the folder
**relative to the data root**: `sessions/<jarvis_session_id>/contexts/<context_id>`
(`PurePosixPath`). Both ids are validated as safe path segments, so `..`,
separators, drive letters or non-ASCII never reach the filesystem. A path is
never accepted as input. Creating the folder is Slice 02/03.

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
Slice 03). Persistence: `jarvis.sqlite3` v5 (Slice 02).
