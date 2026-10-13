# Slice 03 - Runtime reproduction and observability


## Goal
Prove where playback breaks: first-frame, mid-scene resume, visible scene boundaries, incompatible clocks and stalls.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 is a rejected floating viewer to retire; screenshot 2 is the Variants interface to retain and simplify. See ../../docs/06-screen-evidence.md. Do not build a second player.


## Canonical Concepts
Native Remotion Studio, Remotion composition, Player, Variants, pinned source, score and cues; verify current contracts and code owners.


## Scope
### In Scope
Prove where playback breaks: first-frame, mid-scene resume, visible scene boundaries, incompatible clocks and stalls.
### Out of Scope
- No second viewer or custom video engine; no 8-second cutoffs.
- No speculative redesign of left rail.
- No unrelated Board/agent/audio refactors.


## Dependencies
`01-independent-intention-and-code-audit`


## Implementation Steps
1. Build isolated local Core/Control Center/Remotion runtime harness; never touch live user session.
2. Reproduce a 9-scene video and a mixed-duration suite: 3s, 8s, 30s scenes plus transitions and varying fps.
3. Record Player frame, composition frame, scene index, source duration, playback phase, seek source, load/mount events and Core score position with structured diagnostics.
4. Measure blackout/freeze/flash at boundaries and record frame-accurate screenshots or video clips.
5. Track whether native Studio alone reproduces defects (control group).
6. Create red regression tests for each confirmed failure; no hard-coded workaround without causality.


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
- Evidence identifies which clock/control owns displayed 2.6/30s versus 2/8s and how they diverge.
- Tests fail on original broken flow and become a reusable release gate.


## Documentation Updates
Update the canonical contracts and log tested HEAD and findings; promote changed concepts to executable L3 acceptance tests.


## Handoff Notes
- PM must select a valid Workspace Task Type; never invent one.
- Coding requires /caveman and /coding-guideline.
- Human validation: None assigned; escalate genuinely physical decisions to PM after machine gates.