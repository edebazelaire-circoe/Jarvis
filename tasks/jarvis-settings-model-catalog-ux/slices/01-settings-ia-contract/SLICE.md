# Slice 01 — Define the new Settings information architecture and option contracts

## Goal

Replace the “Aiguillage”-centric IA with a technical-first Agent/CLI configuration and categorized voice settings contract before touching UI markup.

## Context

The user has locked the product direction but several suggested technical/personality knobs must be validated against real runtime capabilities.

## Canonical Concepts

- Agent/CLI technical section
- Agent/CLI personality section
- Auto/Dupliqué binding
- Sous-agents/Models catalog surface
- voice top-subtab taxonomy
- supported option metadata (type/default/range/help/advanced)

## Scope

### In Scope

- Inventory every current setting and assign it a destination/category.
- Define required options and mark speculative suggestions as optional until runtime-backed.
- Define migration/alias handling for “Aiguillage” routes/labels.
- Define voice category mapping using final supported arbitration settings.

### Out of Scope

- Backend implementation.
- Visual polish beyond IA contract.

## Dependencies

00

## Implementation Steps

1. Inventory current Control Center settings and routing controls.
2. Lock technical-first grouping; include Auto/Dupliqué, verbosity and politeness/formality explicitly.
3. For suggested controls (parallelism, timeout, cost/latency/quality bias, fallback, confirmations/proactivity), expose only those with real runtime semantics or create explicit follow-up contracts.
4. Define voice sub-tabs and map each existing voice setting to exactly one category.
5. Define deprecation/migration behavior for saved settings and old navigation.

## Files Likely Touched

- `docs/*settings*`
- `jarvis/domain/*settings* or existing config schema`
- `tests/unit/*settings*`

## Architecture Constraints

- A setting without runtime semantics must not be a placebo UI control.
- “Aiguillage” is not a user-facing category after migration.

## Automated Validation

- Schema/category validation tests.
- Migration fixture for existing saved routing/settings.

## Acceptance Criteria

- Every existing setting has a documented destination or deprecation reason.
- Required user controls are represented.
- No duplicate/contradictory setting names remain.

## Documentation Updates

Create canonical Settings IA/options documentation.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
