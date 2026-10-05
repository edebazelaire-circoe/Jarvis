# Slice 05 — Fresh tail and bounded Presentation working set

## Goal

Maintain both immediate conversational freshness and a compact enriched Presentation context without turning either into long-term memory.

## Context

Deictic commands require the last few seconds of speech, while useful proactive support benefits from slower semantic enrichment. One representation cannot safely serve both needs.

## Canonical Concepts

Fresh transcript tail, working set, provenance, prepared resource reference, Session scope, Context compatibility.

## Scope

### In Scope

- Bounded recent transcript tail with timestamps/segment IDs.
- Bounded enriched working-set items for topics, entities, claims, source refs, prepared resources and unresolved items.
- Freshness/provenance metadata and deterministic eviction rules.
- Read APIs/context assembly for explicit addressed turns and background workers.
- Resource handles that can later point to prepared research/visual output.

### Out of Scope

- Long-term memory.
- Unlimited transcript accumulation.
- Persisting raw ambient audio.

## Dependencies

- `04-ambient-presentation-lane`
- `01-contract-reconciliation`

## Implementation Steps

1. Reconcile any existing `presentation-working-set` implementation.
2. Implement/repair fresh-tail store and bounded semantic set.
3. Add enrichment/update pipeline with provenance.
4. Define precedence: newer fresh evidence beats stale enriched summaries for immediate reference resolution.
5. Add deterministic eviction/freshness tests.

## Files Likely Touched

Presentation working-set runtime/domain model, context assembly, tests, docs.

## Architecture Constraints

Session-scoped/disposable. Do not duplicate canonical artifact or memory registries; store references.

## Automated Validation

Tests for boundedness, eviction, provenance, deictic resolution, stale-vs-fresh precedence and restart behavior according to canonical Session rules.

## Acceptance Criteria

An explicit turn can resolve immediate references from the fresh tail while still benefiting from compact prepared semantic context.

## Documentation Updates

Make working-set structure, freshness and lifecycle contract explicit.

## Handoff Notes

Coding Slice: load `/caveman` and `/coding-guideline`.
