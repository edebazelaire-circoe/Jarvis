# Slice 01 — Agent Role, Mission Owner, Ephemeral & Work Method contracts

## Goal

Create the pure domain contracts for immutable roles, missions/sub-missions, Mission Owner responsibility, ephemeral classification, and heuristic Work Methods.

## Dependencies

00-project-manager-readiness

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Canonical role IDs and definitions.
- Role immutability on agent instances.
- Mission and parent/sub-mission identity.
- Mission Owner responsibility distinct from role, including recursive ownership.
- Ephemeral classification semantics.
- Work Method schema as heuristics/quality expectations, explicitly not a DAG/workflow.
- Compatibility aliases for existing `coder`, `reviewer`, `research` semantics without guessing from arbitrary labels.

## Scope — out

- Runtime spawning/delegation.
- Persistence implementation.
- Frontend.
- A fixed execution plan schema.

## Implementation steps

1. Read current work-state/loadout/routing domain contracts.
2. Add strict pure-domain types/validators and stable wire forms where appropriate.
3. Define immutable fields and conflict behavior.
4. Define role visual metadata contract centrally (ids/icons/accent token/badge) without frontend-specific CSS.
5. Define Work Method versioning and candidate provenance fields; no ordered step graph.
6. Add exhaustive unit tests for decode, bounds, immutability, compatibility aliases and unknown-role degradation.

## Files likely touched

- `jarvis/domain/...` role/mission/method modules (exact names chosen after audit)
- `jarvis/domain/work_state.py` only if optional normalized fields are proven necessary
- tests/unit/*role* / *mission* / *work_method*
- canonical docs chosen in Slice 00

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

caveman; coding-guideline

## Independent QA

Required: code-review; qa-verification; agent-trace-analysis.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Human Validation

- None for this Slice.

See `human-validation.json`.

## Acceptance criteria

- [ ] Role ID is explicit and immutable.
- [ ] Mission Owner is not encoded as a role.
- [ ] Sub-mission ownership can be represented recursively without cycles.
- [ ] Ephemeral is explicit data, not inferred from duration after the fact.
- [ ] Work Method contains heuristics/quality criteria and no planned DAG/step sequence.
- [ ] Legacy role markers map deterministically or degrade explicitly.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- **Extend, do not recreate.** The role registry already exists on main: `jarvis/domain/subagent_roles.py` (`SubagentRole`, `ROLES`, `role_for`, `with_role_instructions`, `brain_rules`, commit `e05d931d`). The canonical role contract of this Slice is an extension of that module (visual identity tokens, `can_own_mission`, `can_spawn`, allowed/default Work Methods, loadout alias). No second role module.
- **Keep the current ids** `interviewer`, `research`, `web-research`, `coder`, `concept`: they key the user's persisted prompt overrides (`subagent_role.<id>`). Mapping: Developer = `coder`, Document Research = `research`, Web Research = `web-research`, Conceptualizer = `concept`. New additive ids for Research Lead and QA; Finalizer only if this Slice shows it is needed. `reviewer` (loadout role, `memory_settings.LOADOUT_ROLES`) becomes the explicit compatibility alias of QA. User-facing names stay French.
- **Mission** references the existing shared mission dossier `<Board memory>/missions/<topic>-<YYYYMMDD>/mission.md` (`subagent_roles.MISSION_PATH_HINT`) by path; it does not introduce a second prose context.
- **Ephemeral** already exists (`WorkObservation/WorkItem.ephemeral`, `EPHEMERAL_WORK_STATUSES`, `agent_tasks.EPHEMERAL_MARKER`, `parse_ephemeral_description`). Reuse that flag. Product meaning decided by agent 0 (I-004, commit `6f2ca77d`): one flag, silent success kept, brain rule widened to small self-evident corrections. This Slice defines the contract (explicit, immutable once declared, lowered on failure as today) so that an ephemeral task can carry a role (e.g. one ephemeral `coder` for a typo fix); it does **not** edit the brain prompt rule (`claude_local.py:101`) — Slice 07 owns that change.
- **Fix the marker collision** (audit §2.5, I-005): `[éphémère]` must lead the description (`agent_tasks.py:73`, `fullmatch` at `:196`) while the hook reads `[profile] [role]` at the head with ASCII-only patterns (`PROFILE_PATTERN`/`_BRACKET`, `routing_hook.py:67`, `:71`). Consequences to test: `[éphémère] [code] [coder] …` → `[éphémère]` does not match the ASCII pattern, `_markers` returns `(0, None)`, `read_profile`/`read_role` fall back to the `prompt` key (`:90`, `:122`) and otherwise yield `general`/`None`; `[code] [coder] [éphémère] …` → profile/role read, ephemeral flag lost. Define one composed grammar (or structured equivalent) parsed identically by `agent_tasks.py` and `routing_hook.py`; tests cover every order, the accented token against the ASCII patterns, and the `prompt` fallback.
- **Nested spawn is proven** on the installed CLI 2.1.304 (readiness audit §8, N3): a `general-purpose` sub-agent can call `Agent`, and the `PreToolUse` hook sees the nested call with the caller's `agent_id`. `can_spawn` / `can_own_mission` can therefore be real capabilities of the native path; `can_spawn` must also be reflected in the tool set of any custom agent type.
- Files likely touched (corrected): `jarvis/domain/subagent_roles.py`, `jarvis/domain/work_state.py` (only if needed), `jarvis/runtime/agent_tasks.py` + `jarvis/runtime/routing_hook.py` (grammar only), new `jarvis/domain/mission*.py` / `work_method*.py` as needed, `tests/unit/test_subagent_roles.py` and new tests.
- Documentation: create `docs/subagent-roles.md` (already promised by the module docstring, currently missing) and `docs/work-methods.md`.
