# Slice 00 — Project Manager readiness gate

## Goal
You are the Project Manager and orchestrator. Execute this Slice yourself; do not delegate it. Reach a readiness state before implementation dispatch.

## Context
Handoff is based on the 2026-09-16 design session and repo review of main SHA `7ed67bb09f4f9e1d63df793a23777904f6c63d13`.

## Canonical Concepts
Core work truth stays authoritative; Scene is persistent projection; runtime direct authority is narrow; main brain owns semantic composition; browser owns rendering/reflex; completed work remains until user disposition; brain has no archive tool.

## Scope
### In Scope
Perform an independent blind repository/context audit before reading this handoff's documentation-level conclusions; inspect current HEAD, architecture, Control Center, agent/work/event/MCP/persistence/tests; resolve the exact Workspace Task Type vocabulary; reconcile audit with handoff; repair stale planning; emit `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`; define a targeted freshness check before every Slice dispatch.

### Out of Scope
Product code changes; invented Task Types; changing locked user decisions merely to fit code.

## Dependencies
None.

## Implementation Steps
1. Record current HEAD and runtime topology.
2. Blind-audit relevant contracts/tests.
3. Resolve valid Task Types.
4. Reconcile with handoff.
5. Repair/split/reorder planning if needed.
6. Record readiness evidence in LOG.
7. Run targeted freshness check before each later dispatch.

## Files Likely Touched
Handoff planning only.

## Architecture Constraints
No implementation dispatch below READY; PM does not implement product code.

## Automated Validation
Validate Slice IDs/dependencies, Task Types, required skills/routing, no brain archive tool, and current repository compatibility.

## Acceptance Criteria
Blind audit precedes reconciliation; HEAD recorded; Task Types resolved or explicit block; readiness state recorded; no dispatch below READY.

## Documentation Updates
Update LOG and handoff only when audit proves staleness.

## Handoff Notes
Every implemented Slice gets qa-verification; code adds code-review; user/runtime adds runtime-validation; agent/tool/MCP adds real agent-trace-analysis.
