# Slice 10 — Roles & Work Methods Settings UI

## Goal

Expose the canonical Role Registry and Work Methods in a polished, readable Settings surface so agent identity/capabilities are inspectable.

## Dependencies

00-project-manager-readiness, 04-role-registry-loadouts-methods

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Role list/card identity.
- Role detail with mission, prompt/instruction source, skills/loadout, tools/capabilities, Mission Owner/spawn permissions and Work Methods.
- Degraded/unknown role state.
- Responsive readable information architecture.
- Edit controls only where a canonical safe write API exists and product scope is clear; otherwise read-only.

## Scope — out

- A raw JSON/prompt dump as primary UX.
- Inventing configuration writes in the frontend.
- Editing arbitrary hidden system prompts.

## Implementation steps

1. Audit current Settings architecture and shell.
2. Run `/impeccable` UI planning.
3. Use Slice 04 read API as the only role/config data source.
4. Design role cards with same visual identity tokens as graph.
5. Create structured detail sections; long prompt/instruction text behind deliberate disclosure, not giant wall.
6. If no safe settings owner exists for a field, label it read-only rather than fake-editing.
7. Run browser/accessibility/responsive + Human Validation.

## Files likely touched

- Control Center Settings modules
- settings relay/view only if needed
- browser tests
- settings docs / OPERATIONS

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

caveman; coding-guideline; impeccable

## Independent QA

Required: code-review; qa-verification; runtime-validation.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Frontend routing

This is frontend work. Prefer Claude where the workspace supports agent routing and run `/impeccable` before implementation/review. Preserve the Control Center shell/stacking/accessibility contracts.

## Human Validation

- `HV-ORG-10-01` — Open Settings > agent roles and confirm the role catalogue is visually structured, readable and consistent with graph identity rather than a raw wall of prompt text.
- `HV-ORG-10-02` — Inspect a role and verify mission, skills/loadout, capabilities and Work Methods are understandable; unavailable/edit-disabled fields are honestly read-only.

See `human-validation.json`.

## Acceptance criteria

- [ ] Role catalogue is pleasant and easy to scan.
- [ ] Role identity matches task graph.
- [ ] Capabilities/loadout/methods are inspectable without raw text overload.
- [ ] UI does not invent editable state.
- [ ] Degraded states are explicit.
- [ ] Human visual checks pass.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- **This Slice is the Settings tab "Sous-agents" left open by `jarvis-subagent-roles-interview`** (absorbed; plan `tasks/jarvis-subagent-roles-interview/PLAN.md` §6). One roles tab only. Add it to `TABS` (`control_center.html`), module `jarvis/runtime/control_center_subagents_settings.js` following `control_center_memory_settings.js`, active instances (from `/api/agent/tasks`, role already exposed) in a separate area.
- A safe canonical write path exists for role instructions (`POST /api/prompts/subagent_role.<id>`, revisions, reset): instruction editing is **in scope** (user decision 3 of that task: instructions editable and persisted). Every other field stays read-only unless Slice 04 adds an owner.
- Documentation: `docs/settings/INDEX.md`, `docs/subagent-roles.md`.
