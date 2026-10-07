# Slice 03 — Tool Brain Perception and World Model

## Goal

Provide Tool Brain with a compact, relevant, stable-ID representation of what the user currently sees, plus targeted inspection methods for deeper information.

## Context

Tool Brain should not ingest the full application/database state on every wake. It needs a high-signal default snapshot and explicit read paths to zoom in on one object.

## Canonical Concepts

Perception snapshot, world object, active Board, scene object, task/agent/process projection, browser/display surface, targeted inspection.

## Scope

### In Scope

- Snapshot schema and builder over canonical current state.
- Active Board, visible/focused scene objects, stars/points/capsules/windows where those concepts exist live.
- Condensed task/agent/process state relevant to visible UI.
- Browser/window/display-surface state when available.
- Stable IDs, labels, type/status, ownership and compact summaries.
- Queue summary placeholder/interface for later Slice integration.
- `get_information_on(id)`-style targeted inspection through canonical naming.
- Related-object/action inspection where it materially improves decisions.
- Size/relevance bounds and deterministic serialization for replay/evaluation.

### Out of Scope

- New mutating UI capabilities.
- Arbitrary repository/filesystem/database browsing by Tool Brain.

## Dependencies

- `01-runtime-contract-audit`
- `02-ui-tool-choice-contract`

## Implementation Steps

1. Define a versioned snapshot contract.
2. Build adapters over canonical scene/Board/runtime/browser state.
3. Add compact summary fields and omit bulky metadata by default.
4. Add targeted inspection endpoints/tools for one stable ID.
5. Ensure inspection arguments use current valid ID choices.
6. Add fixtures for empty, busy, multi-window, multi-agent and multi-Board states.
7. Add deterministic snapshot serialization for replay tests.

## Files Likely Touched

New Tool Brain perception module plus canonical state adapters and tests discovered by Slice 01.

## Architecture Constraints

Perception is a projection, not persistence. It never becomes a second source of truth for Board, scene, task or browser state.

## Automated Validation

- Snapshot reflects canonical state revisions.
- Targeted inspection returns richer data for the same ID.
- Snapshot remains bounded under large scene/task counts.
- IDs are stable while objects live.
- Unknown/deleted IDs fail cleanly.

## Acceptance Criteria

- A decision model can understand what the user sees without full-state dumping.
- Every object it may select is identifiable and inspectable.
- Replay fixtures can reconstruct the exact decision input.

## Documentation Updates

Document snapshot schema, relevance rules and inspection contract at Level 3.

## Handoff Notes

Use `/caveman` and `/coding-guideline`.
