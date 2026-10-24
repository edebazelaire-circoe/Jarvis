# Slice 04 — Memory advanced diagnostics

## Goal
Create the Advanced destination for low-level Memory configuration and diagnostics removed from the normal page.

## Context
The user wants ordinary Settings to stay conceptual. Current Memory settings expose Tencent, raw timeout and detailed status inline.

## Canonical Concepts
Memory settings schema/status and `Avancé & diagnostic` target IA.

## Scope
### In Scope
- raw recall timeout;
- Tencent enable/url/service id/private permission;
- detailed lexical/semantic/Tencent status and degradation codes;
- index sync and mirror health;
- effective setting provenance where useful;
- technical restart messaging;
- deep-link target for concise warnings in Memory/Memory Center.

### Out of Scope
- no changes to Tencent protocol/runtime;
- no invented rebuild/resync actions unless a live route exists;
- no user-facing credential value display.

## Dependencies
### Hard `depends_on`
None after Slice 00 READY.

### Soft `requires`
- broader Settings Advanced shell from the related reorganization task; fallback: implement a mountable Advanced-memory section with stable registration metadata.

### Can Start With
Existing memory schema/status payloads and current advanced target map.

### Produces
Mountable Advanced-memory diagnostics/configuration section.

### Integration Checkpoint
Slice 05 registers it into the final Advanced shell.

## Implementation Steps
1. Inventory every low-level field/status leaving normal Memory.
2. Build schema/status-driven Advanced section.
3. Preserve source/downgrade/restart truthfulness.
4. Add stable deep-link/registration seam.

## Files Likely Touched
New Advanced-memory frontend module and narrow registration metadata; avoid shared shell until Slice 05.

## Architecture Constraints
No runtime semantics change. No secret values.

## Automated Validation
Static/build plus narrow status/config smoke checks. Do not launch the unit test suite at this Slice boundary.

## Acceptance Criteria
Every removed technical capability remains discoverable in Advanced without duplicating editable homes.

## Documentation Updates
Update Advanced diagnostics map.

## Handoff Notes
Frontend Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported.
