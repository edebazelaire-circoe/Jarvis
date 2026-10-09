# Slice 02 - Engine semantics and forced-default policy

## Goal
Define minimal shared PresentationEngine interface, capabilities and refusal semantics without disturbing the current Slidecar engine.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Specify rendering vs authoring vs motion vs export capabilities per engine and native/adapter/unsupported statuses.
- Keep Scene/Prefab/Cue/DA/Variant/Core ownership unchanged.
- Make Remotion forced default and no autonomous agent choice or fallback a validated policy.
- Define typed engine unavailable/unsupported errors and manifest engine metadata.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
01-final-branch-conformance

## Implementation Steps
1. Specify rendering vs authoring vs motion vs export capabilities per engine and native/adapter/unsupported statuses.
2. Keep Scene/Prefab/Cue/DA/Variant/Core ownership unchanged.
3. Make Remotion forced default and no autonomous agent choice or fallback a validated policy.
4. Define typed engine unavailable/unsupported errors and manifest engine metadata.

## Files Likely Touched
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- `docs/prefabs.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Schema/contract tests; fail when forbidden fallback path or ambiguous engine selected.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Published Level 2 contract and conformance stubs; Slidecar remains readable/experimental.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/prefabs.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
