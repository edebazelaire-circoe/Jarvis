# Slice 07 — Deep Sessions & Boards Manager UI

## Goal
Add a top/settings Control Center button that opens a clear deep manager for Sessions, Boards, memory files, artifacts/provenance and runtime relationships.

## Context
This is primarily an operability/debugging surface so the user can verify that memory is actually clear and organized for the agent.

## Canonical Concepts
Workspace inspection API, Board memory operations, Control Center UI stacking/safe-area conventions.

## Scope
### In Scope
- New top/settings control/button and manager surface.
- Overview of current Session/Board/Context.
- Sessions list/history and details.
- Boards list/details including kind/status/timestamps/refs.
- Relationship view: Session -> Board -> binding -> conversation -> agent session/lifecycle.
- Board memory tree and bounded file viewer; safe edit/create/move/delete affordances where authorized.
- Artifact list/detail/provenance and payload/reference metadata.
- Useful activity/trace linkage.
- Loading, empty, error, partial/unavailable states.
- Deep links/jump to Board where appropriate using canonical switch flow.

### Out of Scope
- Replacing all settings UI.
- Meeting/presentation live controls.
- Direct disk browser outside Board workspaces.

## Dependencies
Slices 04-05.

## Implementation Steps
1. Audit top/settings control placement and stacking registry.
2. Design information architecture with `/impeccable` before implementation.
3. Build manager from server-confirmed data; no hidden local duplicate state.
4. Add memory/artifact/relationship inspectors.
5. Add mutation affordances with explicit destructive confirmation where needed.
6. Add accessibility and browser tests.

## Files Likely Touched
Control Center HTML/CSS/JS modules, route client helpers, UI tests.

## Architecture Constraints
Use a Claude Work Agent when supported. Load `/impeccable`, `/caveman`, `/coding-guideline`. Server is source of truth. IDs/details are allowed because this is a management/debugging surface.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation`. Browser/unit tests with realistic large histories and failure states.

## Acceptance Criteria
The user can visually understand where a Board's memory lives, what it contains, how it links to Sessions/bindings/artifacts, and safely perform supported management actions.

## Documentation Updates
Control Center UI docs/stacking registry and operator documentation.

## Handoff Notes
Do not turn the manager into a graph-art project; clarity and inspectability come first.
