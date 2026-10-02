# Jarvis Board Memory + Workspace Inspector

## Project

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Planning source: repository `main` at `96a93963a6faf0723be5839e89545e64546ccdb7` (inspected 2026-10-02)
- Execution entrypoint: [`slices/TODO.md`](slices/TODO.md)
- Prerequisite handoff: `jarvis-session-context-recording-runtime`
- Status (2026-10-03): **implemented, awaiting Human validation** (HV-WS-UI-001, HV-WS-UI-002; script `slices/09-e2e-rollout/HUMAN-CHECKS.md`). Not done.

## Goal

Make Boards the durable, inspectable workspace/memory boundary of Jarvis and give both the human operator and Jarvis itself first-class tools to understand and manipulate that state.

The task adds a **free-form Board memory workspace** alongside the Board's structured state, integrates that durable Board memory with the Session/SessionContext system from the prerequisite handoff, exposes historical read/analysis without forcing a foreground Board switch, and adds a dedicated `jarvis-workspace` MCP server for Board/Session/memory/artifact inspection and management.

The Control Center gains two complementary surfaces:

1. a deep **Sessions & Boards Manager** reachable from the top/settings controls, for debugging and understanding the real storage, relationships, files, artifacts and runtime bindings;
2. a lightweight **Board browser/switcher** listing all Boards and their current state, reusing the existing Board control instead of creating a competing model.

## Mental model

```text
JarvisSession
  |
  +-- active SessionContext  <------ agent's current cognitive workspace
  |
  +-- loads / works on -----------------------------------------+
                                                              |
Board ---------------------------------------------------------+
  | structured backend state
  |   id, title, kind, refs, scene, timestamps, status...
  |
  +-- durable free-form Board memory workspace
  |     summary.md / research/ / meeting-notes/ / ...
  |
  +-- task refs
  +-- artifact refs ---------------------------> Artifact registry
  +-- project refs                               + provenance
  +-- conversation/binding relationships
  +-- activity / trace references
```

The SessionContext is what the active agent has in mind **now**. Board memory is the durable workspace state that lets Jarvis leave a Board, return later, and recover the work without turning every prompt into a filesystem dump.

## Locked decisions

1. **Board is a durable workspace/context boundary.** Reuse the existing Board domain rather than inventing a parallel Meeting/Presentation container.
2. **Board memory is free-form and agent-organized.** Structured management data stays in SQLite/domain models; agent memory lives in a Board-scoped filesystem workspace that agents may reorganize.
3. **Board memory and SessionContext are distinct.** They evolve in parallel. A Board switch/hydration makes relevant Board state available to the active SessionContext, but does not equate the SessionContext directory with the Board directory or copy everything blindly.
4. **Historical inspection does not imply activation.** Jarvis/sub-agents must be able to inspect a dormant/old Board, past Session, memory file or artifact without switching the user's foreground Board or speech authority.
5. **Full control uses semantic APIs, not raw database mutation.** Create/list/get/update/rename/switch/archive and memory-file operations are first-class service/API/MCP operations. No `UPDATE whatever` or unrestricted path traversal.
6. **Board memory is bounded to its backend-derived workspace root.** Path traversal, symlink escapes and arbitrary host-file access are forbidden.
7. **Artifacts stay canonical in the generic artifact registry from the prerequisite Session/Context task.** The Board manager indexes/links them; it does not duplicate media payloads or invent a second artifact store.
8. **Connections must be inspectable.** Human and agent surfaces must show Session -> Board -> binding/conversation/agent-session, Board -> memory files, Board/Session/Context -> artifacts, and artifact provenance where available.
9. **Add a dedicated `jarvis-workspace` MCP server.** Existing Board/Session tools currently on `jarvis-console` migrate to this workspace server rather than being duplicated indefinitely. `jarvis-console` returns to settings/control-plane concerns.
10. **Jarvis gets the same workspace powers as the UI.** UI and MCP call the same backend services/routes and obey the same validation/error semantics.
11. **Sub-agent inspection is supported.** A delegated agent intended to inspect historical work must receive or be able to reach the workspace read tools; this must be proven in real agent traces.
12. **Board kind is organizational metadata, not live interaction behavior.** If not already introduced by newer main, add a small `board_kind` vocabulary (`empty`, `meeting`, `presentation`) so the manager/browser can classify Boards. Opening a `meeting` Board does not itself enter Meeting behavior.
13. **Do not implement Meeting/Presentation live lifecycle here.** `preparation -> live -> completed`, start/stop buttons, OFF/SLEEP policies, wake-word behavior and detailed meeting orchestration are future work.
14. **Reuse the existing Board browser.** Current main already has `#boardsHud` / `control_center_boards.js`; evolve it into the quick Board list/switcher rather than shipping a second competing selector.
15. **The deep manager is a separate diagnostic/management surface.** It belongs with the top/settings controls and may expose more implementation detail than the everyday Board switcher.

## Important current-main evidence

Current `main` already has:

- `jarvis/domain/workspace_board.py`: Board as durable workspace/context boundary, with context summary, task/artifact/project refs, scene ref and interaction mode.
- `docs/boards.md`: one Board binding per `(Session, Board)`, A/B/A reuse, one foreground speech authority, Board switch transactions, UI/MCP parity.
- `jarvis/runtime/control_center_boards.js`: Board list/create/rename/archive/switch and New Session UI via Control Center routes.
- `jarvis/runtime/settings_mcp.py` + `jarvis/runtime/console_boards.py`: `board_list`, `board_get`, `board_get_active`, `board_create`, `board_update`, `board_archive`, `board_switch`, `session_current`, `session_new` on `jarvis-console`.
- `docs/mcp/tool-contract.md`: typed tool catalog/metadata, availability, context-budget and inspector conventions.

Current `main` still reflects the older Session lifetime (`core_restart` closes a Session). This task **must not re-implement or silently contradict** the prerequisite `jarvis-session-context-recording-runtime` handoff. Slice 00 must verify whether that handoff has landed and reconcile against the actual code before dispatch.

## Execution

Start with Slice `00-project-manager`. It is a readiness/orchestration gate and is executed by the Project Manager itself. No implementation Slice may begin until the Project Manager reports `READY`.

Every coding Slice must load `/caveman` and `/coding-guideline`.

Frontend Slices 07 and 08 must additionally load `/impeccable` and use a Claude Work Agent when the host supports that routing rule.

## QA doctrine

Every implemented Slice receives baseline `qa-verification`. Code changes additionally receive `code-review`. User-visible or runtime behavior additionally receives `runtime-validation`. Agent prompts, tools, routing, modules, MCP or agent runtime additionally receive `agent-trace-analysis` with real trace evidence.

QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, create an Issue, or escalate. A regression caused by the current Slice is blocking and may not be parked in `Issues/`.

Human validation never substitutes for machine validation. Before a Human check, exhaust deterministic/unit/integration/browser/runtime/trace validation that could catch the issue first.

## Planning blocker

The current Workspace Task Type vocabulary was not discoverable from repository evidence. Slice 00 must resolve valid Task Types and assign them before implementation dispatch. Do not invent or default Task Types.
