# Slice 07 — Presentation manifestation policy

## Goal

Decide when Presentation should say nothing, speak, request a visual manifestation, or raise discreet attention.

## Context

The central UX rule is conservative manifestation: ambient awareness should not turn Jarvis into a running commentator.

## Canonical Concepts

Addressed command, knowledge question, visual command, attention candidate, speech policy, semantic display intent.

## Scope

### In Scope

- Classify Presentation outcomes into `none`, visual/display intent, spoken answer, spoken+visual, or attention.
- Make visual/navigation commands silent by default unless speech is needed for error/clarification/safety.
- Allow concise speech for genuine questions where useful.
- Suppress ambient output by default.
- Gate contradiction attention by relevance/confidence/freshness.
- Produce a structured semantic result that downstream speech/Tool Brain paths can consume.

### Out of Scope

- Low-level UI-tool choice.
- Window geometry or concrete prefab rendering.
- User-specific interruption preference learning.

## Dependencies

- `06-background-intelligence-arbitration`
- `05-presentation-working-set`

## Implementation Steps

1. Define policy inputs/outputs against current runtime contracts.
2. Implement deterministic rules before model-driven nuance where possible.
3. Integrate with explicit-turn answer path and background results.
4. Ensure `none` is a first-class successful outcome.
5. Add scenario tests for visual command, knowledge question, ambient-only and contradiction cases.

## Files Likely Touched

Presentation policy module, Brain/context integration, speech-intent glue, tests, docs.

## Architecture Constraints

Policy emits semantic intent; Tool Brain owns concrete UI execution. Ambient context alone does not authorize actions.

## Automated Validation

Deterministic policy matrix tests, trace assertions for decision reason, regression tests for SIMPLE mode.

## Acceptance Criteria

Representative presentation interactions produce the intended silence/speech/display/attention behavior without filler output.

## Documentation Updates

Document the manifestation matrix and escalation rules.

## Handoff Notes

Coding/runtime Slice: load `/caveman` and `/coding-guideline`; add `agent-trace-analysis`.
