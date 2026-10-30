# Slice 05 - Scene integration: organize, open and undo

## Goal

Integrate the finished input semantics, atomic layout command, viewer shell and agent projection into the live Board scene: organization context actions, Enter/double-click opening, object/agent viewer routing and bounded Ctrl/Cmd+Z geometry undo.

## Context

This Slice is the convergence owner for the scene page hot path. It must adapt to the actual outputs of Slices 01, 03 and 04 rather than forcing those branches to wait for each other.

## Canonical Concepts

- final scene selection from Slice 02
- atomic arbitrary layout command from Slice 01
- viewer launch API from Slice 03
- agent projection/action API from Slice 04
- current context-menu/menu UI
- existing optimistic scene pending/hold behavior

## Scope

### In Scope

- Context-menu actions for Open/View and multi-object organization.
- Pure/deterministic arrangement planning for row, column, auto grid, custom grid, align, distribute and equal dimensions.
- Custom graphical grid picker plus numeric fallback.
- Send one atomic layout command per organization action.
- Enter and double-click opening semantics.
- Compatible-selection rules and accessible notice for skipped incompatible objects.
- Agent double-click routing to agent viewer.
- Artifact click-through from agent viewer and deterministic return path.
- Short-lived geometry undo ring and Ctrl/Cmd+Z integration with stale protection from Slice 01.
- Ctrl/Cmd+A final integration if not completed in Slice 02.
- Focus restoration and scene selection preservation around viewer open/close.
- Focused browser/runtime tests.

### Out of Scope

- New scene domain batch command implementation.
- Viewer renderer internals.
- Agent projection internals.
- Persistent groups/containers.
- Viewer save/export.
- Representation redesign.

## Dependencies

### Hard `depends_on`

- `02-mouse-resize-selection-input` - this Slice owns the same scene integration path after the gesture refactor and must not race it.

### Soft `requires`

#### `01-atomic-layout-and-undo-contract`

Need: final atomic arbitrary geometry command and stale-undo semantics.

Fallback during local UI work: a fixture command adapter that records requested ids/target boxes and simulates applied/refused batch outcomes.

Integration required before: approval of this Slice.

Mismatch policy: adapt the UI command adapter/planner output to the canonical contract; do not add per-object writes.

#### `03-multi-object-viewer-shell`

Need: viewer launch API, entry model and close/focus hooks.

Fallback during local UI work: fixture viewer adapter with `open/close` event capture.

Integration required before: approval of this Slice.

Mismatch policy: adapt scene-to-viewer entry mapping; do not duplicate viewer shell code inside the scene page.

#### `04-agent-viewer-projection`

Need: agent view endpoint/model and Stop/Ask descriptors.

Fallback during local UI work: fixture running/completed/unknown agent projections.

Integration required before: approval of this Slice.

Mismatch policy: adapt scene agent identity to the final endpoint; do not synthesize missing mission/progress data in the browser.

### Can Start With

Completed Slice 02 plus fixture seams for 01/03/04.

### Produces

The complete user-facing Board workflow, ready for final convergence QA.

### Integration Checkpoint

Before approval, remove/close all fixture seams for 01/03/04 and validate against their actual final APIs.

## Implementation Steps

1. Re-read Slice 02 behavior and preserve all pointer/selection invariants.
2. Implement a pure layout planner with deterministic visual order and stable group placement.
3. Add organization menu hierarchy, disabled states and custom grid picker.
4. Bind each organization action to exactly one atomic scene command.
5. Record successful geometry transactions in a bounded local undo ring; bind Ctrl/Cmd+Z outside editable controls.
6. On undo, use the Slice 01 stale/compare path. Refusal invalidates/reports the entry rather than forcing stale geometry.
7. Add double-click and Enter dispatch. Viewable media/documents open the compatible selection; agents open agent detail alone.
8. Add context-menu Open/View action with the same dispatch semantics.
9. Add accessible skipped-item notice for mixed incompatible selections.
10. Preserve selection and restore focus on viewer close when the anchor still exists.
11. Wire agent Stop and Ask actions using Slice 04 descriptors.
12. Wire agent artifact cards into the object viewer with deterministic Back/return behavior.
13. Run focused browser/runtime scenarios and capture evidence.

## Files Likely Touched

Revalidate at HEAD. Likely:

- `jarvis/runtime/control_center_scene_page.js`
- arrangement helper module (prefer new pure module)
- current context menu/menu module
- viewer integration/bootstrap module
- focused selection/actions/browser tests

Avoid reimplementing Slice 01/03/04 code in this Slice.

## Architecture Constraints

- One organization action == one atomic scene mutation.
- Viewer interaction never writes Board geometry.
- Agent data is never inferred in the browser.
- Ctrl/Cmd+Z does not become global durable history.
- Editable fields keep normal text undo and selection shortcuts.
- Existing Voice/Bare Hands semantics remain compatible.

## Automated Validation

Focused node/browser/runtime tests for every menu action, custom grid, Enter/double-click, mixed selection, agent routing, focus return and stale undo. No full suite.

## Acceptance Criteria

- Multi-selection context menu preserves the group and exposes organization actions.
- Row/column/grid/align/distribute/same-size produce deterministic atomic geometry.
- Custom grid supports common graphical selection and larger numeric values such as 3x8.
- Enter/double-click/view action open the correct viewer content without moving the Board.
- Agent double-click shows public agent state and working actions.
- Ctrl/Cmd+Z reverses eligible geometry operations and refuses stale ones safely.
- All soft requirements are reconciled to real final interfaces.

## Documentation Updates

Update user interaction docs and viewer integration docs with final shortcuts and selection/open semantics.

## Handoff Notes

This Slice is not complete while any fixture adapter for Slices 01/03/04 remains on the production path.


## S05 atomic group-drag correction (2026-10-30)
PM traced canonical hold path beyond old menu/pointer helpers: createHoldDesk.drop currently loops handle.ids and calls injected d.commit once per member; scene page injects commitUserGeometry only. The known group-drag test therefore points to a real lost atomic behavior, not solely a stale assertion. Earlier readiness wording was incomplete. This task's atomic multi-object/user-manipulation contract requires correction in S05, not deferral as pre-existing.
Extend the SAME shared hold commit seam to submit all eligible group target boxes once through S01's canonical atomic operation (or existing canonical translation when mathematically appropriate). No second gesture engine or manual per-object mutation loop. Preserve hold release, common movement/offsets, user pin semantics, pending/rollback and payload bounds. Unknown/stale required member refuses whole set. Actual browser+Core/SQLite scenario must show one group gesture -> one command and at most one revision, including orbit/fixed behavior. Update canonical docs/static conformance to landed seam; remove old known-failure entry only when corrected test and live behavior pass. S05 tier remains UI plus atomic integration checks; backend critical semantics already verified in S01.

