# Slice 03 - Generic Fullscreen Borderless Surface

## Goal
Add a real fullscreen borderless display mode through the canonical Jarvis scene/window host so presentation surfaces and compatible prefabs can use it.

## Context
The user explicitly wants a true video-like fullscreen experience, not a large bordered window or CSS-only imitation.

## Canonical Concepts
Scene/window surface mode, focus, selected display, restore state, presentation surface.

## Scope
### In Scope
- Fullscreen borderless enter/exit API.
- Selected-display handling according to host capability.
- Hide Jarvis/application chrome on the active presentation surface.
- Restore prior size/position/focus on exit.
- Keyboard/emergency exit behavior.
- Compatibility with ordinary eligible windows/prefabs.

### Out of Scope
- Presentation-specific score/cue logic.
- Variant Explorer design.

## Dependencies
- `01-contract-audit`
- External: canonical Scene/Prefab/window host contract must be available.

## Implementation Steps
1. Identify actual desktop/browser/window shell.
2. Implement real host fullscreen when available; do not silently label CSS-only expansion as equivalent.
3. Expose semantic surface operation through current UI/scene tooling.
4. Preserve/restore previous layout and focus.
5. Test multi-monitor/selected-display behavior where test harness permits.

## Files Likely Touched
Scene/window host, UI surface adapter, agent/tool schema and related tests.

## Architecture Constraints
Fullscreen is a generic surface capability, not a presentation-only renderer fork.

## Automated Validation
State-transition tests, restore tests, invalid display/focus handling, permission/user-gesture handling, regression tests for normal window mode.

## Acceptance Criteria
Compatible surfaces can enter/exit fullscreen borderless reliably and restore the previous workspace.

## Documentation Updates
Document fullscreen semantics and host limitations/failure modes.

## Handoff Notes
Frontend Slice: use `/caveman`, `/coding-guideline`, `/impeccable`, and a Claude agent when supported.
