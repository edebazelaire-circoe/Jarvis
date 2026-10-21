# Slice 01 - Canonical Settings registry and six-category IA contract

## Goal

Create the reusable contract that fixes the Settings top-level information architecture at six categories and gives feature modules a supported way to register sections without mutating top-level navigation.

## Context

Today `control_center.html` owns a base `TABS` array while Wake word, Appearance and Experimental mutate it from separate modules. This pattern has already scaled from the original set to a new Sub-agents top-level page. The target needs a stable registry before visual/migration work proceeds.

## Canonical Concepts

- `docs/02-architecture.md`
- `docs/07-target-settings-map.md`
- `tasks/jarvis-settings-model-catalog-ux/docs/settings-ia-contract.json` as historical metadata evidence only

## Scope

### In Scope

- Define exactly six category IDs/labels/order.
- Define a section registration contract: stable ID, category, label, order/group, mount/destroy, save/dirty policy, optional alias metadata.
- Add duplicate-ID and unknown-category validation.
- Define explicit legacy tab alias mapping for the currently supported tab IDs.
- Add conformance tests so a future module cannot create category seven.
- Document the registry as the canonical Settings navigation contract.

### Out of Scope

- Do not redesign the shell yet.
- Do not move controls between categories yet.
- Do not change persistence/runtime semantics.

## Dependencies

- `00-project-manager`

## Implementation Steps

1. Freshness-check all current Settings injectors and tab IDs.
2. Choose the smallest reusable runtime/frontend registry location consistent with Control Center bundling conventions.
3. Implement six immutable top-level categories.
4. Implement section registration and validation.
5. Add temporary legacy tab aliases for existing programmatic callers.
6. Expose registry data to the current shell without changing visual output yet, or provide a migration adapter if the host architecture requires it.
7. Add unit/conformance tests.
8. Write/update the canonical Settings navigation documentation.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- new or existing Control Center Settings registry module
- Settings-related unit tests
- `docs/settings/*`

## Architecture Constraints

- Feature modules register sections; they do not mutate the top-level category list.
- Category IDs are stable implementation IDs; labels are presentation metadata.
- No setting metadata (ranges/options/defaults) is copied from backend schemas into the registry.

## Automated Validation

- Exactly six categories in canonical order.
- Duplicate section registration fails deterministically.
- Unknown category registration fails deterministically.
- Existing legacy IDs resolve to declared destinations.
- No new persistence write is introduced.

## Acceptance Criteria

- Six-category IA is machine-enforced.
- A feature can register a Settings section without adding a top-level tab.
- The contract is documented and discoverable.

## Documentation Updates

Create/update the durable Settings navigation/registry contract and point older IA documentation to the superseding contract.

## Handoff Notes

This Slice is the prerequisite architecture gate for every frontend migration Slice.
