# Slice 02 - Single presentation UX and semantics contract


## Goal
Lock a product contract for Remotion Studio versus Variants, one video runtime, navigation, timing and presenter semantics before changing controls.


## Context
This is a fix of an existing Jarvis Presentation Studio + Remotion implementation. User screenshot 1 is an unwanted floating presentation viewer to retire; screenshot 2 is the Variants base to preserve but simplify. Refer to `../../docs/06-screen-evidence.md` and latest inspected implementation. This Slice does not authorize an additional viewer or media engine.


## Canonical Concepts
Remotion composition, native Remotion Studio, Variants, source and variant pins, playback clock, score/cues where relevant. Read canonical references rather than copying their contracts.


## Scope
### In Scope
Lock a product contract for Remotion Studio versus Variants, one video runtime, navigation, timing and presenter semantics before changing controls.


### Out of Scope
- Rebuilding Remotion itself or adding another Jarvis viewer.
- Arbitrary per-slide playback cutoffs for video.
- Redesign of the left rail before the user's sketch.
- Unrelated Board/agent/audio infrastructure refactors.


## Dependencies
`01-independent-intention-and-code-audit`


## Implementation Steps
1. Define two distinct choices: native Remotion Studio for source/timeline authoring; Variants for history, preview, branch/select/compare/publish.
2. Reject parallel Jarvis-owned floating viewer; retain useful capabilities only once.
3. Specify primary play/pause, previous/next scene, global scrub, thumbnail click, fullscreen, end-of-show, manual presenter and video-continuous semantics.
4. Keep score/cue/sidekick roles independent from media clock while making time/frame position unambiguous.
5. Define control inventory: retain, remove, merge, overflow menu, with keyboard and accessibility requirements.
6. Defer final left-rail geometry pending user sketch; never block P0 playback on that sketch.


## Files Likely Touched
- `docs/presentation-studio.md`
- `docs/presentation-engine.md`
- `docs/remotion-runtime.md`
- Actual code owners identified by fresh Slice 01 mapping; don't edit stale guessed paths.


## Architecture Constraints
Single canonical Remotion runtime and timeline; preserve Core-owned variants, prefabs, score/cues, security, provenance, stable IDs and legacy content. No silent Slidecar fallback. Never mutate live user's Jarvis/Core during test. Only work on a fresh confirmed code branch.


## Automated Validation
- Write focused regression/unit/component tests for the Slice's goal and negative cases.
- Run tests under an isolated Core/Remotion/browser as relevant, capture exact command/HEAD, file/frame evidence and known baseline failures.
- Required QA: `qa-verification`.
- Regressions introduced here block approval; PM cannot archive them as external Issues.


## Acceptance Criteria
- Exactly one control contract and unambiguous default: play means continuous full composition with authored scene durations; no arbitrary per-slide timer.
- Product acceptance matrix covers native Studio, Variants, embedded Player, external display and presenter mode.


## Documentation Updates
Update canonical contract pages as the actual owner map requires, and append evidence with tested SHA. Review docs/05-documentation-levels.md; promote changed concepts to L2 contract and L3 executable conformance where applicable.


## Handoff Notes
- PM resolves current Workspace Task Type before dispatch; no invented assignment.
- Coding requires `/caveman` and `/coding-guideline`.
- Human validation:
- Human signs off the control hierarchy and two-view naming only after a clickable static prototype or UI inventory is available.