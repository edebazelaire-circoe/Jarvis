# Slice 09 — End-to-end validation, migration and rollout

## Goal
Prove the complete workspace-memory system across restart, Board switching, historical inspection, MCP, delegated agents and UI, then finalize migration/docs/rollout.

## Context
This feature crosses persistence, agent context, MCP and UI; isolated unit success is insufficient.

## Canonical Concepts
All prior task concepts.

## Scope
### In Scope
- Realistic multi-Board/multi-Session fixture/e2e scenario.
- A/B/A Board switching with different memory and artifacts.
- Restart/resume according to prerequisite Session semantics.
- Historical inspection of inactive Board while current Board remains foreground.
- Main Brain MCP management actions.
- Delegated-agent historical inspection trace.
- Deep manager and quick browser against the same state.
- Migration from pre-feature Board rows/data.
- Context-budget and performance checks for large histories.
- Final canonical docs and operator notes.

### Out of Scope
- Meeting/presentation live behavior.
- New capture features.

## Dependencies
Slices 03, 06, 07, 08.

## Implementation Steps
1. Build deterministic e2e scenario with at least three Boards and historical Session data.
2. Exercise memory file writes, artifacts/provenance and Board switches.
3. Restart supported components and verify continuity.
4. Run main Brain and delegated-agent traces.
5. Exercise UI manager/browser with the same data.
6. Run full affected regression suites and context-budget gates.
7. Finalize docs/migration notes and remove temporary compatibility code that would duplicate tools.

## Files Likely Touched
Integration/E2E tests, fixtures, canonical docs, migration/release notes.

## Architecture Constraints
No assertion of continuity or sub-agent access without real runtime/trace evidence.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation` + `agent-trace-analysis`. Full relevant Board/Session/MCP/Control Center regression suites.

## Acceptance Criteria
A single evidence-backed run demonstrates durable Board memory, clean A/B/A context boundaries, safe historical inspection, correct artifact links, UI/MCP parity and delegated-agent access with no foreground/speech-authority regression.

## Documentation Updates
Finalize `docs/boards.md`, local-data docs, SessionContext integration docs, MCP tool contract, Control Center/operator docs.

## Handoff Notes
Any regression introduced by this task is blocking. Do not park it in Issues to declare success.
