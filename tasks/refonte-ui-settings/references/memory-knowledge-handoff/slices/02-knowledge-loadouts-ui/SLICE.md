# Slice 02 — Knowledge sources and loadouts UI

## Goal
Create the `Connaissances` surface and make agent knowledge access/loadouts editable through normal UI.

## Context
Current loadouts are supported by backend settings but shown read-only. Runtime availability must be separated from desired enablement.

## Canonical Concepts
`docs/skills-and-loadouts.md`, `jarvis/core/loadout_resolver.py`, `jarvis/runtime/memory_settings.py`.

## Scope
### In Scope
- source cards for Wiki, CodeGraph, Skills;
- status distinction active/disabled/unavailable;
- editable matrix/cards for Memory/private/Wiki/CodeGraph/Skills per agent/role;
- create/update/remove loadout overrides through canonical Memory settings write path;
- product-language explanation of private/shared/project scopes.

### Out of Scope
- no new knowledge providers;
- no fake CodeGraph availability;
- no changes to deny-by-default private access semantics;
- no architecture connection editing.

## Dependencies
### Hard `depends_on`
None after Slice 00 READY.

### Soft `requires`
- current role vocabulary from subagent registry; fallback: consume current server-provided roles/loadout keys through an adapter rather than hard-code labels.

### Can Start With
Existing `memory.loadouts` schema, resolver and Settings POST semantics.

### Produces
A standalone Knowledge/loadout UI module plus mapping adapter from product rows to canonical loadout keys.

### Integration Checkpoint
Slice 05 mounts it beside Memory and reconciles role labels with current Architecture & Agents work.

## Implementation Steps
1. Read actual provider runtime status.
2. Design source state cards.
3. Build loadout matrix/editor without exposing raw scope strings as primary UX.
4. Preserve explicit private-scope confirmation/rules.
5. Support removing an override so built-in preset applies again.

## Files Likely Touched
New isolated knowledge/loadout frontend module, possible narrow helpers around existing memory settings payload.

## Architecture Constraints
Resolver remains authority for effective access. UI writes policy only.

## Automated Validation
Static/build checks and narrow write/readback smoke checks. Do not launch the unit test suite at this Slice boundary.

## Acceptance Criteria
A user can understand and change which knowledge kinds an agent/role can access without editing the JSON settings file.

## Documentation Updates
Update loadout Settings docs and examples.

## Handoff Notes
Frontend Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported.
