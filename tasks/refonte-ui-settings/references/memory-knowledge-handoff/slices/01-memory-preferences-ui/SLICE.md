# Slice 01 — Memory preferences UI

## Goal
Build the redesigned `Mémoire` user-facing surface for recall, semantic retrieval and consolidation.

## Context
Current backend schema/status contracts already exist. This Slice changes presentation and grouping, not memory semantics.

## Canonical Concepts
`docs/settings/memory.md`, `jarvis/runtime/memory_settings.py`, `jarvis/domain/memory_settings.py`.

## Scope
### In Scope
- recall enabled and max-items control;
- semantic enabled/provider/private permission;
- consolidation mode/confidence/candidate budget;
- concise status summary and Memory Center CTA;
- truthful restart notices;
- schema-driven ranges/options.

### Out of Scope
- no raw timeout as primary UI;
- no Tencent operator fields;
- no loadout editor;
- no Memory Center list/detail UI.

## Dependencies
### Hard `depends_on`
None after Slice 00 READY.

### Soft `requires`
- Slice 04: Advanced destination/deep-link target. Fallback: render a stable `advanced-memory` intent/callback and integrate in Slice 05.

### Can Start With
Existing `/api/settings` memory payload and current `control_center_memory_settings.js` behavior fixtures.

### Produces
A standalone Memory preferences module/component ready for shell integration.

### Integration Checkpoint
Slice 05 live mount/navigation wiring.

## Implementation Steps
1. Preserve server schema as source of truth.
2. Recompose controls into product cards/sections.
3. Remove low-level timeout/Tencent/diagnostic clutter from default view.
4. Preserve dependency disabling and compatibility messaging.
5. Add concise summary and CTA/deep-link seams.

## Files Likely Touched
Prefer a new/isolated memory preferences module; minimize shared shell edits before Slice 05. Existing `control_center_memory_settings.js` may be refactored if ownership is isolated.

## Architecture Constraints
No browser-only copies of ranges/options/providers. No secret values.

## Automated Validation
Syntax/build/static checks and a narrow render/save smoke check. Do not launch the unit test suite at this Slice boundary.

## Acceptance Criteria
The normal Memory view is understandable without exposing raw runtime internals and all persisted writes retain current semantics.

## Documentation Updates
Update Memory Settings UI destination docs.

## Handoff Notes
Frontend Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported.
