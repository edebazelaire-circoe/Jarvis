# Slice 04 - One composition and one playback clock contract


## Goal
Specify and implement one canonical time/frame source and a deterministic map from composition position to scene boundaries and variants.


## Context
Fix the existing Jarvis Presentation Studio/Remotion system. Screenshot 1 is a rejected floating viewer to retire; screenshot 2 is the Variants interface to retain and simplify. See ../../docs/06-screen-evidence.md. Do not build a second player.


## Canonical Concepts
Native Remotion Studio, Remotion composition, Player, Variants, pinned source, score and cues; verify current contracts and code owners.


## Scope
### In Scope
Specify and implement one canonical time/frame source and a deterministic map from composition position to scene boundaries and variants.
### Out of Scope
- No second viewer or custom video engine; no 8-second cutoffs.
- No speculative redesign of left rail.
- No unrelated Board/agent/audio refactors.


## Dependencies
`02-product-experience-contract`, `03-reproduce-timeline-and-transition-failures`


## Implementation Steps
1. Evaluate native Remotion Sequence/Series/TransitionSeries composition against per-scene sandbox and current isolation; document security tradeoffs.
2. Define frame/fps conversion, scene start/end, transition overlaps, local scene time, direction of sync, end-of-media and seek semantics.
3. Separate media clock from presenter score/cue authority; no duplicated competing playback state machine.
4. Build a pure frame mapping and tests for irregular durations and transition overlap.
5. Choose safe path to single composition without silently weakening isolation or mutating stored artifacts.


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
- One explicit time authority used by Player UI, scene index, global bar and timeline readouts.
- Frame mapping passes boundaries, overlaps, seek and paused conditions; security decision documented.


## Documentation Updates
Update the canonical contracts and log tested HEAD and findings; promote changed concepts to executable L3 acceptance tests.


## Handoff Notes
- PM must select a valid Workspace Task Type; never invent one.
- Coding requires /caveman and /coding-guideline.
- Human validation: None assigned; escalate genuinely physical decisions to PM after machine gates.