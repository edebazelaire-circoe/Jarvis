# Slice 19 - Explicit prefab save and version trial branching

## Goal
Allow explicit promotion and safe version upgrades through new variants without forcing update of existing presentations.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- User alone requests save as Component, Composition, Page or Presentation prefab; extract reusable parameters, source and dependencies.
- Keep pinned versions; notify newer version, request permission, trial it in new variant, compare and adopt explicitly.
- Preserve provenance/license/compatibility; no auto promotion, no overwrite, no silent rebinding.
- Support saving a full presentation as a template without individually publishing all its constituent scenes.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
17-prefab-shop-semantic-catalog, 18-upstream-template-import, 13-remotion-controls-bridge

## Implementation Steps
1. User alone requests save as Component, Composition, Page or Presentation prefab; extract reusable parameters, source and dependencies.
2. Keep pinned versions; notify newer version, request permission, trial it in new variant, compare and adopt explicitly.
3. Preserve provenance/license/compatibility; no auto promotion, no overwrite, no silent rebinding.
4. Support saving a full presentation as a template without individually publishing all its constituent scenes.

## Files Likely Touched
- `docs/prefabs.md` (verify actual final-branch path before editing)
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Publish/decline/upgrade-in-variant/rollback; pinned old version and upstream unavailable scenarios.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Explicit save creates one library item of requested granularity; existing variants stay unchanged.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/prefabs.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
