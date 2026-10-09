# Slice 14 - Subagent structural edits and safe hot reload

## Goal
Support large verbal edits by delegating a scoped source edit job, validating it and showing resulting Remotion HMR.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Re-use existing Core edit/revision/undo/hot reload semantics, adapt to TSX and Remotion/JS module bundling.
- Use @remotion/codemods/sdk only behind versioned optional adapter after proof; agents may edit source when controls insufficient.
- Serialize concurrent edits; preview, validate, commit or rollback; preserve score/scene when compatible.
- Emit typed error and do not switch to Slidecar on build failure.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
06-remotion-source-isolation, 11-remotion-studio-process-ui, 13-remotion-controls-bridge

## Implementation Steps
1. Re-use existing Core edit/revision/undo/hot reload semantics, adapt to TSX and Remotion/JS module bundling.
2. Use @remotion/codemods/sdk only behind versioned optional adapter after proof; agents may edit source when controls insufficient.
3. Serialize concurrent edits; preview, validate, commit or rollback; preserve score/scene when compatible.
4. Emit typed error and do not switch to Slidecar on build failure.

## Files Likely Touched
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Real HMR build, broken TypeScript, concurrent edits, rollback, invalid frame count, daemon restart.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Subagent alters one source scene, stage refreshes safely, failure rolls back without damaging other scenes.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
