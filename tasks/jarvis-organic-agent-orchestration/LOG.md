# LOG — jarvis-organic-agent-orchestration

## 2026-10-19 — Handoff creation

- Product interview consolidated into an implementation handoff.
- Project resolved to JARVIS; repository resolved to `edebazelaire-circoe/Jarvis`.
- Baseline observed: `main@82051c3ada7a695b88042e8772e7da35bbae2513`.
- Existing Core Work State, Agents panel, constellation Scene, role/loadout seam, Conversation Events and prefab system audited through current repository docs/code contracts.
- Locked correction: this feature is **organic orchestration**, not a planned workflow engine and not a “minimum complexity” doctrine.
- Locked history rule: completed non-ephemeral execution remains inspectable; ephemeral agents do not remain as persistent constellation/history nodes.
- Workspace Task Type vocabulary could not be authoritatively resolved from the available project sources during handoff creation; implementation is blocked on Slice 00 rather than inventing a value.
- Google Drive publication is part of handoff completion; remote path: `Jarvis/task/to-do/jarvis-organic-agent-orchestration/`.

## 2026-10-20 — Slice 00 readiness (blind audit, reconciliation)

- Worktree `C:/Projects/jarvis/orch`, branch `task/jarvis-organic-agent-orchestration` from `main`. Audited HEAD `336f21be` (local `main`). Corrected by the QA rework: `origin/main` is still `82051c3a`; local `main` carries 2 unpushed commits (`3351ef59`, `336f21be`) — the first check compared only `HEAD..origin/main`. Only commit since the handoff baseline `82051c3a`: `3351ef59` (scene/dossier/wheel UI fixes) — no impact on contracts, watch `control_center_scene_page.js` for Slice 09.
- The repository has no `docs/workflows/AGENT_TASK_LIFECYCLE.md`: fallback on the project memory (no dev branch, branch from `main`, dedicated worktree, one writer per worktree, merge `origin/main` into the task branch before closing).
- Blind audit performed on code and repository docs before reading this handoff; evidence with `file:line` in `references/readiness-audit.md`.
- Main finding: the handoff missed what was already on main at its own baseline — role registry `jarvis/domain/subagent_roles.py` with Interviewer, mission dossier, `EXECUTION_GATE_RULE`, editable role instructions and `GET /api/subagent-roles` (`e05d931d`), and the merged ephemeral-task feature (`3bc7acf2`). Slices 01/04/07/10 amended to extend these instead of recreating them.
- Decision: absorb the remaining scope of `jarvis-subagent-roles-interview` (Settings tab -> Slice 10, `docs/subagent-roles.md` -> Slices 01/04, sandbox trial -> Slices 07/13). Current role ids kept (they key persisted user overrides).
- Worktree `eph` read only: superseded prototype (runtime archive of ephemeral stars), not reused, not modified.
- I-001 resolved by waiver of agent 0 (`waived-by-agent-0`, precedent `jarvis-unified-chat-and-board-drop`); `task.json` blocker removed; every Slice `metadata.json` updated with `task_type_blocker`, `freshness_paths`, readiness.
- I-002 resolved: Mission History in `jarvis.sqlite3` via `sqlite_state._MIGRATIONS[10]` + dedicated adapter/port/service.
- I-003 clarified (existing scoped gate preserved); new issues I-004 (meaning of ephemeral, before Slices 05/07), I-005 (marker collision, Slice 01), I-006 (overlapping worktrees).
- Gap recorded: D08 not met on main (ephemeral stars persisted, only hidden by the page) — Slice 08.
- Freshness check before each dispatch defined (`references/readiness-audit.md` §7).
- Baseline tests: `test_subagent_roles.py`, `test_work_state_contracts.py`, `test_schema_migrations.py` — 123 passed. No product code changed; JARVIS not started.
- **Readiness: READY.** Next: independent QA (qa-verification) of Slice 00, then dispatch Slice 01.
- Agent 0 decisions (autonomous, recommended options): Q1/I-004 resolved — one ephemeral flag, silence kept, brain rule widened to small self-evident corrections (Slices 05/07 unblocked). Q2 (archive `jarvis-subagent-roles-interview` to done, remove worktree `subag`) and Q3 (fate of the 13 uncommitted files in `eph`) left to the Human: Drive moves and uncommitted work are Human-owned.

## 2026-10-20 — Slice 00 rework after independent QA (PASS_WITH_NOTES)

- Process: Slice 00 was executed by a Work Agent delegated by agent 0, then reviewed by an independent QA (PASS_WITH_NOTES). This is a deliberate choice.
- N1: drift statement corrected (`git ls-remote origin main` -> `82051c3a`; local `main` 2 commits ahead, unpushed). Freshness check §7 now compares `HEAD..main` and `HEAD..origin/main` (steps 1, 2, 4).
- N2: I-004 decision of agent 0 (`6f2ca77d`) carried into `slices/TODO.md`, `readiness-audit.md` (header, §2.4, §6 Q1), metadata 05/07 `dispatch_precondition`; Slice 07 named owner of the ephemeral rule of the brain prompt (`claude_local.py:101`); Slice 01 amendment aligned (contract only, no prompt edit).
- N3: nested spawn probe run in the scratchpad (`claude -p`, haiku, 2 short calls, no JARVIS, no Core port). CLI `2.1.304`. Proven: a `general-purpose` sub-agent calls `Agent` (`spawn_depth` 2, `parent_tool_use_id`, `NESTED_OK`); it sees the session's MCP tools; the `PreToolUse` hook fires for the nested call and carries the caller's `agent_id` and `tool_use_id`. D04 feasible natively; readiness stays READY. Remaining sandbox checks for Slice 05: Jarvis `--mcp-config` servers in sub-agents, depth > 2, custom agent types.
- N4: I-005 mechanics corrected (ASCII-only `PROFILE_PATTERN`/`_BRACKET`, `[éphémère]` does not match; fallback on the `prompt` key); Slice 01 tests retargeted.
- N5: D25 arbitration — the `PreToolUse` hook is the source of role/ephemeral/mission/parent facts sent to Core; `agent_tasks.py:1011` stays diagnostic (Slices 03, 05).
- N6: Conversation Events `subagent.*` spans (ephemeral included) are diagnostic, not D08 history; must not feed Mission History nor the graph (Slices 03, 08).
- Minor: `ROLE_BASE_PROFILE` at `loadout_resolver.py:45`.
- **Readiness: READY** (unchanged). Open Human questions: Q2, Q3 (non-blocking).

## 2026-10-20 — Slice 01 implemented (QA pending)

- Freshness: `git log HEAD..main` empty, `git diff HEAD main -- <freshness_paths>` empty (main = `336f21be`).
- Role contract: `jarvis/domain/subagent_roles.py` extended (no second module). Ids kept (`interviewer`, `research`, `web-research`, `coder`, `concept`); additive `research-lead` (Direction de recherche) and `qa` (Contrôle qualité), defined but `enabled=False` until Slices 04/07 wire them (brain prompt and hook behaviour unchanged). New per-role data: `RoleVisual` (icon, accent token, badge, unique per role), `can_own_mission` (requires `can_spawn`), `can_spawn` (must agree with the `Agent` tool in `tools`; `coder` now lists it), `work_methods`/`default_work_method`, `loadout_role`. `ROLE_ALIASES = {reviewer: qa}`; `resolve_role` -> `declared | alias | disabled | unknown | undeclared`, reserved ids `undeclared`/`unknown`. `as_dict` (hence `GET /api/subagent-roles`) gains these fields additively; `schema_version` left at 1 for Slice 04.
- I-005 resolved: one head-marker grammar `jarvis/domain/agent_markers.py` (`parse_head`), used by `routing_hook` (`read_profile`, `read_role`, `_markers`, `read_playbook_role`, `strip_profile`) and `agent_tasks.parse_ephemeral_description`. `[éphémère]` is accepted once anywhere in the head and is transparent; prompt fallback kept for profile/role only; existing descriptions read as before. `AgentDeclaration` (+ `declaration_from_hook_event`) is the stable form the hook will send to Core (D25) — not wired.
- Missions: `jarvis/domain/missions.py` — `Mission` (parent/root, dossier path reference, lifecycle open -> closed once), `AgentInstance` (immutable role/ephemeral/mission/owner/parent, Work State identity, no execution status), `reconcile_instance` (`immutable_field`), `transfer_ownership` (explicit handoff ref only), `check_mission_tree` (no cycle, bounded depth 16, owner consistency), `retained_in_history` (ephemeral lowered on failure), ephemeral cannot own a mission.
- Work Methods: `jarvis/domain/work_methods.py` — versioned heuristic schema, plan-shaped keys refused by name, provenance with explicit promotion, `check_revision`, `check_role_methods`. Relation kind vocabulary `USEFUL_RELATION_KINDS` to be reused by Slice 02.
- Shared helper `_checks.recode` (coded errors around shared checks).
- Docs: new `docs/subagent-roles.md`, `docs/work-methods.md`, `docs/legacy/subagent-role-aliases.md`; updated `docs/skills-and-loadouts.md`, `docs/ARCHITECTURE.md`. No schema change, JARVIS not started, no frontend change.
- Pre-existing failures seen (not this Slice): `test_brain_capability_parity::test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt`, `test_brain_delegation::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`, `tests/integration/test_settings_redesign_migration.py::test_assembled_primary_navigation_has_six_tabs_and_no_legacy_navigation` (JS `SyntaxError` in the assembled settings script; Python-only Slice).


## 2026-10-20 — Slice 01 fix pass after independent QA (PASS_WITH_NOTES)

- N1 fixed: a second `[éphémère]` right after the head (even glued or at the end, `[éphémère] [éphémère]`, `[éphémère] [éphémère]x`) is a duplicate: no declaration, text intact.
- N2 kept on the safe side and pinned: `[éphémère] [code] [éphémère] x` (was ephemeral, description `[code] [éphémère] x`) is now ordinary; `docs/subagent-roles.md` §2 lists the intended differences.
- N3 fixed: the flag needs a non-empty label after every head marker (`[ CODE ] [éphémère] `, `[éphémère] [code]` declare nothing).
- N4 fixed: disabled roles (`qa`, `research-lead`) are no longer in `ANNOUNCED_ROLES`, so `[code] [qa] …` reads exactly as before (marker not consumed, kept in the label, prompt role and loadout not hidden). `read_loadout_role` now lives in `agent_markers` and uses the contract's `loadout_role` for an active role whose marker is not itself a loadout role.
- N5: docs no longer promise a reachable visible `unknown` degradation from the grammar (an unknown word is not a role and yields `undeclared`); **Slices 03 and 05 decide** whether an unknown marker must travel to Core and degrade visibly.
- N6: docs state that `coder.tools` gains `Agent` (value change, display only). N7: snapshot size comment fixed.
- Equivalence: `tests/unit/test_agent_markers_equivalence.py` keeps a frozen oracle of the old readers; QA corpus (`scratchpad/qa01/probe.py` + `cmp.py`, 157 927 cases) re-run: zero differences on cases without the exact `[éphémère]` token (disabled roles included); remaining differences are only the intended ones (token transparent in description and prompt, accepted beyond the first place, lost on duplicate or empty label).
- For Slices 03/05 (not coded): **N8** several instances may carry `mission_owner=True` for the same mission (successive owners after handoff); only `Mission.owner_instance_id` names the current owner. `AgentDeclaration` still lacks `session_id`, `subagent_type`, `run_in_background`, a timestamp, announced `mission_id` / parent mission, a contract version, and the journal event `agent.declared` carrying canonical `role_id` and `role_status`.
