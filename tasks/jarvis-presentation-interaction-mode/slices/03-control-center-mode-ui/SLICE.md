# Slice 03 — Control Center interaction-mode UI

## Goal

Expose the canonical interaction mode clearly in the existing Control Center without inventing a second settings surface.

## Context

The user needs to deliberately choose Presentation mode. Existing Control Center conventions and UI/MCP parity should be preserved.

## Canonical Concepts

Control Center, effective interaction mode, UI/MCP parity, SIMPLE, PRESENTATION, REUNION reserved state.

## Scope

### In Scope

- Reuse or complete the existing mode control.
- Show current effective mode and mode-change feedback.
- Keep SIMPLE and PRESENTATION clearly selectable.
- If REUNION already exists in product UI, keep it visibly reserved/disabled/coming rather than inventing behavior.
- Ensure Jarvis can perform the same supported mode switch through the canonical MCP/settings surface if parity rules require it.

### Out of Scope

- Reworking the entire Control Center.
- Meeting/reunion behavior.

## Dependencies

- `02-interaction-mode-contract`

## Implementation Steps

1. Inspect current mode control implementation.
2. Extend existing visual language and accessibility semantics.
3. Bind directly to canonical mode state/actions.
4. Add UI state/error/loading behavior.
5. Add UI/MCP parity tests where applicable.

## Files Likely Touched

Existing Control Center HTML/JS/CSS, settings/MCP facade, frontend/runtime tests.

## Architecture Constraints

Extend existing controls; do not create a parallel settings panel or direct frontend-owned truth.

## Automated Validation

Frontend unit tests, integration tests against canonical mode state, MCP parity checks, visual/runtime regression pass.

## Acceptance Criteria

The user can enter/leave PRESENTATION from the existing Control Center and the UI reflects authoritative runtime state.

## Documentation Updates

Update interaction-mode Control Center docs/help text.

## Handoff Notes

Frontend coding Slice: load `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude agent when host routing supports it.
