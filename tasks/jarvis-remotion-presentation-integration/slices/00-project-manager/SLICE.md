# Slice 00 - Completion/readiness and orchestration gate

## Goal
Run the independent fresh audit yourself, gate execution until the original agent has finished, repair this plan, and resolve Workspace Task Types.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Read current branch/main/docs/tests independently before the pre-audit matrix.
- Confirm original task actually completed (including its 15 and 18-22, unless replaced) and stable SHA/branch ownership.
- Reconcile evidence against handoff; resolve divergent main commits and exact head.
- Resolve real Task Type per Slice from workspace, no invented values.
- Declare exactly READY / CONTEXT_REWORK_REQUIRED / CONFLICT / HUMAN_DECISION_REQUIRED.
- Dispatch only when READY; targeted freshness check before every Slice.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
None

## Implementation Steps
1. Read current branch/main/docs/tests independently before the pre-audit matrix.
2. Confirm original task actually completed (including its 15 and 18-22, unless replaced) and stable SHA/branch ownership.
3. Reconcile evidence against handoff; resolve divergent main commits and exact head.
4. Resolve real Task Type per Slice from workspace, no invented values.
5. Declare exactly READY / CONTEXT_REWORK_REQUIRED / CONFLICT / HUMAN_DECISION_REQUIRED.
6. Dispatch only when READY; targeted freshness check before every Slice.

## Files Likely Touched
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Compare live GitHub branch and main refs; enumerate original outstanding Slices and QA reports; verify no project overlap.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Written readiness state with evidence, no code changed in Slice 00; no premature dispatch.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
**You are the Project Manager** and orchestrator for this handoff. Execute this Slice YOURSELF and DO NOT delegate it. Blind-audit the repository and original work first, then reconcile the planning documents. Announce exactly one readiness state. No dispatch below READY. Repair scope/slicing/dependencies if necessary. Resolve Task Types from actual current workspace vocabulary. Freshness-check before each Slice dispatch.
