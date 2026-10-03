# Slice 08 — Shared Prefab Library Management

## Goal

Provide a clear management surface for the shared prefab library so humans and Jarvis can understand what exists, where it came from, and what may safely be changed.

## Context

The user wants the library maintained for everyone to reuse. It must make base/system definitions distinct from custom/forked ones and support preview/inspection rather than becoming an opaque folder of code.

## Canonical Concepts

Shared prefab library, base prefab, fork/custom prefab, provenance, preview.

## Scope

### In Scope

- Browse/search/filter prefab definitions.
- Preview with defaults/sample data.
- Inspect inputs/events/version/provenance/usage where available.
- Distinguish base/system vs custom/fork visually and semantically.
- Save-as-new flow.
- Explicit base-edit affordance with strong wording/gate.
- Refresh/update after an agent creates a prefab.

### Out of Scope

- Global product settings unrelated to prefabs.
- Presentation-board settings.

## Dependencies

- `07-agent-prefab-operations`

## Implementation Steps

1. Integrate with the existing Jarvis settings/library navigation rather than adding a parallel admin shell.
2. Use the canonical catalog as the only source of prefab identities.
3. Build preview from validated runtime defaults.
4. Surface provenance/version/parent relationships.
5. Add explicit actions for instantiate/test/fork/save-as-new; protect base edit.
6. Ensure agent-created prefabs appear without manual page code changes.

## Files Likely Touched

Prefab/library frontend, shared settings/navigation integration, catalog endpoints, browser/visual tests.

## Architecture Constraints

The UI renders backend/catalog truth; it does not author a second hand-maintained prefab list.

## Automated Validation

- Search/filter/preview tests.
- Dynamic new-prefab visibility.
- Base/custom action gating.
- Browser interaction and visual regression coverage.

## Acceptance Criteria

- A user can understand available prefabs and their provenance.
- A newly saved prefab appears through catalog refresh/discovery.
- Base prefab modification is visibly distinct from instance/fork editing.

## Documentation Updates

Document library management workflow and ownership.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.
