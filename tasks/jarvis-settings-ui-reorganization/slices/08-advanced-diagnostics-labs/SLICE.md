# Slice 08 - Advanced diagnostics and labs

> Authored by agent 0 during Slice 00: the Drive publication of this handoff contained an empty folder for this Slice. Content is derived strictly from `docs/02`, `docs/03`, `docs/04`, `docs/06` and `docs/07`; no new product decision is introduced.

## Goal

Build `Avance & diagnostic` as a structured category with five explicit groups, receiving every technical/operator surface the previous Slices registered.

## Context

Slices 03-06 register advanced sections (Voice architecture/VAD/verifier, wake detector state, CLI/routing, Work Method promotion, memory-leg diagnostics, Bare Hands benchmark/recording). `Prompts` (`tabPrompts()`) and the scene test gate (`control_center_scene_settings.js`, `experimental` tab) still need a home.

## Canonical Concepts

- `docs/02-architecture.md` section 4
- `docs/07-target-settings-map.md` section 6

## Scope

### In Scope

- Groups: Architecture & compatibility, Prompts & instructions, Runtime & CLI, Diagnostics, Labs & test tools.
- Move the prompt workbench (save/reset per layer, effective preview) to Prompts & instructions.
- Move scene test gate + brain restart to Labs & test tools; remove the scene module's `experimental` tab dependency.
- Harmonize the sections registered by earlier Slices; technical monospace styling allowed here only.
- Ensure no section is orphaned and none duplicates an ordinary editable control.

### Out of Scope

- No change to prompt override persistence, scene gate semantics, routing semantics or diagnostics data sources.

## Dependencies

- `03-voice-audio-reorganization`, `04-agents-models-reorganization`, `05-memory-knowledge-reorganization`, `06-interface-interactions-reorganization`, `07-connections-reorganization`

## Implementation Steps

1. Inventory every section registered with category `advanced_diagnostics`.
2. Add the five groups and order sections inside them.
3. Relocate Prompts and scene test gate.
4. Add an advanced-category notice explaining these are operator tools.
5. Update tests.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_scene_settings.js`
- prompt workbench, scene settings and routing tests

## Architecture Constraints

- Advanced is structured, not a junk drawer: every section belongs to one of the five groups.

## Automated Validation

- Every advanced section belongs to a declared group.
- Prompt override save/reset unchanged.
- Scene gate toggle and brain restart unchanged.
- Wake detector, Voice and memory diagnostics reachable.

## Acceptance Criteria

- No top-level `Prompts` or `Expérimental` tab remains.
- All technical tooling is reachable under `Avance & diagnostic`.

## Documentation Updates

`docs/settings/INDEX.md`: Advanced groups and what belongs in each.

## Handoff Notes

If prompts or role instructions change runtime behavior, add `agent-trace-analysis`; pure relocation does not.
