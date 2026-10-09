# Slice 08 - Board discoverability and derived provenance

## Goal
Expose an editable presentation source and derivative export lineage in existing Artifact/Board inspector and links.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Reuse WorkspaceService artifact links and active Board capture semantics.
- Index source and exports with traceable relationship source->snapshot->export, variant/revision and provenance.
- Avoid duplicate board storage or a second asset index; allow explicit cross-Board links.
- Expose links and open-by-id from Board manager even after restart.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
07-source-artifact-model-contract, 05-remotion-project-source-contract

## Implementation Steps
1. Reuse WorkspaceService artifact links and active Board capture semantics.
2. Index source and exports with traceable relationship source->snapshot->export, variant/revision and provenance.
3. Avoid duplicate board storage or a second asset index; allow explicit cross-Board links.
4. Expose links and open-by-id from Board manager even after restart.

## Files Likely Touched
- `docs/artifacts.md` (verify actual final-branch path before editing)
- `docs/boards.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Board switch/archived board, no open session, explicit link, missing parent, idempotency and crash reconciliation.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Board finds presentation and child export, link/unlink and reverse navigation work.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/artifacts.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/boards.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
