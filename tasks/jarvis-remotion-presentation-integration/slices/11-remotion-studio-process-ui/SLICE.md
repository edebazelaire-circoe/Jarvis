# Slice 11 - Optional Studio launch, hot preview server

## Goal
Make Remotion Studio a user-visible optional side window managed by Jarvis, not a terminal task or forced GUI editor.

## Context
This is a **follow-up** to the finished `jarvis-interactive-presentation-studio` branch. At planning snapshot some original Slices were still unfinished. The PM must reconcile changed code before dispatch. Avoid parallel implementation of original features.

## Canonical Concepts
Presentation Studio, Scene/Prefab, Remotion, Board/Artifact, EngineSelectionPolicy, Tool Brain and canonical project contracts as relevant.

## Scope
### In Scope
- Expose open/close/status/restart Studio, local URL only, port collision handling and host reuse.
- Bind Studio to current source module and read-only Board asset access; no arbitrary external scripts or ports.
- Manage HMR server on source updates with crash/reconnect status.
- Avoid leaking Node processes or orphan browser profiles on stop/restart.
### Out of Scope
Do not rewrite the active original task or bypass current canonical owners. No forced conversion of unrelated existing presentations.

## Dependencies
04-remotion-one-time-provisioning, 05-remotion-project-source-contract, 06-remotion-source-isolation

## Implementation Steps
1. Expose open/close/status/restart Studio, local URL only, port collision handling and host reuse.
2. Bind Studio to current source module and read-only Board asset access; no arbitrary external scripts or ports.
3. Manage HMR server on source updates with crash/reconnect status.
4. Avoid leaking Node processes or orphan browser profiles on stop/restart.

## Files Likely Touched
- `docs/OPERATIONS.md` (verify actual final-branch path before editing)
- Additional code/test paths to be selected only after blind audit and current contract reconciliation.

## Architecture Constraints
- One authoritative Core Presentation writer; reuse existing Scene/Prefab ownership and Board/Artifact link services.
- Remotion forced by default, user-only explicit Slidecar experiment; no silent fallback or unasked global prefab publication.
- Reject stale source revisions and unsafe/unresolved assets; keep editing source separate from render/export.
- Preserve the original branch until its implementer finishes.
- Do not let untrusted Remotion TSX/JS gain Jarvis filesystem/secret/tool privileges.

## Automated Validation
- Windows/local browser launch, close while edit, restart, port conflict, stale-source and crash cleanup.
- QA: `qa-verification` required; `code-review` for code, `runtime-validation` for runtime/GUI, `agent-trace-analysis` with real traces for agent/tools.
- A current-Slice regression is blocking and cannot be reclassified as an unrelated Issue.

## Acceptance Criteria
- Opening Studio displays the active presentation; closing it does not discard work.
- Verification evidence identifies test environment and exact branch commit; claims are not inferred from docs.

## Documentation Updates
- Update `docs/OPERATIONS.md` at its canonical section, with Level 2 contract/Level 3 conformance as applicable.
- Update handoff LOG and central evidence index, preserving source-of-truth ownership.

## Handoff Notes
Coding agents must follow `/caveman` and `/coding-guideline` where relevant. Frontend agents follow `/impeccable` with Claude if supported. Request Human validation only after maximum automated verification.
