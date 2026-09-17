# Slice 04 — Build the reusable sortable/filterable catalog table

## Goal

Create one reusable catalog/comparison component for sub-agent/text and voice model inventories.

## Context

The user explicitly wants to sort from expensive to cheap, filter by tags/capabilities, compare models, and see short usage guidance.

## Canonical Concepts

- sorting
- multi-filtering
- search
- capability/tag chips
- availability badges
- price/cost fields
- short description/recommended use
- compare selection
- request/add action
- responsive/accessible states

## Scope

### In Scope

- Implement reusable component against Slice 03 API/view model.
- Handle unknown/stale/unavailable states honestly.
- Support role-specific columns without forking the whole component.

### Out of Scope

- Agent settings layout.
- Voice settings layout.

## Dependencies

03

## Implementation Steps

1. Use `/impeccable` and Claude routing if supported.
2. Define shared table/view-model adapter.
3. Implement sorting/filtering/search and comparison interaction.
4. Implement clear usable/unavailable/requestable badges and action states.
5. Implement loading/error/no-credentials/partial-metadata states.
6. Add component/runtime tests.

## Files Likely Touched

- `jarvis/runtime/control_center.html or extracted frontend assets`
- `jarvis/runtime/control_center_work.js or new shared JS module`
- `tests/*ui*`

## Architecture Constraints

- Unknown values render as unknown, not zero/free/unsupported.
- Availability must remain visible under sorting/filtering.

## Automated Validation

- UI component tests.
- Deterministic fixture covering all availability states.
- Responsive runtime validation.

## Acceptance Criteria

- Component works for text/sub-agent and voice role data.
- Sort/filter/compare functions are deterministic.
- Unavailable items cannot be accidentally selected as usable.

## Documentation Updates

Document shared component props/fields and availability presentation.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
