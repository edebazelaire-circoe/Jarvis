# Slice 07 - Presenter cue and score bridge without clock conflict


## Goal
Retain presenter/cue/sidekick workflows while removing timing interference with video playback.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 is a rejected floating viewer to retire; screenshot 2 is the Variants interface to retain and simplify. See ../../docs/06-screen-evidence.md. Do not build a second player.


## Canonical Concepts
Native Remotion Studio, Remotion composition, Player, Variants, pinned source, score and cues; verify current contracts and code owners.


## Scope
### In Scope
Retain presenter/cue/sidekick workflows while removing timing interference with video playback.
### Out of Scope
- No second viewer or custom video engine; no 8-second cutoffs.
- No speculative redesign of left rail.
- No unrelated Board/agent/audio refactors.


## Dependencies
`04-canonical-composition-clock`, `06-player-lifecycle-and-transport`


## Implementation Steps
1. Compare media run with manual-presenter run; do not assume continuous video and cue-driven presentation have identical stepping.
2. Align score anchors to source frames where explicit; avoid per-slide dwell timers that cut motion.
3. Maintain legitimate cue/voice control, stop, pause, resume, interruption and detours with typed refusal and graceful fallback to keyboard.
4. Handle voice architecture unavailable as a status signal, not as a reason video playback fails.
5. Add scenario tests using fake speech and documented real microphone checks without claiming live voice proof.


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
- Media video can play without ambient voice; presenter navigation and cues still function.
- No speech, cue or tool is triggered by a media frame without corresponding authorized input.


## Documentation Updates
Update canonical contracts and log tested HEAD and findings; promote changed concepts to executable L3 acceptance tests.


## Handoff Notes
- PM selects a valid Workspace Task Type; never invent one.
- Coding requires /caveman and /coding-guideline.
- Human validation: Validate real spoken cues, audio routing and dual-screen presentation on the target machine.