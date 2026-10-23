# Slice 07 - Settings integration and legacy migration

## Goal

Converge the parallel runtime/UI branches into the real Settings page, own the shared hot files, migrate legacy navigation/config safely, and reconcile the broader Settings shell task.

## Context

Slices 01-06 intentionally defer shared route/page registration to prevent parallel conflicts. This Slice is the single integration owner before final QA.

## Canonical Concepts

- all task docs
- current Settings registry/IA docs
- `jarvis-settings-ui-reorganization` shell work

## Scope

### In Scope

- Register graph, brain config and role-policy handlers/routes.
- Mount page with exactly Architecture + Sous-agents tabs.
- Wire Architecture canvas <-> brain popup <-> live runtime adapters.
- Wire Sous-agents tab <-> live role-policy service.
- Reconcile with live global Settings shell styling/navigation.
- Remove/supersede old Agents/models normal-page controls.
- Route CLI path/permission/re-probe/diagnostics to Advanced destinations.
- Route personality fields to Personalization/Voice, not this page.
- Preserve legacy settings fields and supported deep-link aliases during migration.
- Mark/update old related task/docs so its Slice 04 cannot contradict this implementation.
- Add targeted runtime traces/smoke checks for topology + delegation + role routing integration.

### Out of Scope

- No full unit/integration/E2E suite; Slice 08 owns that final campaign.
- No new unrelated Settings redesign.

## Dependencies

### Hard `depends_on`

- 01: live topology service required for final graph wiring.
- 02: live brain config service required for popup wiring.
- 03: live role policy required for global sub-agent routing UI.
- 04: Architecture UI required.
- 05: brain popup UI required.
- 06: Sous-agents UI required.

All six are true integration prerequisites; shared hot-file work should not start before their output shapes are available.

### Soft `requires`

- External umbrella Settings shell task:
  - need: current final shell/nav registration convention.
  - fallback: mount through current Settings registry/adapter while preserving page module isolation.
  - integration_required_before: Slice 07 acceptance.
  - mismatch_policy: adapt page registration to shell; do not fork a second shell.

### Can Start With

Only after hard dependencies complete; may inspect shell freshness while waiting.

### Produces

- fully wired Architecture & Agents page;
- migrated navigation/deep links;
- shared route/page registration;
- updated Settings documentation and old task supersession note.

### Integration Checkpoint

This Slice is the integration checkpoint. Slice 08 validates the converged product.

## Implementation Steps

1. Reconcile all published contracts and resolve any soft-requirement mismatches.
2. Register backend handlers in shared controller/router.
3. Mount Architecture + Sous-agents modules in the Settings shell.
4. Wire brain popup context actions and graph focus.
5. Apply legacy navigation/deep-link redirects.
6. Relocate technical and personality controls to their canonical destinations.
7. Verify no duplicated writable controls/sources of truth.
8. Capture narrow runtime traces for a graph mutation, brain delegation and role candidate selection.

## Files Likely Touched

Shared hot files such as `jarvis/runtime/control_center.py`, `jarvis/runtime/control_center.html`, Settings registry/navigation modules, docs, compatibility aliases.

## Architecture Constraints

No duplicate Settings shell, model catalog, role registry, connection store or brain identity registry.

## Automated Validation

Targeted build/import/browser smoke, deep-link smoke and real trace analysis for topology/delegation/routing. **Do not launch the full unit test suite at this Slice boundary.**

## Acceptance Criteria

- Page has exactly two tabs.
- Live graph and live brain popup work together.
- Live role-policy editing works in Sous-agents.
- Old Agents/models concept is no longer the default destination.
- Personality and CLI technical controls are absent from the normal page and remain reachable in canonical destinations.
- Legacy config is preserved/migrated safely.
- No concurrent contradiction remains in the old Settings task documentation.

## Documentation Updates

Update Settings IA, architecture, routing/sub-agent and migration/deep-link docs.

## Handoff Notes

Requires `/caveman`, `/coding-guideline`, `/impeccable`; use Claude Work Agent for frontend implementation/review where supported. This Slice owns shared hot-file convergence.
