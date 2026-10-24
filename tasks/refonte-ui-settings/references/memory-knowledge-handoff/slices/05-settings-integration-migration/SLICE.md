# Slice 05 — Settings integration and migration

## Goal
Converge the four parallel surfaces into the final `Mémoire & connaissances` page and Advanced destinations.

## Context
This Slice owns shared hot-file wiring and single-home cleanup after parallel modules are ready.

## Canonical Concepts
Settings IA contract; memory schema/status; legacy deep-link compatibility.

## Scope
### In Scope
- final navigation/mount wiring;
- `Mémoire`, `Connaissances`, `Memory Center` internal routing;
- register Advanced memory section;
- remove duplicate low-level controls from ordinary Memory;
- preserve supported legacy Memory tab/deep links through aliases if required;
- reconcile source status and loadout labels with runtime/current role registry;
- accessibility/keyboard/focus integration.

### Out of Scope
- no new memory behavior;
- no broad unrelated Settings redesign.

## Dependencies
### Hard `depends_on`
- 01 — needs finished Memory preferences module.
- 02 — needs finished Knowledge/loadout module.
- 03 — needs finished Memory Center module.
- 04 — needs Advanced-memory destination.

### Soft `requires`
- related Settings shell task current state; fallback: preserve existing shell and register through its supported hooks.

### Can Start With
Not dispatched until all hard predecessors complete.

### Produces
Integrated page, migration aliases and final user-visible Settings behavior.

### Integration Checkpoint
Complete before Slice 06.

## Implementation Steps
1. Freshness-check shared shell and related task changes.
2. Wire modules into one page.
3. Remove duplicate editable homes.
4. Add legacy route aliases as needed.
5. Validate keyboard/focus/deep links/restart messaging.

## Files Likely Touched
Shared Settings shell/mount files, integration registries, related docs.

## Architecture Constraints
One canonical editable home per setting; current persistence keys remain authoritative.

## Automated Validation
Build/static and targeted integration smoke. Do not launch the unit test suite at this Slice boundary.

## Acceptance Criteria
The integrated page exposes all intended functionality once, preserves legacy access where supported and does not lose backend capability.

## Documentation Updates
Update Settings IA and memory docs.

## Handoff Notes
Frontend/code Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported.
