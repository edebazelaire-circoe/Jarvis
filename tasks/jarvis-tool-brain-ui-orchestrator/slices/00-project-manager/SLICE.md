# Slice 00 — Project Manager Readiness Gate

## Goal

Act as the Project Manager and orchestrator for this handoff. Determine whether the current Jarvis repository and related handoffs are ready for Tool Brain implementation before delegating any product-code Slice.

## Context

The design is well specified at product level, but the task creator could not access the live GitHub repository. Durable Drive handoffs provide strong architecture evidence but may be stale. Repository reality is authoritative.

## Canonical Concepts

Tool Brain, Jarvis Brain, scene/runtime ownership, Board/Session, MCP catalog, conversation event log/timeline, speech/Mouth progress, prefab/scene objects.

## Scope

### In Scope

- Perform an independent blind repository/context audit **before reading this handoff's documentation-level conclusions**.
- Locate current scene/UI tool APIs, Board runtime, speech/Mouth pipeline, response buffering/chunking, conversation events/timeline, MCP catalog/tool metadata and browser/window control primitives.
- Inspect pending/current Jarvis handoffs that overlap this scope, especially scene-window-prefab and session-context work.
- Reconcile repository reality with this handoff.
- Resolve valid Workspace Task Types for every Slice.
- Split, reorder, supersede, add or enrich Slices if live evidence requires it.
- Produce one readiness state: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, or `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- Editing product code.
- Implementing another Slice on behalf of a Work Agent.

## Dependencies

None.

## Implementation Steps

1. Audit the live repository without relying on `docs/05-documentation-levels.md` first.
2. Map canonical ownership and state flows for scene, Board, speech, conversation events and MCP tools.
3. Identify whether any existing component already resembles a decision/tool brain or action queue.
4. Locate the existing live transcript/debug UI and its event contracts.
5. Inspect the current status of `jarvis-scene-window-prefab-foundation` and reconcile scene API assumptions.
6. Reconcile the audit with all task docs/Slices.
7. Resolve each Slice's Task Type from the current Workspace vocabulary.
8. Record readiness state and planning corrections.
9. Require a targeted freshness check immediately before each later Slice dispatch.

## Files Likely Touched

Handoff planning/docs only. No product code.

## Architecture Constraints

Never create a second scene contract, Board state machine, MCP catalog, conversation-event store, transcript system or speech-progress truth when a canonical one exists.

## Automated Validation

- Verify every Slice dependency resolves to a Slice ID in this task.
- Verify Task Types resolve to existing Workspace values.
- Verify cross-handoff ownership boundaries are explicit.
- Verify no implementation Slice is dispatched below `READY`.

## Acceptance Criteria

- Blind audit is documented.
- Live repository/cross-task drift is reconciled.
- Every planned Slice is implementable against current code.
- Task Types are resolved or a real blocker is recorded.
- Readiness state is explicit.

## Documentation Updates

Update this handoff where proven stale. Do not speculatively rewrite product docs.

## Handoff Notes

You are the Project Manager. Execute this Slice yourself and do not delegate it. Apply the QA doctrine in the README to every later Slice.
