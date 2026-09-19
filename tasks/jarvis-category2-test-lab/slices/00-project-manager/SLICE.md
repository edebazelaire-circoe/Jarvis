# Slice 00 — Project Manager readiness and orchestration gate

## Goal
Act as the Project Manager and orchestrator. Execute this Slice yourself; do not delegate it. Perform an independent blind repository/context audit before reading the handoff documentation-level conclusions, reconcile the audit with this handoff, resolve valid Workspace Task Types, establish baseline QA commands, and declare one readiness state.

## Context
This task was planned against `main@c33207281a5b6a10a6630b8914f19855ea096473`. Slice 00 and the pre-dispatch freshness check are authoritative for live file locations and parallel changes.

## Canonical Concepts
- Category 2 Test Lab
- DiagnosticSpec / ProfileSpec / Scenario / TestRun
- DiagnosticBundle
- Existing RuntimeJournal, speech delivery telemetry, async conversation harness, and Control Center contracts where relevant

## Scope
### In Scope
1. Audit live `main`, git status/worktrees, relevant active tasks/branches, Test/Voice/Control Center/runtime docs and tests.
2. Reconcile active observability/transcript and voice-arbitration work; identify conflict zones.
3. Resolve every later Slice to a valid current Workspace Task Type; do not invent one.
4. Establish baseline/narrow/full verification commands.
5. Declare exactly one of `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`.
6. Dispatch nothing below `READY`.
7. Before every later dispatch, run a targeted freshness check.
8. You may split/reorder/add/supersede planning Slices when evidence requires it, but do not edit product code in Slice 00.

### Out of Scope
- Autonomous LLM reasoning inside Test Lab.
- Unrelated product behavior changes.
- MCP as a required dependency.

## Dependencies
None.

## Implementation Steps
1. Audit live `main`, git status/worktrees, relevant active tasks/branches, Test/Voice/Control Center/runtime docs and tests.
2. Reconcile active observability/transcript and voice-arbitration work; identify conflict zones.
3. Resolve every later Slice to a valid current Workspace Task Type; do not invent one.
4. Establish baseline/narrow/full verification commands.
5. Declare exactly one of `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`.
6. Dispatch nothing below `READY`.
7. Before every later dispatch, run a targeted freshness check.
8. You may split/reorder/add/supersede planning Slices when evidence requires it, but do not edit product code in Slice 00.

## Files Likely Touched
Resolve against the live repository during the freshness check. Likely areas include `jarvis/testlab/` (new), `jarvis/runtime/`, `jarvis/audio/`, `tests/integration/`, `tests/unit/`, and Control Center assets/routes as appropriate.

## Architecture Constraints
- Test Lab remains deterministic and contains no embedded debugging intelligence.
- Do not persist hidden chain-of-thought.
- Do not make Category 2 live/hardware diagnostics part of every normal CI run.

## Automated Validation
- Add narrow unit/contract/integration coverage for this Slice.
- Run repository baseline/release verification selected by Slice 00 where reasonable.
- Prove failure paths, cancellation/cleanup, and serialization compatibility relevant to this Slice.

## Acceptance Criteria
- Slice behavior is covered by automated tests.
- Public contracts are documented/versioned where introduced.
- No regression in existing deterministic conversation/voice tests.
- Runtime/user-visible behavior has concrete evidence when applicable.

## Documentation Updates
Update canonical repository documentation for every new public Test Lab concept or contract introduced by this Slice.

## Handoff Notes

Mandatory QA doctrine:
- Every implemented Slice gets `qa-verification`.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts/tools/routing/modules/runtime add `agent-trace-analysis` with real trace evidence.
- Regressions caused by the Slice are blocking.
- Human validation never substitutes for maximum reasonable machine QA.

