# Slice 16 - Integrated regression, comparison and sign-off


## Goal
Prove the fix in an isolated machine run then escalate only genuinely physical/creative checks to a person.


## Context
Jarvis Presentation Studio and Remotion repair. Screenshot 1 is the unwanted floating viewer; screenshot 2 is the Variants reference. See docs/06-screen-evidence.md.


## Canonical Concepts
Native Remotion, one Player timeline, Variants, source version pins, score/cues, existing Boards/Prefabs/Artifacts.


## Scope
### In Scope
Prove the fix in an isolated machine run then escalate only genuinely physical/creative checks to a person.
### Out of Scope
- No duplicate custom player or studio.
- No new left rail design without sketch.
- No unapproved modification of the live user's Core or data.


## Dependencies
`07-presentation-score-voice-compatibility`, `08-media-fullscreen-stability`, `10-variants-interface-control-audit`, `11-studio-variants-navigation`, `12-native-authoring-workspace-roundtrip`, `13-claude-native-generation-parity`, `14-visual-quality-and-media-gates`, `15-retire-duplicate-runtime-and-doc-migration`


## Implementation Steps
1. Run focused and wide test suites against fresh HEAD, compare to initial baseline and classify inherited failures.
2. Run native Studio open-edit-sync-preview, Variants preview, continuous Player, manual presenter, cues, fullscreen, audio and export.
3. Run scripted resilience scenarios: 9 scenes, 30s scene, rapid seek, backward jump, Core restart, lost connection, cold/warm caches and various fps.
4. Measure transition discontinuity and document failed/known limits instead of waiving.
5. Obtain Human review of UI, actual video, blinded Claude parity and dual-monitor audio; record any Remotion licence decision.
6. Produce final implementation report with before/after screenshots, code paths retired, source/variant preservation and rollback instructions.


## Files Likely Touched
Canonical docs/presentation-studio.md, docs/presentation-engine.md, docs/remotion-runtime.md, docs/remotion-studio.md; actual code owners from fresh HEAD.


## Architecture Constraints
Remotion is default; Slidecar only explicit Human experimental path, no fallback. Preserve source, data, version pins and security guarantees. Use isolated test environment and migration/rollback.


## Automated Validation
- Full regression, real-browser playback, visual contact sheets, source integrity, performance and Human handoff evidence as relevant.
- qa-verification mandatory, code-review for code, runtime-validation for runtime/UX, agent-trace-analysis with real traces for agent changes.
- PM cannot defer current-Slice regressions into Issues.


## Acceptance Criteria
- No new unclassified regressions, no P0 visual/transition/playback defects, exact manual and continuous contracts pass.
- Live Human approval must be recorded separately from automated evidence.


## Documentation Updates
Update authoritative contracts, tested SHA, migration and release report. Keep Level 2 semantics and Level 3 conformance synchronized.


## Handoff Notes
- PM resolves current Workspace Task Type; no invented defaults.
- This Slice primarily orchestrates release and QA; coding sub-work requires /caveman and /coding-guideline.
- Human validation: Approve on target machine with actual display/audio and two comparison presentations.