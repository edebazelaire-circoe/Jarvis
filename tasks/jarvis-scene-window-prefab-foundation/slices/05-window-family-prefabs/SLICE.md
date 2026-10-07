# Slice 05 — Rework FENETRES as Base Prefab Families

## Goal

Implement the already-defined Rework FENETRES families as reusable base prefabs on top of the new runtime.

## Context

Windows are the first major reusable family and should become the best starting points Jarvis can choose from before creating custom objects.

## Canonical Concepts

Window family, base prefab, scene window instance.

## Scope

### In Scope

- Migrate the window families recovered in Slice 01.
- Extract genuinely variable properties as declared inputs.
- Preserve existing interaction/lifecycle semantics.
- Share common shell behavior by composition/inheritance according to canonical project rules.
- Register searchable aliases/tags/descriptions for agent discovery.

### Out of Scope

- Inventing new window families not supported by prior decisions/evidence.
- Presentation-specific window behavior.

## Dependencies

- `04-scene-prefab-bridge`

## Implementation Steps

1. Build the shared/base shell(s) required by the recovered taxonomy.
2. Convert each agreed family with minimal duplication.
3. Expose parameters such as title/accent/content/state only where truly variable.
4. Migrate call sites incrementally through adapters if required.
5. Add representative visual and interaction coverage for every family.

## Files Likely Touched

Window renderers/styles, prefab definitions, catalog metadata, scene adapters, browser/visual tests.

## Architecture Constraints

Do not use a prefab input as a hidden escape hatch for arbitrary HTML when a slot/child/data contract should exist.

## Automated Validation

- Snapshot/DOM tests per family.
- Browser geometry/resize/focus tests.
- Lifecycle regression tests.
- Existing call-site compatibility tests.

## Acceptance Criteria

- Every recovered family is available as a reusable prefab base.
- Existing window behavior is preserved.
- Jarvis can discover families through metadata rather than hardcoded knowledge.

## Documentation Updates

Document the final window family catalog and extension rules.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.

## Slice 00 contract (binding)

Families: exactly `jarvis.window`, `jarvis.document`, `jarvis.table` (06 D-FAMILIES). No invented family.

Create:
- `jarvis/prefabs/base/jarvis.window/1/*`: data `body` (`text`, markdown, ≤8000), `items` (array ≤64 of `{label, url?, ref?}`; labels **wrap**); props `accent` (color), `density` (enum `compact|comfortable`). No events.
- `jarvis/prefabs/base/jarvis.document/1/*`: data `body` (`text`, markdown, ≤12000); props `accent`, `scale` (enum `s|m|l`); scrolls in-frame; PageUp/PageDown/Home/End when focused.
- `jarvis/prefabs/base/jarvis.table/1/*`: data `columns` (array 1..8 of `{label ≤40, align: enum left|right|center}`), `rows` (array ≤64 of array ≤8 of string ≤200); props `accent`, `zebra` (boolean); event `row_selected` (notify, `{index}`).
- All three: `publication.json` (origin `base`, actor `system`) + entries in `catalog.lock.json`; shell classes reused, no duplicated shell CSS.

Touch:
- `docs/prefabs.md` §"Base catalogue" (table of inputs/events, extension rule: a new family = a new base id + lock entry + tests, no code change).
- `docs/mcp/plan-outils-interface.md` Catégorie F: mark `view_table` superseded by `jarvis.table`.
- Legacy renderer: **no change** (D-LEGACY).

Acceptance:
- `test_prefab_base_catalog.py`: each base manifest valid, samples valid, lock matches, search finds each by alias ("tableau", "document", "fenêtre").
- Node: each behavior in the shim with fake DOM renders empty/one/many samples, markdown via `renderBlocks`, accent CSS variable applied from props.
- Browser (Chrome): side-by-side legacy window vs `jarvis.window` with the same title/body/items (screenshots), long document fully readable by scrolling, 8×64 table, resize/fit, both CC themes.

Depends on: 04.
QA: qa-verification + code-review + runtime-validation. Frontend: /impeccable, Claude agent. Human: HV-WINDOW-FAMILIES-01 after machine QA.
