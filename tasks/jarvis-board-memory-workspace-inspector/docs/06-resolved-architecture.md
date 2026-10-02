# 06 - Resolved architecture (Slice 00, agent 0)

Written by the Project Manager after the blind code audit of `467232f`
(origin/main) and reconciliation with docs 00-05. Where this document and
docs 00-05 disagree, **this document wins**; docs 00-05 were written against
`96a9396` before the prerequisite merged. Every implementer reads this file
and the "Slice 00 contract" appended to their SLICE.md.

## R0 - Baseline facts (verified in code)

- Prerequisite `jarvis-session-context-recording-runtime` **has landed**
  (merge `4a9ae3c`, migrations v5-v7, CONTEXT_GLOBAL `7c7871a`).
  - A Session is no longer closed by `core_restart`: Core start resumes the
    open Session (`jarvis/core/session_manager.py` `_resume`); only
    `start_new_session()` closes one (`SessionEndReason.NEW_SESSION`).
  - `SessionContext` (`jarvis/domain/session_context.py`, table
    `session_contexts` v5, folder `<data_root>/sessions/<jsess>/contexts/<jctx>/`
    via `jarvis/adapters/context_workspace.py`) has **no `board_id`** by
    design (prerequisite D06).
  - Artifact registry: `jarvis/domain/artifacts.py`, tables `artifacts`,
    `artifact_relations`, `session_activity` (v6), payloads under
    `<data_root>/artifacts/<jart>/`, service `jarvis/core/artifact_service.py`.
    Artifacts carry `jarvis_session_id?` / `context_id?`, **no Board link**.
  - Canonical activity ledger: table `session_activity` (no CHECK on `kind`;
    closed set in `ActivityKind`, `jarvis/domain/session_activity.py`).
    `GET /v1/activity` serves the **open Session only** today.
- Boards: `jarvis/domain/workspace_board.py` `Board` (no kind field anywhere
  in the repo), stored as JSON `data` in `work_boards` (v3);
  `BoardService` (`jarvis/core/board_service.py`), switch under
  `SpeechAuthority.lock`.
- Agent hydration today: three channels - Board block
  (`render_board_brief`, `runtime/board_brief.py`), SessionContext block
  (`render_session_context_brief`), CONTEXT_GLOBAL system prompt layer.
  Folder grants via `--add-dir` (`runtime/claude_local.py`): `sessions/`,
  `CONTEXT_GLOBAL/`.
- Path safety: `jarvis/adapters/safe_folders.py` (lstat per component, refuses
  symlinks/junctions/reparse points, Windows path limits) is the canonical
  helper. `global_context._entry_path` is weaker - do not copy it.
- MCP: native servers are FastMCP stdio modules with
  `build_server/mcp_config/write_mcp_config/serve_stdio`, a `jarvis` CLI
  subcommand (`jarvis/app.py`), metadata in `runtime/mcp_tool_meta.py`
  (single source), passed to the Brain by one `--mcp-config` per server in
  `claude_local.py`. Board/Session tools (`board_list`, `board_get`,
  `board_get_active`, `board_create`, `board_update`, `board_archive`,
  `board_switch`, `session_current`, `session_new`) live on `jarvis-console`
  (`runtime/console_boards.py` -> Control Center `/api/boards*`,
  `/api/sessions*`).
- Delegated agents are the Claude CLI built-in `Agent` tool in the same CLI
  process; MCP inheritance is documented as proven by trace
  (`docs/mcp/plugins.md`). This task must still re-prove it for
  `jarvis-workspace`.
- UI: `#boardsHud` in `.topbar` + `control_center_boards.js`; dock
  `<nav class="dock">` (ERR TRC LAB CNV SET MCP AGT). No UI reads
  `/api/artifacts`, `/api/activity` or `/api/contexts` today.
- Stale doc: `docs/boards.md:19` still says "Core start = new Session".

## R1 - Concepts and ownership (resolves D01-D04, D13)

| Concept | Owns | Stored in |
|---|---|---|
| `Board` (structured) | identity, title, **`board_kind`**, status, timestamps, refs, scene ref, interaction mode | `work_boards.data` JSON |
| Board memory workspace | free-form agent files | `<data_root>/boards/<board_id>/memory/` |
| `SessionContext` | the active agent's current cognitive workspace | unchanged (prerequisite) |
| Artifact | media/derived payloads + provenance | unchanged registry |
| Board-artifact link | "this artifact belongs to / is used by this Board" | **new table, v8** |

- `BoardKind` = `empty | meeting | presentation`, default `empty`. Added to
  the Board payload JSON with backward decoding (missing -> `empty`). No DDL
  change for it (payload is JSON). Changing kind never touches
  `interaction_mode`.
- Board memory root is derived by the backend from `board_id` only
  (`<data_root>/boards/<board_id>/memory/`). Clients only ever pass a
  **relative POSIX path inside `memory/`**. Created lazily with
  `safe_folders.ensure_folder_tree`; archived Boards keep their memory
  (read-only for writes: `board_archived` error).
- No mandatory file inside `memory/`. **Convention only**: if
  `memory/summary.md` exists, it is the Board's memory digest used by
  hydration (R3).
- `Board.artifact_refs` (legacy opaque strings) stay decodable and editable;
  the canonical Board-artifact relation is the v8 link table. The inspector
  shows both, labelled as such.

## R2 - Schema v8 (single migration of this task)

`jarvis.sqlite3` `_SCHEMA_VERSION` 7 -> 8, one step, snapshot
`tests/schema/jarvis_state.v8.sql`:

```sql
CREATE TABLE board_artifact_links (
  board_id    TEXT NOT NULL REFERENCES work_boards(board_id),
  artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
  origin      TEXT NOT NULL CHECK (origin IN ('active_board', 'explicit')),
  linked_at   TEXT NOT NULL,
  PRIMARY KEY (board_id, artifact_id)
);
CREATE INDEX idx_board_artifact_links_artifact ON board_artifact_links(artifact_id);
```

(Exact FK column names follow the real `artifacts` DDL; S02 adjusts.)
- New artifacts are linked to the Session's `active_board_id` at creation
  (`origin='active_board'`) in the same transaction as the artifact row.
- Explicit link/unlink is a semantic operation (`origin='explicit'`).
- No backfill of pre-v8 artifacts (no reliable evidence of the Board at
  capture time); the inspector shows them under their Session/Context.
- Board memory file mutations append `session_activity` rows with new
  `ActivityKind` values (`board_memory_written`, `board_memory_moved`,
  `board_memory_deleted`, `board_artifact_linked`, `board_artifact_unlinked`)
  - no DDL change (no CHECK on kind).

Only S02 may write this migration. Nobody else touches `_MIGRATIONS`.

## R3 - Board activation and hydration (resolves D04, decision 3)

- The Board brief (`render_board_brief` / `BrainBoardContext`) gains, within
  a fixed budget: `board_kind`, the memory root **relative** locator
  (`boards/<board_id>/memory`), a bounded tree manifest (max 40 entries,
  depth 2, names+sizes), and the head of `memory/summary.md` if present
  (max 2 048 bytes, truncated marker). No full directory dump.
- The Brain CLI gets `--add-dir <data_root>/boards` (same pattern and same
  caveat as `sessions/`: a grant, not a security boundary). The agent may
  organize its active Board's memory directly with its file tools; the
  semantic API (R4) is the parity surface for UI, MCP and sub-agents.
- Brain prompt rule: write durable Board knowledge into the **active** Board's
  memory; only touch another Board's memory through the explicit
  `board_id`-targeted workspace tools.
- SessionContext and Board memory stay separate: a Board switch does not
  switch, create, or copy a SessionContext, and a Context switch does not
  switch Boards (both are already independent in code - keep it).
- Board switch -> the next turn's brief reflects the new Board (existing
  path); no extra copy.

## R4 - Workspace service and API

New Core service `jarvis/core/workspace_service.py` (name may be refined by
S04) composing existing stores - never duplicating them:

- **Reads (side-effect free, never call switch, never touch bindings or
  speech authority)**: `session_list(cursor, limit)`, `session_get(id)`
  (incl. visited Boards, Contexts, bindings), `board_inspect(id)` (Board +
  bindings + memory summary + linked artifacts count + legacy refs),
  `relations(session_id? | board_id?)`, `artifact_list(board_id? |
  session_id? | context_id?, kind?, since?, until?, cursor, limit)`,
  `artifact_relations(id)`, `activity(session_id, cursor, limit)` for any
  Session (lift the open-Session-only restriction).
- **Memory (S02 store, S05 mutations)**: `memory_tree(board_id, path?, depth)`,
  `memory_stat`, `memory_read(board_id, path, offset?, max_bytes)`,
  `memory_search(board_id, query, limit)` (bounded literal search, text
  files only), `memory_write(board_id, path, content, mode=create|replace|
  append, expected_sha256?)`, `memory_mkdir`, `memory_move(from, to)`,
  `memory_delete(board_id, path, recursive=false)` (destructive).
- Limits: path <= 240 chars relative, file read/write <= 256 KiB per call,
  text (UTF-8) only for read/write/search; binary files are listed with
  size but not read.
- Errors: stable codes (`board_not_found`, `board_archived`,
  `memory_path_invalid`, `memory_path_escape`, `memory_not_found`,
  `memory_exists`, `memory_conflict`, `memory_too_large`,
  `memory_not_text`, `session_not_found`, `artifact_not_found`), mapped to
  HTTP 4xx like the existing Board routes.
- Routes: Core `/v1/workspace/...`, relayed by the Control Center as
  `/api/workspace/...` (same relay pattern as `board_routes.py` /
  `capture_relay.py`). Existing `/api/boards*`, `/api/sessions*` routes stay
  and gain `board_kind`.

## R5 - `jarvis-workspace` MCP (S06)

- New module `jarvis/runtime/workspace_mcp.py`, subcommand
  `jarvis workspace-mcp`, config `runtime/workspace-mcp.json`, passed to the
  `conversation` profile like `jarvis-console`. Metadata in
  `mcp_tool_meta.py` with its own category (not "settings").
- The 9 Board/Session tools **move** from `jarvis-console` (same names, same
  semantics; `ConsoleBoardTools` becomes the workspace server's client).
  `jarvis-console` keeps only `settings_*`. No alias left behind.
- New tools (final names fixed by S06 within the context-budget gate):
  `session_list`, `session_get`, `workspace_inspect`, `board_memory_tree`,
  `board_memory_read`, `board_memory_search`, `board_memory_write`,
  `board_memory_move`, `board_memory_delete`, `board_artifacts`,
  `board_artifact_link`. Artifact get/search/relations already exist on
  `jarvis-capture` (`artifact_search`, `artifact_get`): **reuse them, do not
  duplicate**; `board_artifacts` only lists links.
- Brain prompt / brief references that name `jarvis-console` Board tools are
  updated.
- Proof: real Brain trace (board list -> memory write -> memory read) and a
  real delegated sub-agent trace inspecting an old Board without changing
  `active_board_id` / foreground binding / speech authority.

## R6 - UI (S07, S08)

- **S07 deep manager**: new dock button (label `WSP`, title "Sessions &
  Boards") opening a full panel module `control_center_workspace.js`
  (marker/constant/z-index per the Control Center module pattern). Views:
  overview (current Session/Board/Context/binding), Sessions (history),
  Boards (all, incl. archived), relations, memory tree + viewer + editor
  (write/move/delete, delete visibly destructive with confirmation in-panel,
  not `window.confirm`), artifacts + provenance (via existing
  `/api/artifacts*`). Read-only of foreground state; it may call the same
  switch route as the HUD, never its own.
- **S08 quick browser**: evolve `#boardsHud` (no second selector): show
  `board_kind`, last opened, archived filter, kind on create/edit, and a link
  "Inspecter" opening the deep manager on that Board.

## R7 - Slice order and worktrees

Order unchanged: 01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09.
S07 may start after S05 in parallel with S06 only in a separate worktree.
Implementer in `C:/Projects/jarvis/bbm`; QA in detached `bqa`/`bqb`; the
Human's main checkout `C:/Projects/jarvis/jarvis` stays on `main` because
this task adds migration v8.
