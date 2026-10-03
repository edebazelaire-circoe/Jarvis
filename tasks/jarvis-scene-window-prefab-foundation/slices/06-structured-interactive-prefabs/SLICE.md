# Slice 06 — Structured and Interactive Prefabs

## Goal

Prove the system supports data-driven actionable objects by implementing a reusable interactive prefab using structured inputs; use a checklist unless the audited repository already has a better canonical proof object.

## Context

The user explicitly wants Jarvis to populate objects from JSON/lists and to interact with them without rewriting source code.

## Canonical Concepts

Structured prefab input, local instance state, semantic event.

## Scope

### In Scope

- Array/object payload rendering.
- Empty/single/many item states.
- Local interaction state where appropriate.
- Semantic output events.
- Runtime update with a new structured payload.
- Variable-driven appearance (e.g. accent/color) without source mutation.

### Out of Scope

- Arbitrary tool execution from UI JavaScript.
- Presentation orchestration.

## Dependencies

- `05-window-family-prefabs`

## Implementation Steps

1. Implement checklist or evidence-backed equivalent prefab.
2. Define structured input schema and defaults.
3. Render items through owned structure/composition.
4. Emit semantic events for user actions.
5. Update instance data without remount leaks.
6. Add accessibility/keyboard behavior.

## Files Likely Touched

Prefab definition/resources, structured input validators if gaps remain, runtime update path, frontend tests.

## Architecture Constraints

Local UI interactions may be handled locally; actions with Jarvis-side consequences must leave through the controlled event bridge.

## Automated Validation

- Empty/one/many/nested data fixtures.
- Toggle/update events.
- Rerender/update without duplicate listeners.
- Keyboard/a11y checks.
- Color/variable change without definition edits.

## Acceptance Criteria

- Jarvis can instantiate the prefab with a JSON/list payload.
- User interaction emits meaningful events.
- Updating the payload changes the instance safely.
- No source-code edit is required for ordinary content/color changes.

## Documentation Updates

Add a worked example for structured prefab inputs and events.

## Handoff Notes

Use `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when supported.

## Slice 00 contract (binding)

Create:
- `jarvis/prefabs/base/jarvis.checklist/1/*` per the manifest example in 06 R2. `item_toggled` (state, writes `items`), `checklist_completed` (notify). Optional per-item `note` (text). Progress bar when `show_progress`. Keyboard: Tab enters the list, arrows move, Space toggles, `aria-checked` on `role="checkbox"` rows. Empty state text.
- Lock entry + publication.

Touch: `docs/prefabs.md` worked example "structured inputs and events" (create payload, toggle round-trip, notify in the log). Nothing else unless a defect in S02-S04 is found; then report to the PM.

Acceptance:
- Domain/core: sample data empty/1/64 items, 65 items refused, nested note bounds; toggle event applied via `PrefabEventService` (revision +1, data persisted); concurrent brain update of `items` → host basis stale → `stale`, nothing written; completed → notify entry in `GET /v1/prefabs/events`.
- Node: shim behavior toggles emit exactly one event per action; `update` with new items re-renders without duplicate listeners (count listeners on the fake DOM over 50 updates); accent change without source change.
- Browser: tick items with mouse and keyboard; reload → state kept; brain-side (HTTP as brain) data replacement → frame updates without remount (frame identity kept); a11y check (role/aria/focus visible).

Depends on: 05.
QA: qa-verification + code-review + runtime-validation. Frontend: /impeccable, Claude agent.
