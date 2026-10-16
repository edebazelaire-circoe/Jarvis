# Slice 03 - Mouse/Bare Hands selection arbitration

## Goal
Reduce Selection to Mouse/Bare Hands and implement intelligent, non-flapping control takeover.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `02-orbital-tool-wheel`

## Scope / implementation steps
Wire the Selection wedge to a two-choice radial submenu: Mouse and Bare Hands only. Remove legacy/extra selection choices from this surface. Replace the disliked Bare Hands selector icon with a new clean product icon consistent with the approved reference.

Implement intentional Mouse takeover: click is immediate; movement uses a bounded displacement/velocity threshold with hysteresis and debouncing. Micro jitter never changes mode. Once Mouse is active, hand presence does not auto-return to Bare Hands. Return occurs only by explicit UI selection or the canonical Jarvis command path.

Reuse the canonical Bare Hands lifecycle/state transitions; do not add another lifecycle state variable that can diverge.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `Bare Hands HUD/contracts/input modules`
- `new arbitration module if appropriate`
- `control_center.html integration`
- `tests for Bare Hands/Mouse UI logic`

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
- Exactly Mouse and Bare Hands are offered.
- Explicit mouse click takes over immediately.
- Meaningful movement takes over; jitter does not in automated and runtime tests.
- No automatic return to Bare Hands.
- Failed Bare Hands activation is rendered truthfully.
- New Bare Hands icon is visually approved against the design direction and has an accessible label.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` §4 (D5). QA tier: **ui** + property-style tests of the pure arbitration function.

**Files.** New `jarvis/runtime/control_center_input_arbitration.js` (pure `decide(state, event, params)` + browser seam listening to trusted pointer events) + script constant/injection in `control_center.py`; `control_center_tool_wheel.js` (Selection sub-arc Mouse / Bare Hands, Bare Hands secondary sub-arc: tools pointer/pan/select, Veille, Aide, Diagnostic, Calibration); `control_center_barehands_hud.js` (export the `choose` sequence as `JarvisBarehandsHudControl.selectMethod('mouse'|'bare_hands')`; remove the permanent palette strip and top-left lifecycle control from the default view once the sub-arc passes); `control_center_barehands.js` (`disable({reason})` toast wording only); new BH selector icon (inline SVG); `docs/barehands-contracts.md` (§ Palette rewritten, § 1 selector note), `docs/control-center-shell.md`; tests `tests/unit/test_input_arbitration_js.py`, `tests/unit/test_selection_method_browser.py`.

**Acceptance tests.** `test_input_arbitration_js.py::test_click_takes_over_immediately`, `::test_untrusted_or_bh_pointer_id_ignored`, `::test_jitter_below_net_threshold_never_takes_over` (property: random zero-mean walks, 10k seeds), `::test_slow_drift_outside_window_never_takes_over`, `::test_deliberate_move_takes_over_once_and_resets`, `::test_no_transition_when_not_active`, `::test_cooldown_after_explicit_bare_hands`; `test_selection_method_browser.py::test_only_mouse_and_bare_hands_offered`, `::test_mouse_choice_disables_bh_and_c_pose_cannot_wake`, `::test_bare_hands_choice_activates_and_persists`, `::test_failed_activation_rendered_with_cause`, `::test_tools_reachable_in_bare_hands_subarc_single_write_path`, `::test_voice_activate_returns_to_bare_hands`.

**Not in this slice.** No new BH lifecycle state or persisted field; no change to `c_pose` or the pinch engine; captures untouched.

**Preserved invariants.** BH lifecycle authoritative; one tool write path (`saveSettings({tool})`); help/diagnostic/calibration reachable; error state never shown as Mouse; return to Bare Hands only by explicit UI or voice.

**Test migrations here.** `test_barehands_palette_js.py` (strip -> sub-arc, same invariants), `test_barehands_hud_js.py` parts that assert the top-left control is visible by default. Measure return latency; > 3 s -> Issue `Issues/barehands-return-latency.md`.
