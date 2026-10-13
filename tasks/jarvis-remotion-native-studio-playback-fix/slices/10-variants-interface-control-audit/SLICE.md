# Slice 10 - Simplify the existing Variants UI


## Goal
Keep screenshot-2 layout as the visual base while removing transport duplication and false progress indicators.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 shows the unwanted floating viewer. Screenshot 2 shows Variants, the visual base to preserve and simplify. See ../../docs/06-screen-evidence.md. No second player or editor.


## Canonical Concepts
Native Remotion Studio, Player, Variants, pinned source, score/cues; verify current contracts and module owners.


## Scope
### In Scope
Keep screenshot-2 layout as the visual base while removing transport duplication and false progress indicators.
### Out of Scope
- No second viewer or custom video engine; no 8-second playback cutoff.
- Left rail geometry not defined pending user sketch.
- No unrelated Board/agent/audio refactors.


## Dependencies
`02-product-experience-contract`, `06-player-lifecycle-and-transport`, `09-remove-legacy-floating-viewer`


## Implementation Steps
1. Create a per-button and per-panel audit (primary, secondary, obsolete) grounded in screenshot-2 and current DOM.
2. Consolidate play/pause inside Player; allow at most one supplemental global transport surface if justified and synchronized.
3. Retain a coherent thumbnail strip, active variant metadata and branch/rename/archive actions separate from playback.
4. Remove scene/all redundant play toggles and arbitrary 8s-per-slide controls from video flow; preserve relevant presenter advanced controls contextually.
5. Implement responsive layout, keyboard semantics, focus, accessible labels and selected-state clarity.
6. Ensure every visible readout is derived from canonical Player time or explicitly labeled as distinct authoring metadata.


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
- No contradictory 30s versus 8s playback bars.
- Users can identify play/pause, previous/next, seek, fullscreen and current scene without visually duplicated buttons.
- All original variant graph actions remain available.


## Documentation Updates
Update canonical contracts and the UI ownership/retirement map; provide Level 3 conformance where relevant.


## Handoff Notes
- PM resolves valid Workspace Task Type; never invent one.
- Use /caveman, /coding-guideline, /impeccable; request Claude Work Agent for frontend when supported.
- Human validation: Human validates visual control audit on 2 screenshots and live screen.