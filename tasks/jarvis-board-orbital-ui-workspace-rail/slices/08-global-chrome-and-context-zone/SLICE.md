# Slice 08 - Simplify global chrome and consolidate the bottom-left context zone

## Goal
Remove remaining visual clutter while guaranteeing that every required global function still has a discoverable route.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `01-shell-contract-and-design-system`
- `06-bottom-status-and-hidden-toggle`
- `07-right-active-workspace-rail`

## Scope / implementation steps
Audit the current right `.dock`, topbar controls and Board control. Produce a before/after destination matrix for ERR/Trace/Test Lab/Timeline/Settings/MCP/Workspace/Studio and any other current tools. Move low-frequency functions into a compact global launcher/top icon group rather than deleting them blindly.

Keep interaction mode in bottom-left. Make Board switching available in the same bottom-left context zone or as an immediately adjacent compact control, while preserving the Board owner's canonical state/API. Do not merge mode and Board state internally merely because they are visually colocated.

Simplify top-right into a cohesive small icon set consistent with the approved target.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_interaction_mode.js`
- `jarvis/runtime/control_center_boards.js`
- `global tool launcher modules discovered at HEAD`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- `code-review` is mandatory.
- `runtime-validation` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- Every pre-refactor required global tool has a documented, discoverable destination.
- Bottom-left always communicates current interaction mode and provides Board access.
- No duplicate Board or interaction-mode state owner exists.
- Top/right chrome is materially less visually dominant than before.
- Keyboard shortcuts and accessibility labels remain documented and usable.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` D11 (changed), §9 zones, §11. QA tier: **ui**.

**Files.** `jarvis/runtime/control_center.html` (`<nav class="dock">` kept with every button id; re-skinned into a compact top-right launcher: 3-4 frequent icons visible plus a "Plus" popover rank 36 holding the rest; badges ERR/AGT kept visible); `control_center_work.js` (Cosmos dock skin); `docs/control-center-shell.md` (destination matrix); `docs/boards.md` § Placement only if the Human picks the fallback. Tests: new `tests/unit/test_global_launcher_browser.py`.

**Destination matrix (to confirm in the slice).** ERR (badge) visible; AGT (badge) visible; SET visible; CNV visible; TRC, LAB, MCP, WSP, PFB, INS in the "Plus" popover; keyboard shortcuts unchanged. Interaction mode stays bottom-left; `#boardsHud` stays in the top state line (D11).

**Acceptance tests.** `test_global_launcher_browser.py::test_every_pre_refactor_tool_has_a_route` (ids from the old dock list), `::test_popover_keyboard_roving_escape`, `::test_badges_visible_without_opening`, `::test_board_control_visible_and_switches_board`, `::test_mode_control_bottom_left_unchanged`; existing dock slicer tests stay green.

**Not in this slice.** Deleting any tool; merging mode and Board state; moving `#boardsHud` (unless HV-08-01 picks the fallback: then sibling right of `#interactionModeButton`, same `JarvisBoardsControl`).

**Preserved invariants.** No duplicate Board/mode owner; every tool reachable by mouse, keyboard and its existing shortcut; ERR/agent badges never hidden behind a click.

**Test migrations here.** None if ids and `<nav class="dock">` are kept: `test_control_center_mvp.py:94-108`, `test_interaction_mode_hud_js.py:1328`, `test_barehands_hud_js.py:985`, `test_prefab_library.py:497`, `test_control_center_mcp_inspector_js.py:821`, `test_presentation_studio_inspector_docs.py:117`, `test_control_center_timeline_ui.py`; otherwise one shared helper (§11). `test_boards_hud_js.py:924` only under the fallback.
