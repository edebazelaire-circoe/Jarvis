# Slice 02 — UI Tool Choice Contract

## Goal

Make every Tool Brain-facing UI operation safely selectable from current runtime state, with stable IDs, rich parameter metadata and dynamic valid choices.

## Context

The user explicitly wants the model to choose from valid runtime values rather than fabricate IDs. Existing MCP semantic/catalog work should be extended, not bypassed.

## Canonical Concepts

Tool descriptor, dynamic choice provider, stable runtime ID, side-effect class, precondition, Tool Brain capability manifest.

## Scope

### In Scope

- Tool Brain projection of the canonical UI tool catalog.
- Parameter metadata: type, required/default, description, constraints.
- Dynamic choice-provider contract for runtime-known values.
- Human-readable choice labels and compact metadata.
- Stable ID/revision references for selectable objects.
- Explicit side-effect classification (`read`, `reversible_ui`, `destructive_ui`, etc.) using repository conventions.
- Precondition metadata and mutation-time validation hooks.
- Tests proving advertised choices and executor validation agree.

### Out of Scope

- Tool Brain model decisions.
- Perception snapshot beyond data needed to provide choices.
- Browser research/content-fetch tools.

## Dependencies

- `01-runtime-contract-audit`

## Implementation Steps

1. Extend the canonical MCP/tool metadata schema instead of creating a Tool Brain-only parallel registry.
2. Add choice-provider interfaces backed by authoritative state.
3. Add stable `value` + human `label` + relevant typed metadata for each choice.
4. Attach snapshot/revision context when needed for optimistic validation.
5. Cover scene objects, Boards and other already-supported UI IDs first.
6. Define behavior for truly free-form parameters and minimize their use.
7. Add catalog parity/conformance tests.

## Files Likely Touched

Canonical MCP catalog/meta/schema code and UI tool facades identified in Slice 01, plus tests/docs.

## Architecture Constraints

The catalog describes capabilities; runtime services remain mutation owners. Dynamic choices never grant authority by themselves.

## Automated Validation

- Every constrained parameter exposes only legal current values.
- Removed objects disappear from choices.
- Fabricated IDs are rejected.
- Choice labels are non-authoritative; IDs drive execution.
- Tool catalog parity tests prevent schema/description drift.

## Acceptance Criteria

- Tool Brain can construct valid UI calls without inventing runtime identifiers.
- Tool descriptions are concise enough for model context but sufficient for correct selection.
- The same validator guards calls from Tool Brain and other callers where appropriate.

## Documentation Updates

Promote dynamic choice-provider and Tool Brain capability-manifest contracts to Level 3.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. This Slice changes tool contracts, so `agent-trace-analysis` is mandatory.
