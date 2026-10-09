# Slice 00 — Project Manager readiness gate

## Goal  
Act as Project Manager and orchestrator. Execute this Slice personally; do not delegate it.

## Context  
The handoff was reconstructed after a failed initial Drive upload. Repository state may have moved since the planning snapshot.

## Canonical Concepts  
Canonical memory authority; derived memory intelligence; L0-L3 abstraction; retention classes; knowledge assets; memory UX.

## Scope  
### In Scope  
Perform an independent blind repository/context audit before reading handoff conclusions; reconcile drift; validate dependencies and Task Types; repair/split/reorder Slices if needed; reach one readiness state.  
### Out of Scope  
Product code changes.

## Dependencies  
None.

## Implementation Steps  
1. Blind-audit current Jarvis memory, Brain V2, settings/control center, tests and agent routing.  
2. Reconcile findings with this handoff.  
3. Resolve current Workspace Task Type vocabulary for every Slice.  
4. Record READY, CONTEXT_REWORK_REQUIRED, CONFLICT or HUMAN_DECISION_REQUIRED.  
5. Dispatch nothing below READY.  
6. Immediately before every later Slice, perform a targeted freshness check.

## Files Likely Touched  
Planning/handoff files only.

## Architecture Constraints  
Do not silently weaken locked decisions. Do not edit product code in Slice 00.

## Automated Validation  
Validate Slice IDs/dependencies, task types, canonical references and QA requirements.

## Acceptance Criteria  
READY is evidence-backed; all dispatch blockers are resolved or explicitly escalated.

## Documentation Updates  
Update task planning when repository drift requires it.

## Handoff Notes  
Every implementation Slice gets qa-verification; code gets code-review; runtime/UI gets runtime-validation; agent/memory injection gets agent-trace-analysis.  
