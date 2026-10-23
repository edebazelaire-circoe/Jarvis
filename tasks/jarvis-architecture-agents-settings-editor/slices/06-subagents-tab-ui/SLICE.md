# Slice 06 - Sous-agents tab UI

## Goal

Redesign the existing Sous-agents Settings surface into the second tab of Architecture & Agents, preserving the robust role registry/instruction behavior while adding role-oriented candidate routing.

## Context

The approved reference is visually strong but contains only five illustrative roles and placeholder models. Current main has seven canonical roles and a mature Settings module with error/revision behavior that must not be lost.

## Canonical Concepts

- `docs/subagent-roles.md`
- `jarvis/runtime/control_center_subagents_settings.js`
- `docs/06-functional-spec.md` section D
- `references/subagents-ui-reference.png`

## Scope

### In Scope

- New Sous-agents tab composition in the approved neon/glass style.
- All canonical roles from server payload.
- Role identity/mission/relevance/capabilities/tools/skills/loadout/Work Methods/instructions.
- Ordered preferred harness/model candidates per role.
- Fallback/availability/provenance display.
- Optional routing matrix/overview as a projection of the same policy.
- Concise active instance context.
- Preserve loading/error/timeout/unknown outcome/revision conflict/draft preservation/reset behavior.
- Keep Work Method promotion operator tooling out of the normal flow unless fresh canonical docs classify it as ordinary.

### Out of Scope

- Do not hard-code five mockup roles or mockup model names.
- No personality controls.
- No old Auto/Duplique top-level product toggle.
- No shared shell registration until Slice 07.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Slice 03:
  - need: role policy payload, candidate ordering/fallback write contract and migration provenance.
  - fallback: use current `/api/subagent-roles` plus fixture policy adapter.
  - integration_required_before: Slice 07 completion.
  - mismatch_policy: adapt routing subcomponent/transport without rewriting role registry UI.

### Can Start With

Current role Settings module, current role API and reference image.

### Produces

- redesigned Sous-agents UI module;
- role-policy adapter/subcomponent;
- preserved robust instruction editor state machine.

### Integration Checkpoint

Slice 07 live role-policy route and Settings page mount.

## Implementation Steps

1. Inventory current UI behaviors and keep every robust state/error path.
2. Refactor visual composition without rewriting the role registry truth.
3. Add role candidate order/fallback controls behind adapter.
4. Add availability/provenance and optional routing overview.
5. Keep Work Methods/instructions in their canonical ownership.
6. Verify all roles/aliases render from payload.
7. Verify active instance failures do not disable role config.

## Files Likely Touched

`jarvis/runtime/control_center_subagents_settings.js` and dedicated supporting CSS/module files. Avoid `control_center.html` final mount until Slice 07.

## Architecture Constraints

One role registry, one model catalog, one role-policy store. Preserve optimistic revision semantics for instructions.

## Automated Validation

Frontend build/static checks plus targeted fixture/smoke scenarios for conflict/refusal/timeout/partial payload and candidate editing. **Do not launch the unit test suite at this Slice boundary.**

## Acceptance Criteria

- All canonical roles appear from live payload.
- Candidate order/fallback can be edited per role without changing another role.
- Instruction draft/conflict/unknown-outcome behavior is not regressed.
- Placeholder model names/role counts are not hard-coded.
- No Brains tab or personality section appears.

## Documentation Updates

Update `docs/subagent-roles.md` Settings destination/role-policy UI section.

## Handoff Notes

Requires `/caveman`, `/coding-guideline`, `/impeccable`; use Claude Work Agent for frontend implementation/review where supported.
