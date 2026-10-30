# Slice 01 - Atomic layout and safe geometry undo contract

## Goal

Add the minimum canonical scene capability needed to apply arbitrary target geometries to a selected group atomically, and define safe stale-aware semantics that the UI can use for bounded geometry undo.

## Context

Existing `translate_selection` atomically applies one common delta. Organization actions need different target boxes for different members. Sending N `set_geometry` commands would create partial states and multiple revisions, which violates the product contract.

The exact new operation name and wire shape are deliberately not locked by planning. Fit the existing scene vocabulary after the Slice 00 audit.

## Canonical Concepts

- `SceneSelection`
- `SceneBatchReport`
- scene command/reducer authority
- one snapshot / one patch / one revision semantics
- existing geometry validation and user pin behavior

## Scope

### In Scope

- Domain value(s) for bounded per-object target geometries.
- One atomic scene operation for arbitrary selected geometry targets.
- All-or-nothing validation and batch report.
- Wire/protocol/Control Center relay support.
- Optimistic/pending compatibility needed by later UI integration.
- Safe compare/stale semantics for undo if current architecture needs a Core-side precondition.
- Focused unit/integration tests for the new command.

### Out of Scope

- Row/grid/alignment math.
- Context menu UI.
- Browser undo ring UI.
- Durable history or redo.
- Full test suite.

## Dependencies

### Hard `depends_on`

None after Slice 00 READY.

### Soft `requires`

None.

### Can Start With

Current scene selection/batch contracts and tests.

### Produces

A stable atomic arbitrary-layout command API and test fixtures usable by Slice 05.

### Integration Checkpoint

Slice 05 must reconcile its planner output to this command and its stale/undo result semantics before approval.

## Implementation Steps

1. Re-read current scene domain, batch planner, wire parser and Control Center proxy at HEAD.
2. Choose the smallest operation shape consistent with existing selection commands. Keep request size bounded by scene limits and wire limits.
3. Validate that every target names an eligible active placed object and every target geometry passes normal geometry rules.
4. Apply the entire set on one current snapshot or reject without mutation.
5. Preserve authority rules and `pinned_by_user` semantics for an explicit user/brain command.
6. Return a normal batch report with matched/changed/unchanged/refused information.
7. Add compare-before-write semantics if needed so an undo request can say, atomically, `revert only if these members still have the geometry produced by the operation being undone`.
8. Extend protocol serialization and relay paths without creating a second batch format.
9. Add focused domain/wire/protocol tests including invalid member, stale compare, payload bounds and one-revision behavior.
10. Update canonical scene-selection/batch docs.

## Files Likely Touched

Revalidate at HEAD. Likely areas:

- `jarvis/domain/scene.py`
- `jarvis/domain/scene_batch.py`
- `jarvis/domain/scene_selection.py` if needed
- scene wire/protocol modules
- Control Center scene proxy/transport
- focused scene batch/protocol tests
- `docs/scene-selection-batch.md`

## Architecture Constraints

- No partial apply.
- No command chunking.
- No general transaction/history framework.
- No duplicated selection resolver.
- Do not make CSS/browser state authoritative for scene geometry.

## Automated Validation

Run only focused scene domain, batch, wire and protocol tests for this command. Add property/parity tests where existing batch commands use them. Do not run the complete repository suite.

## Acceptance Criteria

- N different target boxes can be committed in one scene action.
- Success advances the scene by one revision at most.
- Any invalid/stale required member prevents partial geometry writes.
- Existing selection commands remain compatible.
- The later UI can implement stale-safe undo without overwriting changed targets.

## Documentation Updates

Update the canonical scene batch command documentation and any MCP/tool contract only if the operation is exposed there.

## Handoff Notes

Return the exact final command/wire shape and focused test names to Slice 05. Do not require Slice 05 to reverse-engineer implementation details.

