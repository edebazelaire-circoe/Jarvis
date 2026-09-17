# Slice 05 — Replace “Aiguillage” with technical-first Agent/CLI settings and catalog

## Goal

Ship the new Agent/CLI configuration surface and remove the old user-facing “Aiguillage” navigation without removing backend routing enforcement.

## Context

Recent `main` added an Aiguillage tab. The user now explicitly wants it removed and the useful controls relocated.

## Canonical Concepts

- remove old Aiguillage navigation and keep its legacy programmatic ID compatible
- technical options panel
- Auto/Dupliqué switch
- personality/behavior panel
- Sous-agents/Models catalog using shared table
- help text and advanced disclosure

## Scope

### In Scope

- Implement new layout and binding to Slice 02 APIs.
- Migrate useful routing controls into appropriate technical/catalog surfaces.
- Remove old Aiguillage label/tab and obsolete duplicated markup.

### Out of Scope

- Voice settings redesign.

## Dependencies

02, 04

## Implementation Steps

1. Use `/impeccable` and Claude routing if supported.
2. Build right-side/options area in Agent/CLI page with Technical first.
3. Place Auto/Dupliqué prominently and show consequences/help from canonical semantics.
4. Place verbosity/politeness and supported behavior controls after technical section.
5. Embed shared sub-agent/model catalog.
6. Remove the old Aiguillage tab and normalize its legacy programmatic tab ID.
7. Add persistence/runtime UI tests.

## Files Likely Touched

- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center.py`
- `frontend JS/CSS assets`
- `tests/*control_center*`

## Architecture Constraints

- Do not expose routing implementation jargon as a primary product concept.
- Do not duplicate backend policy logic in JavaScript.

## Automated Validation

- UI binding/persistence tests.
- Legacy programmatic tab-ID compatibility test.
- Runtime validation with catalog unavailable/available states.

## Acceptance Criteria

- No “Aiguillage” primary section remains.
- Technical settings are visually first.
- Auto/Dupliqué persists and reflects backend value.
- Catalog works in the new context.

## Documentation Updates

Update Control Center navigation/settings documentation and screenshots/fixtures if repository practice uses them.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
