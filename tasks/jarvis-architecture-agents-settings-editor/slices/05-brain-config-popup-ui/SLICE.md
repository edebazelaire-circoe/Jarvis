# Slice 05 - Brain config popup UI

## Goal

Build the contextual floating brain configuration experience opened from the Architecture canvas, with no permanent Brain tab.

## Context

The popup edits one selected brain while preserving visual context of the graph. It controls the brain's identity/model/mission/instructions/delegation, not global role candidate mappings.

## Canonical Concepts

- `docs/06-functional-spec.md` section C
- approved Architecture reference image

## Scope

### In Scope

- Floating/draggable config panel or responsive overlay.
- Brain identity/status/system-lock display.
- Provider/model selector from adapter data.
- Mission/prerogative fields described by capability schema.
- Brain-specific instructions when supported.
- Valid activation toggle when supported.
- Five-level delegation control.
- Read-only connection summary + focus/edit-on-graph affordance.
- Validation, unavailable reasons, loading/save/conflict/error states.
- Close/apply/cancel and focus management.

### Out of Scope

- No role -> model candidate mapping.
- No personality/tone/verbosity settings.
- No raw CLI path/permission diagnostics.
- No independent connection persistence contract.
- No shared page registration until Slice 07.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

- Slice 02:
  - need: brain config descriptor/read/write payload.
  - fallback: fixture adapter following `docs/02-architecture.md`.
  - integration_required_before: Slice 07 live wiring.
  - mismatch_policy: adapt form schema/transport, preserve locked user-facing field responsibilities.
- Slice 01:
  - need: connection summary and graph focus identifiers.
  - fallback: display `unavailable` connection summary and emit brain id only.
  - integration_required_before: Slice 07.
  - mismatch_policy: use graph canonical ids.
- Slice 04:
  - need: open/close/select and graph-focus event contract.
  - fallback: expose component-level callbacks.
  - integration_required_before: Slice 07.
  - mismatch_policy: reconcile callbacks without duplicating state.

### Can Start With

Approved reference and local fixtures.

### Produces

- reusable contextual brain config component;
- adapter/form schema;
- event hooks for Architecture canvas.

### Integration Checkpoint

Slice 07 mounts it with live brain config and graph adapters.

## Implementation Steps

1. Build floating/responsive panel shell.
2. Render fields from capability descriptor, not one hard-coded form for all brains.
3. Implement live catalog model selector states.
4. Implement mission/instruction editing.
5. Implement five-level delegation control.
6. Add connection summary/focus action.
7. Add robust save/cancel/conflict/error behavior.
8. Verify focus/keyboard/drag ergonomics.

## Files Likely Touched

New dedicated brain config UI JS/CSS module; avoid shared shell files until Slice 07.

## Architecture Constraints

One selected brain config at a time. No role routing state in this component. No duplicate connection owner.

## Automated Validation

Frontend build/static checks, form/state fixture smoke, keyboard/focus smoke, targeted runtime validation if route fixture is available. **Do not launch the unit test suite at this Slice boundary.**

## Acceptance Criteria

- No Brain tab is needed to fully configure a supported brain.
- Unsupported fields are absent/disabled with explanation, not fabricated.
- Delegation levels are complete and clear.
- Model/provider options are adapter/server-driven.
- Popup remains usable without hiding all architecture context on normal desktop size.

## Documentation Updates

Document component contract and field-capability mapping where appropriate.

## Handoff Notes

Requires `/caveman`, `/coding-guideline`, `/impeccable`; use Claude Work Agent for frontend implementation/review where supported.
