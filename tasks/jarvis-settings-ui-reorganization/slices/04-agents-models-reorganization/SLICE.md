# Slice 04 - Agents and models reorganization

## Goal

Merge the user-facing parts of `Agent / CLI` and the newly landed `Sous-agents` surface into one coherent `Agents & modeles` category.

## Context

The current Agent page mixes everyday model/behavior choices with command paths, permission modes and routing internals. The new Sub-agents page adds a rich role registry, instructions and Work Method tooling as another top-level destination.

## Canonical Concepts

- `docs/settings/INDEX.md`
- `docs/subagent-roles.md` if still canonical on current main
- routing/model catalog contracts
- `docs/07-target-settings-map.md`

## Scope

### In Scope

- Main agent/CLI identity and primary model selection.
- Response verbosity and politeness/formality.
- User-facing sub-agent mode.
- Sub-agent role roster, role identity, mission/relevance/capabilities summary.
- Sub-agent model/profile availability and ordinary role configuration.
- Concise active-instance context where useful.
- Route command/path/permission/re-probe and advanced routing candidate ordering to Advanced.
- Route Work Method candidate promotion to Advanced unless current product docs explicitly classify it as ordinary role configuration.

### Out of Scope

- Do not change routing selection semantics.
- Do not invent fan-out, timeout, cost/quality bias, or model capabilities not supported by runtime.
- Do not rewrite the sub-agent role registry.

## Dependencies

- `02-settings-shell-visual-redesign`

## Implementation Steps

1. Freshness-check Agent/CLI, routing, model-catalog and sub-agent-role contracts.
2. Define user-facing groups: Main agent, Behavior, Sub-agents.
3. Reuse existing catalog components rather than create another model table.
4. Move role settings into the category while preserving drafts, optimistic revision conflict handling and controller cleanup.
5. Register technical CLI/routing and Work Method operator sections under Advanced.
6. Remove the top-level Sub-agents destination from normal navigation once all functionality has a destination.
7. Update tests for catalog lifecycle, routing settings, role instruction editing and deep links.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_subagents_settings.js`
- catalog/routing settings UI modules
- related tests/docs

## Architecture Constraints

- One model catalog implementation; no duplicate inventories.
- Role instruction persistence remains canonical prompt override behavior.
- Routing mode continues to select at most the supported runtime behavior; no semantic drift.

## Automated Validation

- Existing Agent/CLI save payloads still validate.
- Sub-agent role edits/reset conflict behavior remains intact.
- Model catalog controllers are destroyed correctly.
- No top-level Sub-agents tab after migration.

## Acceptance Criteria

- User-facing agent, model and role decisions are discoverable in one category.
- CLI installation/runtime internals are not mixed into the default view.

## Documentation Updates

Update Agent/CLI and sub-agent role docs with the new Settings destinations.

## Handoff Notes

This Slice may need `agent-trace-analysis` only if it changes model/routing/agent runtime behavior; pure relocation should not.
