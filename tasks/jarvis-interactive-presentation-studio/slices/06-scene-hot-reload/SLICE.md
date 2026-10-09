# Slice 06 - Scene-Local Hot Reload and State Preservation

## Goal
Support arbitrary source/code edits without rebuilding the whole presentation and preserve authoring/playback context when safe.

## Context
The product outcome is live coding feel. Exact HMR technology is not locked.

## Canonical Concepts
Scene source revision, hot reload/remount, rollback, playback/editor state preservation.

## Scope
### In Scope
- Source edit application to a target scene.
- Scene-local rebuild/hot swap/remount.
- Preserve active variant, scene and score position when compatible.
- Failure rollback to last valid scene.
- Explicit state-reset signal when compatibility cannot be preserved.

### Out of Scope
- AI code-generation strategy itself.
- Rebuilding unrelated scenes.

## Dependencies
- `05-semantic-edit-api`
- External: actual scene/prefab runtime mounting contract.

## Implementation Steps
1. Select repository-native HMR/remount mechanism.
2. Add scene revision tracking.
3. Implement compile/validation gate before swap.
4. Preserve compatible runtime/editor state.
5. Roll back on compile/mount failure.

## Files Likely Touched
Presentation renderer/scene adapter/dev-runtime/edit service and tests.

## Architecture Constraints
Never let a failed edit destroy the last valid presentation state.

## Automated Validation
Good/bad source edit fixtures, affected-scene-only rebuild, state preservation, rollback, leak/cleanup tests.

## Acceptance Criteria
A source-level change can be applied to one scene with a coherent live result and safe failure behavior.

## Documentation Updates
Document reload guarantees and reset cases.

## Handoff Notes
Frontend/runtime Slice: `/caveman`, `/coding-guideline`, `/impeccable`, Claude when supported.
