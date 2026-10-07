# Slice 21 - Agent, Voice and UI Operations for Presentation Studio

## Goal
Expose the complete Presentation Studio through stable semantic operations so natural voice requests and GUI actions manipulate the same model.

## Context
Jarvis remains the center of the interaction. The user should be able to say "show all variants", "open 37", "make a variant", "compare these four", "make the purple colder", "rehearse from the product scene", etc.

## Canonical Concepts
Stable runtime IDs, constrained choices, semantic operation, Tool Brain seam, voice/UI parity.

## Scope
### In Scope
- Agent/tool operations for artifact open/present/edit.
- Fullscreen enter/exit.
- Scene/score navigation.
- Semantic edits.
- Variant/tree/compare/mix operations.
- Scene-local variant operations.
- Rehearsal and presenter-role commands.
- Promotion to template/prefab.
- Dynamic valid choices/current-state introspection.
- Integrate canonical Tool Brain intent path when available.

### Out of Scope
- New generic natural-language router architecture.

## Dependencies
- `05-semantic-edit-api`
- `12-playback-runtime`
- `16-presentation-variants-domain`
- `17-scene-local-variants`
- `19-variant-compare-mix`
- `20-template-prefab-promotion`

## Implementation Steps
1. Reuse the repository's semantic MCP/tool catalog conventions.
2. Prefer stable IDs/enums supplied from current state.
3. Keep destructive branch deletion behind canonical confirmation policy.
4. Ensure visual commands are silent by default under PRESENTATION policy unless speech adds value.
5. Add targeted inspect/read operations instead of bloating every tool payload.
6. Correlate operations with canonical observability/timeline events.

## Files Likely Touched
Agent tool/MCP schema, Presentation policy adapters, Tool Brain integration, tests.

## Architecture Constraints
Do not make the model invent scene/variant IDs. Do not create a second UI tool scheduler.

## Automated Validation
Tool schema tests, dynamic-choice tests, natural-language/trace scenarios, destructive confirmation, voice/GUI parity, Presentation silence-policy regression.

## Acceptance Criteria
All major Presentation Studio operations are accessible to Jarvis with stable semantic contracts and without bypassing existing UI/authority policies.

## Documentation Updates
Agent/MCP operation reference and examples.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; agent runtime changes require real trace evidence.
