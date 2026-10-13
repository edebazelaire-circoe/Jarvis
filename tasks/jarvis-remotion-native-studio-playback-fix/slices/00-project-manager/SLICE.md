# Slice 00 - Readiness, independent audit and execution control


## Goal
Establish a factual implementation starting point; never dispatch into unknown or conflicting product state.


## Context
This is a fix of an existing Jarvis Presentation Studio + Remotion implementation. User screenshot 1 is an unwanted floating presentation viewer to retire; screenshot 2 is the Variants base to preserve but simplify. Refer to `../../docs/06-screen-evidence.md` and latest inspected implementation. This Slice does not authorize an additional viewer or media engine.


## Canonical Concepts
Remotion composition, native Remotion Studio, Variants, source and variant pins, playback clock, score/cues where relevant. Read canonical references rather than copying their contracts.


## Scope
### In Scope
Establish a factual implementation starting point; never dispatch into unknown or conflicting product state.


### Out of Scope
- Rebuilding Remotion itself or adding another Jarvis viewer.
- Arbitrary per-slide playback cutoffs for video.
- Redesign of the left rail before the user's sketch.
- Unrelated Board/agent/audio infrastructure refactors.


## Dependencies
None. Execute this as the Project Manager; do not delegate.


## Implementation Steps
1. Blindly audit current repository HEAD and running/queued related handoffs before reading the proposed conclusions.
2. Check open branches, recent commits, baseline failures, existing task overlap and current Workspace Task Type vocabulary.
3. Reconcile evidence with this handoff and classify readiness as READY, CONTEXT_REWORK_REQUIRED, CONFLICT or HUMAN_DECISION_REQUIRED.
4. For READY, confirm Slice order, identifiers, intended architecture and measurable release gates; otherwise stop and repair planning or escalate.
5. Before dispatching each implementation Slice, re-check fresh HEAD and affected contracts; avoid simultaneous edits of shared modules.


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
- Readiness report, HEAD and baseline evidence; dependency and conflict matrix; an agent/task-type assignment plan.
- No product code edit or work-agent dispatch during Slice 00.


## Documentation Updates
Update canonical contract pages as the actual owner map requires, and append evidence with tested SHA. Review docs/05-documentation-levels.md; promote changed concepts to L2 contract and L3 executable conformance where applicable.


## Handoff Notes
- PM resolves current Workspace Task Type before dispatch; no invented assignment.
- Coding requires `/caveman` and `/coding-guideline`.
- Human validation:
- Human approval only when a real conflict, missing permission or irreversible decision is discovered.


## Readiness protocol (mandatory)
1. **Blind audit:** first inspect repository, user evidence, tasks and external dependencies without reading this handoff's conclusions.
2. **Reconcile:** inspect handoff analysis and correct outdated assumptions, code paths, dependencies, Slice order, or acceptance targets.
3. **Classify exactly one:** `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`. Under any status other than READY, do not dispatch implementation.
4. **Task repair permitted:** split, add, reorder or supersede planning Slices; PM does not modify product code, delegated Work Agents do.
5. **Freshness before every dispatch:** inspect new HEAD, changed files, other agents and prerequisites; resolve Workspace Task Type from current vocabulary.
6. **QA ownership:** collect independent `qa-verification` for every implemented Slice, `code-review` for code, `runtime-validation` for runtime/UI and `agent-trace-analysis` with real traces for agent changes. PM decides approval/rework/new Slice/Issue/Human escalation. Never defer a new regression.
7. **Human checks after machine gates only**; record physical constraints or missing permissions honestly.