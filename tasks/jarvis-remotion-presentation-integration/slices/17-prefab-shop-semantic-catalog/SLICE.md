# Slice 17 - Unified reusable components and marketplace UX

## Goal
Extend Prefab library metadata/catalog and user-facing browsing by semantic type and engine/technology capabilities.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Keep Prefab as broad library identity; categories Component/Composition/Page/Presentation/Asset universal across engines.
- Show visual preview/summary/type in results; technical stack, version, editable parameter contract, compatibility and deps in detail drawer.
- No per-renderer vocabulary translation, no automatic compatibility promise.
- Retain canonical immutable versioning and existing base-prefab safeguards.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
01-final-branch-conformance, 02-engine-and-compatibility-contract

## Implementation Steps
1. Keep Prefab as broad library identity; categories Component/Composition/Page/Presentation/Asset universal across engines.
2. Show visual preview/summary/type in results; technical stack, version, editable parameter contract, compatibility and deps in detail drawer.
3. No per-renderer vocabulary translation, no automatic compatibility promise.
4. Retain canonical immutable versioning and existing base-prefab safeguards.

## Files Likely Touched
- `docs/prefabs.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Search/filter/preview/details, no missing controls exposure, large catalog performance, accessible UX.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Catalogue shows HTML and Remotion categories clearly; user can filter tech and engine capabilities.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/prefabs.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
