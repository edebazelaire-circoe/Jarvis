# Slice 12 - Safe native Remotion source edit and sync round trip


## Goal
Allow legitimate Remotion-native agent/project editing and HMR, instead of forcing all authoring through limited scene schemas.


## Context
Fix existing Jarvis Remotion Presentation Studio. Screenshot 1 depicts rejected floating viewer; screenshot 2 is Variants to retain. Read docs/06-screen-evidence.md and owner references.


## Canonical Concepts
Native Remotion Studio, Player, Variants, source/variant pins, score and cues; verify repository Level 2 and Level 3 contracts.


## Scope
### In Scope
Allow legitimate Remotion-native agent/project editing and HMR, instead of forcing all authoring through limited scene schemas.
### Out of Scope
- No new viewer or media engine, no arbitrary per-slide video limit.
- No guessed redesign for the left rail.
- No silent unsandboxed generated code execution or unrelated infrastructure rewrite.


## Dependencies
`01-independent-intention-and-code-audit`, `11-studio-variants-navigation`


## Implementation Steps
1. Audit current read-only Studio copy, edits/ backup behavior, export restrictions and hard-coded allowed imports.
2. Design a safe, explicit trusted authoring workspace with versioned TSX/asset sources and project-level dependencies; retain sandbox isolation for untrusted preview.
3. Provide auditable synchronization from authorized Studio edits into source/variant commits with conflict protection and rollback.
4. Make HMR fast without rendering MP4 on every edit; distinguish preview, publish and export.
5. Require an explicit risk boundary for unrestricted code/third-party dependencies rather than silently granting host filesystem/network access.
6. Preserve library pins, variants, Board references, artifacts and source provenance.


## Files Likely Touched
- docs/presentation-studio.md, docs/presentation-engine.md, docs/remotion-studio.md, docs/remotion-source.md
- Confirm actual owners and affected tests before editing. Agent-side playbooks: jarvis/runtime/presentation_playbooks.py.


## Architecture Constraints
Preserve Remotion as default, Slidecar only deliberate Human experiment, no silent fallback, one source of truth, stable Prefab pins, variant versions, Boards and Artifacts. Respect sandbox isolation and explicit trusted Studio approval. No changes to live Core/test user data.


## Automated Validation
- Focused machine tests and isolated real-runtime/real-browser checks, with exact SHA, sample sources, frame captures, durations and QA evidence.
- qa-verification and code-review; runtime-validation where applicable; agent-trace-analysis with real agent traces required.
- Current-Slice regressions block PM signoff; do not defer to Issues.


## Acceptance Criteria
- Changes authored in Studio persist via an explicit supported save/publish path, survive restart and appear in Variants.
- No silent overwrite of authored files by the old read-only sync path.


## Documentation Updates
Update canonical contracts, execution guide, source ownership and conformance tests.


## Handoff Notes
- PM resolves valid current Workspace Task Type, no invented assignment.
- Coding requires /caveman and /coding-guideline.
- Human validation: Confirm expected trust/approval UX if product cannot safely enable unsandboxed editing by default.