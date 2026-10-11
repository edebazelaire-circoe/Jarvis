# Slice 06 - Correct Player lifecycle, seek and transport


## Goal
Make play, pause, replay, next, previous, scene selection and seek deterministic against the single Player.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 is a rejected floating viewer to retire; screenshot 2 is the Variants interface to retain and simplify. See ../../docs/06-screen-evidence.md. Do not build a second player.


## Canonical Concepts
Native Remotion Studio, Remotion composition, Player, Variants, pinned source, score and cues; verify current contracts and code owners.


## Scope
### In Scope
Make play, pause, replay, next, previous, scene selection and seek deterministic against the single Player.
### Out of Scope
- No second viewer or custom video engine; no 8-second cutoffs.
- No speculative redesign of left rail.
- No unrelated Board/agent/audio refactors.


## Dependencies
`04-canonical-composition-clock`, `05-continuous-remotion-sequencing`


## Implementation Steps
1. Define Player ready/loading/error lifecycle with explicit resume and restart semantics.
2. Route all transport controls to a single store/Player ref and scene frame conversion.
3. Handle scrub across scene boundaries, backward seek, restart from first frame and pause on resume.
4. Prevent duplicate event listeners, overlapping commands, stale iframe messages, and double-step on rapid input.
5. Test keyboard, pointer, fullscreen handoff, unmount/mount, focus restore and lost Core connectivity.


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
- Scrubbing either bar changes both readouts and the preview instantly within frame-precision.
- Next always begins at scene start, previous behavior is contractually defined, and repeated rapid input cannot drift.


## Documentation Updates
Update canonical contracts and log tested HEAD and findings; promote changed concepts to executable L3 acceptance tests.


## Handoff Notes
- PM selects a valid Workspace Task Type; never invent one.
- Coding requires /caveman and /coding-guideline.
- Human validation: None assigned; escalate genuinely physical decisions to PM after machine gates.