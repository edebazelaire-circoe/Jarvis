# Slice 09 - Integration, responsive behavior, accessibility, and visual polish

## Goal
Prove the redesigned shell works as one system across overlays, viewports, input methods and runtime states.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `03-selection-input-arbitration`
- `04-capture-wheel-migration`
- `05-screenshot-preview`
- `06-bottom-status-and-hidden-toggle`
- `07-right-active-workspace-rail`
- `08-global-chrome-and-context-zone`

## Scope / implementation steps
Reconcile all final layer/z-index contracts. Validate Board, interaction-mode chooser, Board chooser, bottom popovers, wheel/submenus, screenshot preview, right rail, context menus, Settings/full-screen tools, Studio/Variantes and confirmations.

Tune responsive breakpoints so controls do not simply overlap or disappear on short/narrow windows. Validate 200% zoom where practical. Finish keyboard navigation, screen-reader semantics, live regions and reduced-motion behavior.

Run visual comparison against the approved target reference and refine spacing, contrast, icon sizing, card proportions, animation timing and empty-state behavior while retaining the dark Cosmos direction.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `all shell component CSS/JS touched by prior slices`
- `layering tests`
- `runtime validation harness`

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
- Runtime validation matrix in `docs/04-testing-and-quality.md` passes or findings are resolved.
- No known overlap/layer regression across supported surfaces.
- Keyboard-only and Mouse-only operation are complete; Bare Hands flow is validated on the real input path where available.
- Reduced-motion and zoom/narrow/short viewport paths are usable.
- Visual result clearly matches the approved composition and keeps the Board dominant.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` §9-§11, `04-testing-and-quality.md` runtime matrix. QA tier: **ui**.

**Files.** Only shell CSS/JS touched by S01-S08, `docs/control-center-shell.md`, layering/browser tests; new `tests/unit/test_control_center_shell_browser.py` (matrix runner).

**Acceptance tests.** `test_control_center_shell_layers.py` all green (both themes); `test_control_center_shell_browser.py::test_runtime_matrix` covering the 15 states of `04-testing-and-quality.md` × both themes, with screenshots saved as evidence; `::test_keyboard_only_full_path`, `::test_mouse_only_full_path`, `::test_reduced_motion`, `::test_forced_colors`, `::test_axe_when_available` (`JARVIS_AXE_JS`), `::test_zoom_200`, `::test_narrow_700_and_short_560`; BH path on the real input where available (else replayed trace, stated).

**Not in this slice.** New features; re-deciding D5-D11; product changes outside fixes of findings.

**Preserved invariants.** All previous slices' invariants; registry single source; no arbitrary 99999 ranks.

**Test migrations here.** None new; any leftover from S01-S08 must be closed before S10.
