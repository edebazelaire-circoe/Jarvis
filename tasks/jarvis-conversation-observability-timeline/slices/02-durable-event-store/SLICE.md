# Slice 02 — Add durable append/replay storage for conversation events

## Goal

Implement a durable append-only store and query interface for the canonical event envelope, reusing existing Core persistence when it satisfies the contract.

## Context

The record must remain usable after crashes and support efficient session/turn/time queries. The physical backend is chosen only after Slice 00 audits existing Core storage.

## Canonical Concepts

- append-only persistence
- idempotent append
- session/time queries
- crash recovery
- retention/migration contract

## Scope

### In Scope

- Implement store port + adapter.
- Guarantee append durability and duplicate-event behavior.
- Provide pagination/range query primitives needed by UI/export.
- Define migration/version handling.

### Out of Scope

- Source instrumentation.
- Timeline UI.

## Dependencies

01

## Implementation Steps

1. Select/reuse current persistence substrate after audit.
2. Implement append and query APIs around the canonical envelope.
3. Add indexes/lookup paths for conversation/session/turn/trace/task/time.
4. Handle partial/corrupt tail or transaction interruption safely.
5. Add retention/archive policy hooks without silently deleting active history.

## Files Likely Touched

- `jarvis/ports/*`
- `jarvis/runtime/*conversation* or existing Core store adapter`
- `tests/unit/*store*`
- `tests/integration/*conversation*`

## Architecture Constraints

- A crash may duplicate an append attempt but must not silently lose acknowledged events.
- Storage format is an implementation detail; consumers depend on the port/schema.

## Automated Validation

- Idempotency tests.
- Crash/partial-write recovery.
- Pagination and ordering tests.
- Schema migration fixture.

## Acceptance Criteria

- Events survive process restart.
- Duplicate append is deterministic.
- Queries return stable chronological ordering and preserve overlaps/durations.

## Documentation Updates

Document storage, recovery, retention, and migration guarantees.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
