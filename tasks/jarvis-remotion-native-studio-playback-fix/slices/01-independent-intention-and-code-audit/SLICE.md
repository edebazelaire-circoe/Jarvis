# Slice 01 - Independent intent versus implementation audit


## Goal
Inventory every conflicting viewer/control/timeline and document the gap between both screenshots, user intent and actual state.


## Context
This is a fix of an existing Jarvis Presentation Studio + Remotion implementation. User screenshot 1 is an unwanted floating presentation viewer to retire; screenshot 2 is the Variants base to preserve but simplify. Refer to `../../docs/06-screen-evidence.md` and latest inspected implementation. This Slice does not authorize an additional viewer or media engine.


## Canonical Concepts
Remotion composition, native Remotion Studio, Variants, source and variant pins, playback clock, score/cues where relevant. Read canonical references rather than copying their contracts.


## Scope
### In Scope
Inventory every conflicting viewer/control/timeline and document the gap between both screenshots, user intent and actual state.


### Out of Scope
- Rebuilding Remotion itself or adding another Jarvis viewer.
- Arbitrary per-slide playback cutoffs for video.
- Redesign of the left rail before the user's sketch.
- Unrelated Board/agent/audio infrastructure refactors.


## Dependencies
`00-project-manager`


## Implementation Steps
1. Inspect the two evidence screenshots plus the reconstructed feedback transcript.
2. Map old floating visualizer, presentation window, Variant Explorer, Control Center band, Remotion stage and native Remotion Studio to actual modules/routes.
3. Inspect roles, score/cues, presentation library, variant graph, source/asset ownership, read-only Studio sync and editable source APIs.
4. Collect baseline runtime test results without affecting the live Jarvis Core; distinguish reported pass from personally rerun results.
5. Produce remove/keep/merge/refactor table with code owners, test owners and data migration impact.


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
- Every visible control and time indicator in the screenshots has a code owner or is explicitly unknown.
- No claim that a browser bug was reproduced unless a live or isolated browser actually reproduced it.


## Documentation Updates
Update canonical contract pages as the actual owner map requires, and append evidence with tested SHA. Review docs/05-documentation-levels.md; promote changed concepts to L2 contract and L3 executable conformance where applicable.


## Handoff Notes
- PM resolves current Workspace Task Type before dispatch; no invented assignment.
- Coding requires `/caveman` and `/coding-guideline`.
- Human validation:
- No separate Human check assigned; any newly discovered physical decision should be escalated to PM.