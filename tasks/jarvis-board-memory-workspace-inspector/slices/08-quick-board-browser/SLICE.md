# Slice 08 — Quick Board browser and switcher

## Goal
Evolve the existing everyday Board control into a compact screen/list of all Boards with create/rename/archive/switch actions and Board kind visibility, without duplicating the deep manager.

## Context
Current main already has `#boardsHud` and `control_center_boards.js` with list/create/rename/archive/switch. The user explicitly wants a button that lists all Boards.

## Canonical Concepts
Existing Board UI/server-confirmed switch semantics, Board kind.

## Scope
### In Scope
- Reuse/evolve current Board button/list.
- Show all active Boards and optional archived view.
- Show current Board clearly and Board kind when available.
- Preserve create/rename/archive/switch actions.
- Link to/open deep manager for advanced inspection.
- Preserve switch timeout/verifying/server-truth behavior.

### Out of Scope
- Reimplementing Board switching.
- Showing the entire memory tree in the quick picker.
- Final future bottom-left layout redesign unless the current execution baseline already moved there.

## Dependencies
Slices 01 and 06; coordinate visually with Slice 07.

## Implementation Steps
1. Audit current `control_center_boards.js` and user flow.
2. Apply `/impeccable` to simplify list/browser presentation.
3. Add Board kind/status metadata from shared API.
4. Preserve existing refusal/unknown-outcome semantics.
5. Add link/action to deep manager.

## Files Likely Touched
`jarvis/runtime/control_center_boards.js`, Control Center HTML/CSS, browser/unit tests.

## Architecture Constraints
Load `/impeccable`, `/caveman`, `/coding-guideline`; use Claude Work Agent when supported. Do not create a second source of Board truth.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation`. Existing Board UI tests plus new browser coverage.

## Acceptance Criteria
One compact control lists Boards and performs ordinary management reliably, while advanced memory/session inspection remains in the deep manager.

## Documentation Updates
Board UI docs and screenshots/specs if maintained by the repository.

## Handoff Notes
If product design later moves this control to bottom-left, preserve the module/service contract so placement is a presentation change, not another Board implementation.

## Slice 00 contract (agent 0, 2026-10-02)

Binding over the generic sections above; source: `docs/06-resolved-architecture.md`.

- Per R6: evolve `#boardsHud` / `control_center_boards.js` (kind badge, kind on create/edit, last opened, archived filter, "Inspecter" -> deep manager on that Board). No second selector.
- Keep existing `test_boards_hud_js` / browser tests green; extend them.
- Load `/impeccable`.
