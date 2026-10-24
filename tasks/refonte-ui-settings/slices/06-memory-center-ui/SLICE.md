# Slice 06 — Memory Center UI refactor

## Goal

Refactor **Memory Center** into the supplied dense inspection/decision workspace with summary metrics, tabs, notes table, candidate review, recall test, essential settings and source/index health.

## Context

Reference: `references/ui/05-memory-center.png`.

Memory Center is not a normal settings form. It is a workbench for inspecting canonical notes, reviewing consolidation candidates, inspecting knowledge and testing recall, while still using the same Jarvis visual language.

## Canonical Concepts

- `REFERENCE.md`
- current Memory Center/candidate/recall APIs
- canonical memory vs derived index distinction
- existing optimistic candidate decision semantics

## Scope

### In Scope

- Hero/header card with Memory Center identity and live summary metrics.
- Internal tabs for Notes, Candidates, Connaissances and Test de rappel (or current canonical labels with equivalent meaning).
- Notes table/list with selectable rows, level/type/scope/retention/date metadata when supported, pagination/virtualization as appropriate and row actions.
- Candidate review rail/cards with accept/reject actions, pending/error feedback and count summary.
- Recall Test panel with query input, execute action and ranked recalled items/scores where exposed.
- Essential settings quick controls that deep-link or mutate only canonical settings and do not create duplicates.
- Source/index health summary that is concise; detailed service/index diagnostics remain Advanced.
- Search/filter controls for large note sets.
- Empty/loading/error states for each tab/rail.

### Out of Scope

- Do not treat derived index health as canonical memory truth.
- Do not invent retention scores/levels or source counts not present in the runtime.
- Do not surface low-level Tencent/service/index internals just because the mockup has a small status card.
- Do not bypass candidate concurrency/revision protections.

## Dependencies

- `01-settings-visual-foundation`

## Implementation Steps

1. Load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent when supported.
2. Confirm current Memory Center APIs and state models, including note pagination/filtering, candidate decisions and recall testing.
3. Capture current workbench before-state.
4. Build the hero/status strip and internal tab treatment using live metrics.
5. Recompose Notes as the dominant left work surface with readable dense columns, consistent row height, selection and pagination/virtualization.
6. Recompose Candidates as compact decision cards in the right rail; preserve optimistic update/revision/error handling.
7. Recompose Recall Test as a compact query/result panel with scores/relevance only when the API supplies them.
8. Add Essential Settings quick controls only as projections/shortcuts to canonical memory settings; clearly link back to full settings.
9. Add source/index health summary with honest active/unavailable/degraded states and deep-link detailed diagnostics to Advanced.
10. Validate large note counts, no candidates, no recall results, unavailable source and mutation conflict states.
11. Ensure table/rail layout remains usable at 1254×1254 and wider desktop; at narrower widths stack the rail below the main work surface.
12. Capture final screenshots for populated workbench plus one empty/degraded state.

## Files Likely Touched

Resolve exact paths during Slice 00. Expect Memory Center renderer/controller, candidate/recall UI modules, shared dense table styles and focused tests.

## Architecture Constraints

- Canonical memory and existing Memory Center APIs remain authoritative.
- Candidate writes preserve concurrency/revision/error handling.
- Quick controls do not create a second writable settings store.
- Detailed diagnostics remain outside the main workbench.

## Automated Validation

- Notes pagination/search/filter returns correct current data and preserves selection semantics.
- Candidate accept/reject operations preserve optimistic/error behavior.
- Recall test results render in returned order with available score metadata.
- Empty/error/degraded states are visually intentional.
- Keyboard navigation reaches tabs, table actions, candidate actions and recall input.
- Screenshot regression covers populated 1254×1254 workbench.

## Acceptance Criteria

- The workbench is visually recognizable as the supplied Memory Center reference.
- Notes remain the dominant working surface while the right rail stays actionable and compact.
- Dense information remains readable rather than collapsing into HUD noise.
- No fake metrics or memory/index semantics are introduced.

## Documentation Updates

Document Memory Center layout, tab responsibilities, source-health summary policy and the distinction between canonical memory and derived indexes.

## Handoff Notes

Memory Center may legitimately be denser than the rest of Settings, but density must come from information architecture, not tiny type or indiscriminate borders.
