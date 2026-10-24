# Slice 03 — Memory Center UI

## Goal
Redesign Memory Center as a dedicated inspection/decision workspace while preserving its APIs and behavioral safeguards.

## Context
Current Memory Center already implements Notes, Candidates, Health, Knowledge and Recall Test. This Slice improves hierarchy rather than inventing new storage behavior.

## Canonical Concepts
`docs/memory.md`, `/api/memory/*`, `jarvis/runtime/control_center_memory.js`.

## Scope
### In Scope
- Notes list/search/filter/detail;
- Candidates queue/detail/accept/reject confirmation;
- Knowledge inspection with link back to editable Knowledge Settings;
- Recall Test with why/ranks/timings/degraded hints;
- compact canonical/derived labeling;
- secondary health access.

### Out of Scope
- no direct canonical-note editor unless a current Core route is proven to exist;
- no index rebuild button;
- no duplicate loadout editor.

## Dependencies
### Hard `depends_on`
None after Slice 00 READY.

### Soft `requires`
- Slice 02 editable Knowledge destination; fallback: expose a callback/deep-link seam and reconcile in Slice 05.
- Slice 04 Advanced health destination; fallback: retain existing health view as secondary until integration.

### Can Start With
Existing `/api/memory/*` contracts and current `control_center_memory.js` implementation.

### Produces
Redesigned Memory Center module preserving all current error/conflict/confirmation semantics.

### Integration Checkpoint
Slice 05 deep-links and tab placement.

## Implementation Steps
1. Preserve canonical/derived distinction.
2. Recompose Notes and Candidates for higher information density.
3. Keep recall-explain semantics and non-writing guarantee.
4. Keep candidate confirmation/error behavior.
5. Make health secondary and link outward where possible.

## Files Likely Touched
`jarvis/runtime/control_center_memory.js` and related styles/tests/docs.

## Architecture Constraints
Candidate decision remains the owner-facing write. Search/recall results remain derived.

## Automated Validation
Static/syntax checks plus narrow mocked/runtime flow smoke checks. Do not launch the unit test suite at this Slice boundary.

## Acceptance Criteria
Memory Center is useful as an inspection workspace without confusing derived search/index state with canonical memory.

## Documentation Updates
Update Memory Center usage docs.

## Handoff Notes
Frontend Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent where supported.
