# Slice 00 — READINESS

**State: `READY`** (agent 0, 2026-10-02)

## 1. Declared vs real baseline

- Handoff planned against `main@96a9396`. Real base: `origin/main@467232f`
  (merge of `d9c6484` "trash" with `7c7871a`), branch
  `task/jarvis-board-memory-workspace-inspector`, worktree
  `C:/Projects/jarvis/bbm`. The Human's main checkout stays on `main`
  (this task adds migration v8; their live Jarvis must not apply it).
- Prerequisite `jarvis-session-context-recording-runtime`: **landed**
  (`4a9ae3c`, schema v5-v7, + `7c7871a` CONTEXT_GLOBAL). Its HV-REC-* checks
  are not recorded as passed and its `task.json` status was never updated —
  not blocking here, noted for the Human.
- README premise "current main still has core_restart closing a Session" is
  **stale**: Core start resumes the open Session; only `new_session` closes.
  `docs/boards.md:19` still says the old thing (fixed in S01).

## 2. Blind audit findings (summary; detail in docs/06-resolved-architecture.md R0)

1. No `board_kind` anywhere. Board stored as JSON payload → kind needs no DDL.
2. Artifacts/Contexts/captures have no Board link by prerequisite design;
   `Board.artifact_refs` are opaque strings → explicit link table (v8).
3. Canonical path-safety helper `jarvis/adapters/safe_folders.py` exists and
   must be reused for the Board memory root.
4. Three hydration channels already exist (Board block, SessionContext block,
   CONTEXT_GLOBAL); the Board block is extended, not a fourth channel.
5. Board/Session MCP tools are on `jarvis-console` (9 tools); artifact tools
   already exist on `jarvis-capture` → reused, not duplicated.
6. Delegated agents = Claude CLI built-in Agent tool in the same process;
   MCP inheritance documented as proven — re-proven for `jarvis-workspace` in S06.
7. No UI reads artifacts/activity/contexts; `/v1/activity` is open-Session only.
8. `session_activity.kind` has no CHECK → new ActivityKinds need no DDL.

## 3. Planning repairs applied

- `docs/06-resolved-architecture.md` added (binding; wins over docs 00-05).
- "Slice 00 contract" appended to every SLICE.md 01-09.
- Single migration v8 (`board_artifact_links`), owned by S02 only.
- DAG unchanged; HV IDs HV-WS-UI-001 (S07), HV-WS-UI-002 (S08) valid.

## 4. Decisions (agent 0, Human delegated autonomy)

- **D-TT** — No Workspace Task Type vocabulary exists (repo, workspace,
  skills-lib). Gate waived; `task_type: "waived"` in every metadata.json, as
  for the previous handoffs.
- **D-BASE** — Base on `origin/main@467232f`, not local `main@7c7871a`
  (2 commits behind; the merge changes no code under `jarvis/`).
- **D-ROOT** — Board memory root `<data_root>/boards/<board_id>/memory/`.
- **D-LINK** — Board↔artifact = v8 link table, auto-linked to the active
  Board at artifact creation; no backfill.
- **D-GRANT** — `--add-dir <data_root>/boards` like `sessions/`; semantic
  API is the parity surface (UI/MCP/sub-agents).

## 5. Baseline tests at 467232f (detached worktree bwt, main venv, foreground chunks)

Unit 373 files: 11 242 passed, 10 failed, 11 skipped. Integration 71 files:
621 passed, 1 failed (flaky), 23 skipped. Total 11 863 passed / 11 failed / 34 skipped.
`import jarvis.core.v2_app` OK. Merge-loss check on the 5 hand-resolved
files: nothing lost.

**Inherited failures — not yours, do not fix** (all also fail at `7c7871a`):

| File | # | Tests / cause |
|---|---|---|
| tests/unit/test_app.py | 1 | `test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings` — stub lacks `data_root` |
| tests/unit/test_barehands_interaction_js.py | 2 | `..._moved_by_one_zone_through_the_real_engine`, `..._resizes_only_on_two_distinct_compatible_zones` |
| tests/unit/test_brain_delegation.py | 1 | `test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available` — composed prompt ≠ `BRAIN_SYSTEM_PROMPT` constant (RÉGLAGES section) |
| tests/unit/test_interaction_mode_hud_browser.py | 1 | `test_le_mouvement_reduit_arrete_vraiment_le_halo` (order/env dependent) |
| tests/unit/test_scene_group_drag_js.py | 5 | `orbitTurns is not defined` (control_center_scene_interact.js:1414) + onPointerUp substring |
| tests/integration/test_conversation_event_rollout_gate.py | 1 | flaky: '4242' inside random hex |
| tests/unit/test_settings_mcp.py → tests/unit/test_workspace_mcp.py (moved by S06) | intermittent | `test_a_switch_and_a_new_session_asked_during_a_turn_are_scheduled_then_applied` (fails ~1/8 full-file runs at a385a1d too; 1/4 after S06) — **fixed by S6 rework (test-side race)**: the test now waits (bounded poll, 15 s ceiling) for both `board.request.deferred_applied` lines instead of Core's state; 6/6 full-file runs green |

Note: S03/S06 touch the Brain prompt; `test_brain_delegation` is already red
for an unrelated reason — implementers must not "fix" it by editing the
assertion, and must not make it worse.
