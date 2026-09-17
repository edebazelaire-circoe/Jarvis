# Slice 01 — Define the canonical conversation event contract

## Goal

Create a versioned, storage-independent event envelope that can deterministically reconstruct user-visible conversation and execution timing without model rewriting.

## Context

Current `RuntimeJournal` entries use `{ts, kind, level, message, data}` and voice/Core code already has multiple IDs. This Slice defines the canonical functional record and adapters from existing concepts.

## Canonical Concepts

- conversation_id/session_id/turn_id/event_id/parent_event_id
- actor/channel/event_type
- started_at/ended_at
- trace_id/task_id/generation_id
- schema versioning and redaction

## Scope

### In Scope

- Define required/optional/forbidden fields and actor/event vocabularies.
- Define ordering/idempotency semantics and cross-process timestamp rules.
- Define explicit visibility/redaction rules so hidden chain-of-thought never enters the record.
- Provide serializer/validator and fixtures.

### Out of Scope

- Persistence engine.
- Frontend rendering.

## Dependencies

00

## Implementation Steps

1. Audit existing envelope/ID types before introducing new types.
2. Specify actor values for user, mouth/reflex, brain, subagent, tool/system as appropriate.
3. Define duration events and instantaneous events.
4. Define trace-correlation and content visibility semantics.
5. Add schema fixtures and conformance validation.

## Files Likely Touched

- `jarvis/domain/* (prefer existing event-contract location)`
- `jarvis/protocol/*`
- `tests/unit/*event*`

## Architecture Constraints

- Schema must be storage-independent.
- Event IDs must be stable and idempotent; do not use list position as identity.
- No hidden chain-of-thought or raw audio.

## Automated Validation

- Schema validation tests.
- Round-trip serialization fixtures.
- Redaction/forbidden-field tests.

## Acceptance Criteria

- A fresh consumer can reconstruct chronological visible conversation from valid events.
- Invalid/unsafe payloads fail validation.
- Correlation fields are sufficient to join diagnostic traces and task spans.

## Documentation Updates

Create/update the canonical contract documentation and reference it from existing realtime/Brain event docs.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
