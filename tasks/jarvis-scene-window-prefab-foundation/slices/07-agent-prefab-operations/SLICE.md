# Slice 07 — Agent-Facing Prefab Operations

## Goal

Expose the prefab system to Jarvis through controlled, inspectable operations suitable for the project's MCP/tool architecture.

## Context

Jarvis must be able to choose, inspect, instantiate, fork, create, and save prefabs instead of relying on hardcoded UI knowledge.

## Canonical Concepts

Prefab catalog operation, definition mutation, instance operation, explicit base edit.

## Scope

### In Scope

Operations equivalent to:

- list/search prefabs
- inspect prefab schema/code/provenance as permitted
- instantiate prefab in scene
- update prefab instance inputs/data
- fork/clone prefab definition
- create new prefab definition
- validate/preview candidate definition
- save/promote candidate into shared library
- explicitly modify a base prefab only through the protected path

Exact names must match current Jarvis tool/MCP conventions.

### Out of Scope

- Giving prefab JavaScript direct tool access.
- Silent base prefab edits.

## Dependencies

- `06-structured-interactive-prefabs`

## Implementation Steps

1. Define read vs instance-mutation vs definition-mutation surfaces.
2. Reuse existing Jarvis tool authorization/gating conventions.
3. Add explicit base-edit intent/gate.
4. Validate all generated definitions before library publication.
5. Emit trace/audit evidence for definition changes.
6. Make catalog descriptions useful for model selection without shipping full source unless requested/needed.

## Files Likely Touched

Agent tool/MCP contracts, prefab service/catalog, authorization/gate code, trace/logging, tests.

## Architecture Constraints

Backend/runtime remains the authority for validation and mutation. Frontend descriptors must not become a second capability catalog.

## Automated Validation

- Tool schema/conformance tests.
- Read-only operations do not mutate.
- Invalid definitions rejected.
- Base edit denied without explicit gate.
- Trace evidence records actor/action/target/result.

## Acceptance Criteria

- Jarvis can complete the reuse-first workflow end to end through supported operations.
- Definition changes are gated, validated, and traceable.
- No prefab gains arbitrary Jarvis authority.

## Documentation Updates

Document model-visible operation catalog and base-edit rules.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. This Slice also requires `agent-trace-analysis` QA with real traces.
