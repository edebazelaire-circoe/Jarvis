# Slice 16 - MP4, stills, PDF and exact origin links

## Goal
Render on explicit request, preserve frozen source and register each export as a derivative Artifact with reliable lineage.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Support MP4 and still images first, assess PDF still/page pipeline explicitly; no claim editable output from flat export.
- Render from frozen, validated source plus pinned engine version, with deterministic config and progress/cancel.
- Create Artifact relations to logical source/version, variant and export settings; Board shows preview and origin.
- Recover failed/interrupted jobs; no partial final artifact.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
07-source-artifact-model-contract, 09-live-assets-and-freeze, 12-score-to-remotion-runtime

## Implementation Steps
1. Support MP4 and still images first, assess PDF still/page pipeline explicitly; no claim editable output from flat export.
2. Render from frozen, validated source plus pinned engine version, with deterministic config and progress/cancel.
3. Create Artifact relations to logical source/version, variant and export settings; Board shows preview and origin.
4. Recover failed/interrupted jobs; no partial final artifact.

## Files Likely Touched
- `docs/artifacts.md` (verify actual final-branch path before editing)
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Render actual media; verify file playback/dimensions/hash; lost process and disk full cases; attribution tests.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- User can export, find MP4 and trace precise editable origin without corrupting source.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/artifacts.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
