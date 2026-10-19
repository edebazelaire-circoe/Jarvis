# Slice 04 — Role Registry, loadouts, skills & Work Method catalogue

## Goal

Create one inspectable canonical Role Registry and integrate it with current loadout/routing semantics and reusable heuristic Work Methods.

## Dependencies

00-project-manager-readiness, 01-agent-role-mission-contracts, 03-work-state-mission-history

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Role definitions for Interviewer, Research Lead, Web Research, Document Research, Developer, Conceptualizer, QA and other minimal built-in roles validated in audit.
- Mapping from role to prompt layer, loadout role/profile compatibility, skills/tools/capabilities and visual identity tokens.
- Compatibility mapping from current `coder/reviewer/research`.
- Work Method catalogue + role applicability/default suggestions.
- Read API/domain view for Settings/agents.

## Scope — out

- Frontend Settings UI.
- Silent automatic promotion of methods.
- Scattered hard-coded frontend role colors.

## Implementation steps

1. Audit `LoadoutResolver`, prompt catalog/routing hook and existing settings registry patterns.
2. Implement canonical registry and pure inspection view.
3. Wire role resolution into agent brief/loadout creation using explicit role IDs.
4. Add unknown/degraded role behavior that never guesses from free text.
5. Add Work Method registry using heuristic schema from Slice 01.
6. Expose a read-only Core/Control Center inspection path required by Slice 10; add write path only if current settings architecture has a safe owner and product scope justifies it.
7. Test role/loadout/skill parity and compatibility aliases.

## Files likely touched

- `jarvis/core/loadout_resolver.py` / `jarvis/runtime/routing_hook.py` as needed
- new role registry domain/runtime module
- prompt catalog/instruction composition layer
- Core/Control Center read route/view for roles
- tests/unit/*role_registry* / loadout parity

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

- [ ] One registry is the source of role identity/configuration.
- [ ] Existing role aliases continue to work deterministically.
- [ ] Role visuals/capabilities are data, not duplicated frontend switches.
- [ ] Unknown role degrades visibly.
- [ ] Work Methods are heuristic definitions only.
- [ ] Settings can read exact registry state through canonical API.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- **The canonical Role Registry is `jarvis/domain/subagent_roles.py` extended** (see Slice 01), not a new module. Existing pieces to reuse: role instructions as editable prompts `subagent_role.<id>` (`jarvis/runtime/prompt_catalog.py`), hook snapshot `runtime/subagent-roles.json` (`jarvis/runtime/subagent_roles_snapshot.py`), journal `agent.role_applied`, read route `GET /api/subagent-roles` (`jarvis/runtime/control_center.py`, `_subagent_roles_payload`; bump its `schema_version` if fields change).
- Loadout: `LOADOUT_ROLES = (coder, reviewer, research)` and `ROLE_BASE_PROFILE`; registry roles without a loadout keep their profile's loadout (`routing_hook.read_loadout_role`). Extend `LOADOUT_ROLES` additively only for roles that truly need their own loadout; existing `memory.loadouts` rules must still validate.
- Write path: a safe canonical write already exists for instructions (`POST /api/prompts/subagent_role.<id>`, optimistic revisions). Do not add another write path for instructions.
- Documentation: complete `docs/subagent-roles.md`, link from `docs/skills-and-loadouts.md`.
