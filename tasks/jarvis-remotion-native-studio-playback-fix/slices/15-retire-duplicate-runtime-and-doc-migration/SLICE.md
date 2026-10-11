# Slice 15 - Code cleanup and durable documentation migration


## Goal
Remove obsolete alternate owners and document new canonical architecture without damaging existing presentation data.


## Context
Jarvis Presentation Studio and Remotion repair. Screenshot 1 is the unwanted floating viewer; screenshot 2 is the Variants reference. See docs/06-screen-evidence.md.


## Canonical Concepts
Native Remotion, one Player timeline, Variants, source version pins, score/cues, existing Boards/Prefabs/Artifacts.


## Scope
### In Scope
Remove obsolete alternate owners and document new canonical architecture without damaging existing presentation data.
### Out of Scope
- No duplicate custom player or studio.
- No new left rail design without sketch.
- No unapproved modification of the live user's Core or data.


## Dependencies
`06-player-lifecycle-and-transport`, `07-presentation-score-voice-compatibility`, `09-remove-legacy-floating-viewer`, `10-variants-interface-control-audit`, `11-studio-variants-navigation`, `12-native-authoring-workspace-roundtrip`


## Implementation Steps
1. Remove old transport state and styles only after destination routes and compatibility tests pass.
2. Update canonical docs, contracts, symbols, diagrams, operator steps and MCP descriptions; record deprecations.
3. Migrate saved view state, playlist ownership, variant metadata and import/export path; ensure old presentations still open.
4. Review licensing implications of native Remotion use and preserve explicit decision gate where required.
5. Add rollback and feature flag plan only for migration safety, never keep parallel UI as a second product.


## Files Likely Touched
Canonical docs/presentation-studio.md, docs/presentation-engine.md, docs/remotion-runtime.md, docs/remotion-studio.md; actual code owners from fresh HEAD.


## Architecture Constraints
Remotion is default; Slidecar only explicit Human experimental path, no fallback. Preserve source, data, version pins and security guarantees. Use isolated test environment and migration/rollback.


## Automated Validation
- Full regression, real-browser playback, visual contact sheets, source integrity, performance and Human handoff evidence as relevant.
- qa-verification mandatory, code-review for code, runtime-validation for runtime/UX, agent-trace-analysis with real traces for agent changes.
- PM cannot defer current-Slice regressions into Issues.


## Acceptance Criteria
- No conflicting ownership or orphaned controls remain after deletion.
- Historical presentations and variants remain readable, reversible migration is documented.


## Documentation Updates
Update authoritative contracts, tested SHA, migration and release report. Keep Level 2 semantics and Level 3 conformance synchronized.


## Handoff Notes
- PM resolves current Workspace Task Type; no invented defaults.
- Coding requires /caveman and /coding-guideline.
- Human validation: No separate Human check; report genuine blockers to PM.