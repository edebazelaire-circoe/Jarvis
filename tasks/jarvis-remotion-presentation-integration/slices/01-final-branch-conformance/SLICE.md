# Slice 01 - Full branch conformance and gap proof

## Goal
Produce a code-level compliance matrix for the finished existing branch and reconcile old and new requirements without guesswork.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Inspect current finished Slices/tests/routes/UI against each original requirement and later Remotion/prefab/artifact decisions.
- Record exact file/line evidence, what is tested, what is unverified and what is missing.
- Run codebase tests and compare known red baseline; map post-branch main divergence/conflicts.
- Determine which planned Remotion Slices are redundant and delete/reorder plan entries accordingly.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
00-project-manager

## Implementation Steps
1. Inspect current finished Slices/tests/routes/UI against each original requirement and later Remotion/prefab/artifact decisions.
2. Record exact file/line evidence, what is tested, what is unverified and what is missing.
3. Run codebase tests and compare known red baseline; map post-branch main divergence/conflicts.
4. Determine which planned Remotion Slices are redundant and delete/reorder plan entries accordingly.

## Files Likely Touched
- `docs/presentation-studio.md` (verify actual final-branch path before editing)
- `old task LOG and TODO` (verify actual final-branch path before editing)
- `docs/06-branch-compliance-audit.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Full unit/regression suites and source contract tests on the final head; test comparison to current main.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Evidence-backed matrix, integration risks, measured baseline and resolved handoff dependencies.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `old task LOG and TODO` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/06-branch-compliance-audit.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Read completed original `slices/TODO.md`, `LOG.md` and all actual code, then compare with the preaudit only after independent observation; no assumed QA success from log alone.
