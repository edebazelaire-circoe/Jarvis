# Slice 08 - Reliable audiovisual and fullscreen experience


## Goal
Fix sound, player readiness, fullscreen and external display integration without altering security authority.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 is a rejected floating viewer to retire; screenshot 2 is the Variants interface to retain and simplify. See ../../docs/06-screen-evidence.md. Do not build a second player.


## Canonical Concepts
Native Remotion Studio, Remotion composition, Player, Variants, pinned source, score and cues; verify current contracts and code owners.


## Scope
### In Scope
Fix sound, player readiness, fullscreen and external display integration without altering security authority.
### Out of Scope
- No second viewer or custom video engine; no 8-second cutoffs.
- No speculative redesign of left rail.
- No unrelated Board/agent/audio refactors.


## Dependencies
`05-continuous-remotion-sequencing`, `06-player-lifecycle-and-transport`


## Implementation Steps
1. Trace browser autoplay/unmute policies and implement clear muted/audio state and user gesture handling.
2. Ensure aspect ratio, scaling, letterboxing and fullscreen stage layout are stable through presentation changes.
3. Verify sound/video sync for native Remotion media and asset presence in local and exported composition.
4. Preserve sandbox/origin checks and prevent unsafe auto-launch of unsandboxed Studio.
5. Test 1080p and alternate aspect ratios, reduced-motion accessibility, Chrome reload and long sessions.


## Files Likely Touched
- docs/presentation-studio.md; docs/presentation-engine.md; docs/remotion-runtime.md
- Confirm current code owner mapping in Slice 01 and refresh HEAD.


## Architecture Constraints
Use one canonical Remotion composition clock and stable version/variant pins. Preserve Core-owned score/cues, Prefabs, Boards, Artifacts and data security. No silent Slidecar fallback. Never modify live Core or user data during tests.


## Automated Validation
- Focused tests plus isolated real-browser/Core/Remotion reproduction; capture frame-level evidence and tested SHA.
- qa-verification every Slice; code-review for code; runtime-validation for UI/runtime; agent-trace-analysis with real traces for agent runtime changes.
- New regressions block PM approval and cannot be deferred to Issues/.


## Acceptance Criteria
- An explicit user play gesture can start audio where allowed; failure is actionable.
- Full-screen preview shows the complete slide without the Jarvis graph or redundant control overlays.


## Documentation Updates
Update canonical contracts and log tested HEAD and findings; promote changed concepts to executable L3 acceptance tests.


## Handoff Notes
- PM selects a valid Workspace Task Type; never invent one.
- Coding requires /caveman and /coding-guideline.
- Human validation: Physical projector/second monitor and audio check required.