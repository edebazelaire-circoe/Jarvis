# Slice 01 - Architecture graph runtime contract

## Goal

Create the canonical runtime-owned graph model and mutation service that the Architecture UI can render and edit without becoming a second source of truth.

## Context

Today Jarvis has real Core/Voice/Tool ownership concepts but no single generic editable topology contract. The new UI requires nodes, typed ports, typed connections, mutability and validated writes.

## Canonical Concepts

- `docs/ARCHITECTURE.md`
- Tool Brain ownership contracts
- `docs/02-architecture.md` in this handoff

## Scope

### In Scope

- Generic brain/endpoint node model.
- Port compatibility model.
- Directional typed connection model.
- Required/locked vs toggleable vs creatable/removable mutability.
- Authoritative graph snapshot with revision.
- Runtime mutation service with validation/rollback or atomic commit.
- Separate UI-layout position persistence contract.
- Read/write handler module that can be mounted later by Slice 07.
- Adapter(s) that project current Voice/Core/Tool/audio runtime into the graph.

### Out of Scope

- No frontend.
- No speculative future brain instances in the default snapshot.
- No shared `control_center.py` route registration; Slice 07 owns that hot file.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Slice 02: brain config registry/capability descriptors may enrich node metadata.
  - need: per-brain config capabilities/activation mutability.
  - fallback: expose minimal node metadata and stable brain id.
  - integration_required_before: Slice 07 live wiring.
  - mismatch_policy: adapt graph projection to the single brain registry; do not fork ids.

### Can Start With

`docs/02-architecture.md`, current runtime ownership code and direct adapters for current brains/endpoints.

### Produces

- canonical graph domain types;
- runtime graph snapshot service;
- topology mutation service;
- unmounted HTTP/controller handler contract;
- stable fixtures for frontend integration.

### Integration Checkpoint

Slice 07 route registration and UI live adapter reconciliation.

## Implementation Steps

1. Audit real current call paths and mutability constraints.
2. Define node/port/connection/revision contracts.
3. Project current runtime into a graph snapshot.
4. Implement legal enable/disable/create/remove operations.
5. Reject locked/incompatible edits with stable error codes/reasons.
6. Ensure mutations alter runtime binding or fail atomically.
7. Keep layout persistence orthogonal to topology.
8. Publish fixtures/schema for UI Slices.

## Files Likely Touched

Prefer new domain/runtime modules for topology and adapters; related focused docs. Avoid `control_center.py` until Slice 07.

## Architecture Constraints

No UI-only architecture state. No browser-invented connections. No node-position-to-runtime coupling.

## Automated Validation

Use static/import checks and a narrow service smoke scenario proving one allowed mutation and one locked rejection. Agent/runtime trace evidence is required when a real call path is changed. **Do not launch the full unit test suite at this Slice boundary.**

## Acceptance Criteria

- Snapshot describes the actual baseline topology.
- Every edge has direction, purpose, state and mutability.
- Locked writes fail safely.
- Supported editable writes alter actual runtime behavior/state.
- Layout state is independent.
- UI can consume stable fixtures without importing runtime internals.

## Documentation Updates

Add/update canonical architecture topology contract documentation.

## Handoff Notes

Coordinate stable brain ids with Slice 02 through documented interfaces rather than direct concurrent edits.
