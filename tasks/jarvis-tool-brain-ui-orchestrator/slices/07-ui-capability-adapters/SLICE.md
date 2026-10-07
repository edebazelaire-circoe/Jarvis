# Slice 07 — UI Capability Adapters

## Goal

Expose the practical UI operations Tool Brain needs through canonical services and choice providers, including scene, Board, process/agent presentation and browser/display navigation.

## Context

Many scene tools already exist. The task is to normalize/reuse them and fill real capability gaps, not to create duplicate tools for every visual action.

## Canonical Concepts

Scene action, Board navigation, process/agent display object, browser/display surface, semantic UI operation.

## Scope

### In Scope

- Audit/normalize existing scene actions for Tool Brain use.
- Board list/inspect/switch and, where already part of UI semantics, create/focus operations.
- Read/select current task/agent/process entities that can be displayed.
- Open/focus/close/move/resize relevant windows/surfaces using canonical APIs.
- Browser/display operations: open/focus URL/surface, scroll/reveal, back/forward, zoom when supported.
- Dynamic choice providers for every runtime-known ID/enum parameter.
- Semantic batching where the user perceives an action as one coherent UI operation.

### Out of Scope

- Tool Brain-driven web search/research.
- Arbitrary OS automation outside the canonical Jarvis UI/browser surface.
- Duplicating pending prefab/window-family implementations.

## Dependencies

- `02-ui-tool-choice-contract`
- `03-perception-world-model`
- `06-action-queue-revalidation`

## Implementation Steps

1. Reuse/normalize existing scene tools through the canonical tool catalog.
2. Fill missing Board UI operations through the established Board owner.
3. Add process/agent/task selection/read adapters only where canonical runtime objects exist.
4. Audit browser/display control infrastructure and add the minimum semantic operations required.
5. Attach dynamic choices, side-effect classes and preconditions.
6. Add end-to-end tests from Tool Brain action -> canonical service -> resulting UI state.
7. Reconcile with scene-window-prefab work immediately before scene/window edits.

## Files Likely Touched

Scene/UI MCP facade and domain services, Board facade, browser/display runtime and tests identified by Slice 01.

## Architecture Constraints

Browser navigation is presentation. Any operation whose purpose is to discover/interpret external information remains outside Tool Brain V1.

## Automated Validation

- Every mutator has canonical owner and validation.
- Board switching preserves existing authority semantics.
- Scene operations preserve batching/revision rules.
- Browser actions act only on allowed known surfaces/URLs supplied through current context/choices.

## Acceptance Criteria

- Tool Brain can perform the intended UI repertoire without free-form ID guessing.
- Existing direct UI/MCP callers remain compatible.
- No parallel scene/Board/browser state is introduced.

## Documentation Updates

Update canonical tool catalog and UI capability docs.

## Handoff Notes

Use `/caveman` and `/coding-guideline`. Any frontend code also requires `/impeccable` and a Claude agent when host routing supports it.
