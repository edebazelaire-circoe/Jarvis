# Issues / open implementation gates

Only unresolved implementation facts belong here. Product decisions in `docs/01-decisions.md` are locked unless a genuine contradiction is found. Evidence for every resolution: `references/readiness-audit.md`.

## I-001 — Workspace Task Type vocabulary unresolved

**Status:** RESOLVED by Slice 00 (2026-10-20) — waived by agent 0.

No Workspace Task Type vocabulary exists in the repository or in the other handoffs (all `null`/`waived`). Agent 0 applied the established precedent (`jarvis-unified-chat-and-board-drop`, `slices/00-project-manager/metadata.json`): `"task_type": "waived-by-agent-0"` with a `task_type_blocker` field explaining the waiver, in every Slice `metadata.json` and in `task.json`. No label was invented.

## I-002 — Exact persistence owner for mission collaboration history must be verified on HEAD

**Status:** RESOLVED by Slice 00 (2026-10-20).

No existing durable store covers the need (Work State is memory-only; Scene is a projection with brain/user-writable `category`; Conversation Events are conversation-scoped and allow-listed; `artifact_relations` links artifacts; the mission dossier `mission.md` is shared prose). Seam: additive tables in `jarvis.sqlite3` through `_MIGRATIONS[10]` of `jarvis/adapters/sqlite_state.py` (9 -> 10, automatic backup, snapshot `tests/schema/jarvis_state.v10.sql`), dedicated adapter `jarvis/adapters/sqlite_mission_history.py` on the shared connection, port `jarvis/ports/mission_history.py`, Core service `jarvis/core/mission_history.py`. Renumber if another branch lands v10 first.

## I-003 — Interview-to-execution authorization is intentionally not a new universal gate

**Status:** non-blocking; clarified by Slice 00.

Main already carries `EXECUTION_GATE_RULE` (`jarvis/domain/subagent_roles.py:314`): after the Interviewer's `PRÊT :`, the brain summarizes and asks for oral consent. It was decided by the user in `jarvis-subagent-roles-interview`, predates this handoff and only applies to case B (framed requests). It is therefore part of the "existing confirmation/permission policy" that D21 preserves, not a new universal gate. Slice 07 keeps it as is (neither generalized nor removed). `HUMAN_DECISION_REQUIRED` still applies if a *new* global gate appears necessary.

## I-004 — Meaning of "ephemeral" (Q1 of the readiness audit)

**Status:** resolved by agent 0 (2026-10-20, handle-task autonomy, recommended option): one flag, current silence kept; the brain rule widens to small self-evident corrections whose visible change is the report; a fix whose confirmation is awaited stays an ordinary one-agent task; failures are always announced. The Human may revert.

On main, an ephemeral task is one whose result the user does not expect: its success is silent and the brain prompt forbids it for work whose result is awaited (`jarvis/runtime/claude_local.py:101`). This handoff uses ephemeral for small corrections that should not clutter history (D07/D08). Recommendation: keep one flag with its current silence and widen the brain rule to small self-evident corrections whose visible change is the report; a bug fix whose confirmation is awaited stays an ordinary one-agent task. Failures are always announced. Alternative: two flags (history retention vs announcement).

## I-005 — Marker collision: ephemeral cannot carry a profile/role today

**Status:** RESOLVED by Slice 01 (2026-10-20) — one composed grammar, `jarvis/domain/agent_markers.py` (`parse_head`), called by both `routing_hook.py` and `agent_tasks.py`; `[éphémère]` may sit anywhere in the head (once) and is transparent; contract in `docs/subagent-roles.md` §2; tests `tests/unit/test_agent_markers.py`.

`[éphémère]` must lead the description (`agent_tasks.py:73`, `fullmatch` at `:196`) while the routing hook reads `[profile] [role]` at the head with ASCII-only patterns (`routing_hook.py:67`, `:71`): `[éphémère]` does not match them, `_markers` returns `(0, None)`, and `read_profile`/`read_role` fall back to the `prompt` key (`:90`, `:122`), else `general`/`None`; the other order keeps profile/role but loses the ephemeral flag. Slice 01 defines one composed grammar parsed identically on both sides.

## I-006 — Overlapping worktrees

**Status:** non-blocking; Human decisions Q2/Q3 of the readiness audit.

- `subag` (`jarvis-subagent-roles-interview`): backend merged in main; remaining scope absorbed here (Slice 10 Settings tab, `docs/subagent-roles.md` in Slices 01/04, sandbox trial in Slices 07/13). Drive move and worktree removal stay with the Human.
- `eph` (`task/jarvis-ephemeral-tasks`): superseded prototype with 13 uncommitted files (runtime archive of ephemeral stars). Not reused, not modified; kept until the Human decides.
