# Slice 05 - Seamless full-deck Remotion playback


## Goal
Replace discontinuous per-scene playback behavior with complete authored-duration continuous playback.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 is a rejected floating viewer to retire; screenshot 2 is the Variants interface to retain and simplify. See ../../docs/06-screen-evidence.md. Do not build a second player.


## Canonical Concepts
Native Remotion Studio, Remotion composition, Player, Variants, pinned source, score and cues; verify current contracts and code owners.


## Scope
### In Scope
Replace discontinuous per-scene playback behavior with complete authored-duration continuous playback.
### Out of Scope
- No second viewer or custom video engine; no 8-second cutoffs.
- No speculative redesign of left rail.
- No unrelated Board/agent/audio refactors.


## Dependencies
`04-canonical-composition-clock`


## Implementation Steps
1. Implement full video composition/sequence orchestration from frozen or live presentation manifest.
2. Ensure each scene enters on the correct local frame, including transition overlap, without stale time carry from preceding scene.
3. Avoid remount/compile flashes where safe; prewarm media only when justified; show progress and meaningful compile errors.
4. Preserve exact source and variant pins; no hidden fallback to Slidecar on Remotion errors.
5. End at final image and stop or hold according to the UX contract; deterministic replay from frame zero.


## Files Likely Touched
- docs/presentation-studio.md; docs/presentation-engine.md; docs/remotion-runtime.md
- Confirm current code owner mapping in Slice 01 and refresh HEAD; do not rely on stale module guesses.


## Architecture Constraints
Use one canonical Remotion composition clock and stable version/variant pins. Preserve Core-owned score/cues, Prefabs, Boards, Artifacts and data security. No silent Slidecar fallback. Never modify live Core or user data during tests.


## Automated Validation
- Focused negative and positive tests for this Slice plus isolated real-browser/Core/Remotion reproduction as applicable; capture frame-level evidence and tested SHA.
- qa-verification required; code-review required for coding changes; runtime-validation required for UI/runtime changes; agent-trace-analysis with real traces if agent runtime affected.
- New regressions block PM approval and cannot be deferred to Issues/.


## Acceptance Criteria
- 9-scene playback has no unintended boundary flash, duplicate frame or mid-scene start.
- A 30s scene plays 30s and is never forcibly cut by an 8s global timer.
- Seamless boundary evidence is stored and reproducible.


## Documentation Updates
Update the canonical contracts and log tested HEAD and findings; promote changed concepts to executable L3 acceptance tests.


## Handoff Notes
- PM must select a valid Workspace Task Type; never invent one.
- Coding requires /caveman and /coding-guideline.
- Human validation: Watch and approve real continuous playback on target Windows/Chrome machine after machine gates pass.