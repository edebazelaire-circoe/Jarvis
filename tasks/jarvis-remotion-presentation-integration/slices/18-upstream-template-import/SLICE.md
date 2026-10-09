# Slice 18 - External Remotion and Opus assets with provenance

## Goal
Import selected external Remotion/Opus templates safely while recording exact provenance, license and dependency constraints.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Fetch original source only from allowlisted verified origins, not MP4 preview as editable code.
- Record URL, upstream ids/versions/hashes, license, dependencies, import date and changes; do not conflate Remotion license with template license.
- Scope each imported template to current presentation unless user explicitly promotes it.
- Reject incompatible executable deps or offer narrow audited adapter.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
17-prefab-shop-semantic-catalog, 06-remotion-source-isolation, 09-live-assets-and-freeze

## Implementation Steps
1. Fetch original source only from allowlisted verified origins, not MP4 preview as editable code.
2. Record URL, upstream ids/versions/hashes, license, dependencies, import date and changes; do not conflate Remotion license with template license.
3. Scope each imported template to current presentation unless user explicitly promotes it.
4. Reject incompatible executable deps or offer narrow audited adapter.

## Files Likely Touched
- `docs/prefabs.md` (verify actual final-branch path before editing)
- `docs/SECURITY.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Archive integrity, unsafe extraction, missing dependency, license metadata, import without publishing.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Imported source can preview in Remotion or report exact incompatibility; no hidden unlicensed asset.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/prefabs.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/SECURITY.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.


## Plan amendment after Slice 01 (final-head audit, main de7b9c59, 2026-10-09)

Evidence: `docs/06-branch-compliance-audit.md` section "Final-head audit" (R-numbers, risks, redundancy table).

- Needs the licence/upstream fields of Slice 17 and the Slice 06 isolation. No existing importer to reuse (R19). Keep scoped-to-presentation by default; the shared-library publication path is the existing explicit promotion (R11).
