# Slice 15 - High-quality generation with storyboard and DA

## Goal
Adapt serious, exploratory and one-shot presentation workflows to Remotion sources without losing existing score and DA expectations.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Reuse authoring brief and quality gate, fetch Board/project context before asking user for missing fields.
- Assemble score/script, DA, scene modules, controls, motions, transitions, assets as one coherent first draft.
- Allow exploratory divergent directions/variants without over-interviewing.
- Use upstream templates as OPTIONAL inspirations only if selected/provenance confirmed.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
09-live-assets-and-freeze, 11-remotion-studio-process-ui, 13-remotion-controls-bridge

## Implementation Steps
1. Reuse authoring brief and quality gate, fetch Board/project context before asking user for missing fields.
2. Assemble score/script, DA, scene modules, controls, motions, transitions, assets as one coherent first draft.
3. Allow exploratory divergent directions/variants without over-interviewing.
4. Use upstream templates as OPTIONAL inspirations only if selected/provenance confirmed.

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
- Real LLM traces, evidence-based context lookup, no invented figures/assets, first-draft test and user approval.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Serious deck opens near-presentable with its score, DA, timing and editable parameters; exploratory can remain lighter.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/presentation-studio.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
