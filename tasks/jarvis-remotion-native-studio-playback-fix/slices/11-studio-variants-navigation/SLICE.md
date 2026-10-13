# Slice 11 - First-class Remotion Studio and Variants choices


## Goal
Expose native Remotion Studio and Jarvis Variants as adjacent, clearly named spaces sharing project identity.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 shows the unwanted floating viewer. Screenshot 2 shows Variants, the visual base to preserve and simplify. See ../../docs/06-screen-evidence.md. No second player or editor.


## Canonical Concepts
Native Remotion Studio, Player, Variants, pinned source, score/cues; verify current contracts and module owners.


## Scope
### In Scope
Expose native Remotion Studio and Jarvis Variants as adjacent, clearly named spaces sharing project identity.
### Out of Scope
- No second viewer or custom video engine; no 8-second playback cutoff.
- Left rail geometry not defined pending user sketch.
- No unrelated Board/agent/audio refactors.


## Dependencies
`02-product-experience-contract`, `09-remove-legacy-floating-viewer`, `10-variants-interface-control-audit`


## Implementation Steps
1. Add visible Studio and Variants navigation with active state, return path and browser permissions handling.
2. Choose presentation/version/composition once and pass stable identity across views; detect unsaved or unsynced source.
3. Surface Studio startup health, readiness, errors and explicit safety confirmation without making user hunt in Plugins settings.
4. Keep native Remotion Studio true to upstream UX; avoid cloning its timeline in Variants.
5. Preserve variant tree, preview and source provenance across switching; ensure only one authoring source authority.


## Files Likely Touched
- docs/presentation-studio.md; docs/presentation-engine.md; docs/remotion-runtime.md
- Control Center UI owners, Player/stage bridge and routes as verified by Slice 01; refresh HEAD before editing.


## Architecture Constraints
One canonical Remotion frame authority; maintain stable presentation, variant and prefab pins; preserve score/cues, Boards, Artifacts, security and data. No silent Slidecar fallback. Do not alter live Core while testing.


## Automated Validation
- Browser DOM/keyboard/focus/transport/UI tests and isolated real runtime testing with before/after screenshots and SHA.
- qa-verification, code-review, runtime-validation mandatory. Agent trace analysis with real traces if MCP, tool or routing behavior changes.
- New Slice regressions block approval; no Issues deferral.


## Acceptance Criteria
- User can navigate between Studio and Variants for the same presentation without losing selection or version.
- No duplicate Jarvis Studio implementation is introduced.


## Documentation Updates
Update canonical contracts and the UI ownership/retirement map; provide Level 3 conformance where relevant.


## Handoff Notes
- PM resolves valid Workspace Task Type; never invent one.
- Use /caveman, /coding-guideline, /impeccable; request Claude Work Agent for frontend when supported.
- Human validation: Human confirms Studio, Variants and close/fullscreen UX on actual browser.