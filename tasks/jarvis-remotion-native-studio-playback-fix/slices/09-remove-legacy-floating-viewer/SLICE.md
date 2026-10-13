# Slice 09 - Retire the unwanted floating presentation visualizer


## Goal
Remove the screenshot-1 viewer path and its redundant entry points without orphaning required presentation capabilities.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 shows the unwanted floating viewer. Screenshot 2 shows Variants, the visual base to preserve and simplify. See ../../docs/06-screen-evidence.md. No second player or editor.


## Canonical Concepts
Native Remotion Studio, Player, Variants, pinned source, score/cues; verify current contracts and module owners.


## Scope
### In Scope
Remove the screenshot-1 viewer path and its redundant entry points without orphaning required presentation capabilities.
### Out of Scope
- No second viewer or custom video engine; no 8-second playback cutoff.
- Left rail geometry not defined pending user sketch.
- No unrelated Board/agent/audio refactors.


## Dependencies
`01-independent-intention-and-code-audit`, `02-product-experience-contract`, `06-player-lifecycle-and-transport`


## Implementation Steps
1. Inventory open/show/close commands, menus, voice verbs, state persistence and linked objects pointing at old viewer.
2. Choose feature migration targets (Variants or embedded Player) for each unique capability.
3. Disable legacy UI entry points, retire code and styles after compatibility tests, and migrate persisted view preference safely.
4. Ensure one canonical window/object lifecycle and no background duplicate Player.
5. Update MCP/voice intent routes or deprecate with typed errors; retain historical data and old presentation sources.


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
- The unwanted floating viewer is no longer reachable by GUI, voice or stale state.
- Opening a presentation shows an intentional Variants/Player route and no duplicate display.


## Documentation Updates
Update canonical contracts and the UI ownership/retirement map; provide Level 3 conformance where relevant.


## Handoff Notes
- PM resolves valid Workspace Task Type; never invent one.
- Use /caveman, /coding-guideline, /impeccable; request Claude Work Agent for frontend when supported.
- Human validation: Human visually confirms screenshot-1 experience no longer appears.