# Slice 00 — Project Manager readiness gate

## Goal
Act as Project Manager and orchestrator for this handoff. Execute this Slice yourself; do not delegate it. Establish whether the repository and prerequisite contracts are ready before any product-code Slice is dispatched.

## Context
This task depends on the earlier `jarvis-session-context-recording-runtime` design, while the planning snapshot of `main` still shows old `core_restart` Session semantics. The first job is to discover the real execution baseline, not to trust this handoff blindly.

## Canonical Concepts
Boards (`docs/boards.md`), Session/SessionContext prerequisite contract, generic Artifact registry, MCP catalog/tool contract.

## Scope
### In Scope
- Blind repository/context audit before reading this handoff's documentation-level conclusions.
- Determine whether the prerequisite Session/Context/Artifact task has landed, partially landed or not landed.
- Reconcile actual code with this handoff and record one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.
- Resolve the current Workspace Task Type vocabulary and assign valid Task Types to implementation Slices.
- Repair task planning if main has moved: enrich/split/reorder/supersede/add Slices as needed.
- Verify current Control Center Board UI, routes, persistence, MCP launch/config and delegated-agent MCP inheritance/access.
- Establish exact canonical files/services that own Board memory, SessionContext integration and artifact associations.

### Out of Scope
- Product code changes.
- Guessing missing contracts.

## Dependencies
None.

## Implementation Steps
1. Audit repository and relevant project/task evidence independently.
2. Only after the blind audit, read the task docs and reconcile differences.
3. Inspect prior handoff/implementation status.
4. Resolve valid Task Types; leave no implementation Slice with an invented/default type.
5. Check Slice dependency DAG and human-check IDs.
6. Return exactly one readiness state with evidence.
7. Dispatch nothing below `READY`.
8. Immediately before every later Slice dispatch, perform a targeted freshness check.

## Files Likely Touched
Task handoff files only if planning repair is required. No product code.

## Architecture Constraints
The PM may change planning, not product code. It must not silently collapse Board memory and SessionContext into one concept.

## Automated Validation
Planning consistency audit. No product QA run required until implementation begins.

## Acceptance Criteria
- Real baseline and prerequisite status are documented.
- Task Types are valid and resolved.
- Readiness state is explicit.
- No conflicting Session/Board/Context contract remains unresolved.
- Every Slice still maps to user intent and current code.

## Documentation Updates
Amend handoff docs only when stale relative to actual main.

## Handoff Notes
All later Slices require the QA doctrine in README/docs/04. Every coding Slice loads `/caveman` and `/coding-guideline`; frontend Slices also load `/impeccable`.
