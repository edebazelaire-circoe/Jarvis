# Slice 01 - Shell contract, design language, and layer registry

## Goal
Establish the canonical UI contract for the new orbital shell before components are migrated.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `00-project-manager`

## Scope / implementation steps
Define and implement the shared shell foundations: layout zones, spacing/tokens, edge anchor geometry, right rail width behavior, bottom-center safe area, bottom-left context zone, global top chrome region, focus states, reduced motion, icon sizing, semantic colors, and an explicit z-index/layer registry. Create or extend the canonical Control Center UI documentation discovered by the PM.

Do not move all features yet. This Slice should make later component placement deterministic and keep current UI functional. Add regression tests for layer ordering rather than relying on arbitrary z-index numbers.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center.html`
- `shared Control Center theme/shell modules discovered at HEAD`
- `tests covering scene/layer order`
- `canonical Control Center UI docs (create/extend after audit)`

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
- A durable shell/layer contract exists and is referenced by later slices.
- Target art direction is represented through reusable tokens/classes, not copied one-off values in every module.
- Existing scene, dialogs, Studio/Variantes, Board chooser and mode chooser still stack correctly.
- `prefers-reduced-motion`, focus-visible and icon-only accessibility conventions are defined.
- Current UI remains functional before migration slices land.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` (§2, §9, §10, §11). QA tier: **ui**.

**Files.** New `docs/control-center-shell.md`; new `jarvis/runtime/control_center_shell.js` (tokens doc mirror, zones, `CONTROL_SELECTOR`) + `SHELL_SCRIPT_FILE` and injection in `jarvis/runtime/control_center.py` (`ControlCenter.index`); `jarvis/runtime/control_center.html` (registry comment replaced by pointer + mirror, `:root` tokens, `data-shell-control` on every control host, empty `#toolWheel` host declared, default-theme geometry aligned on the Cosmos zones); `jarvis/runtime/control_center_work.js` (Cosmos `STYLE`: no position/z-index for shell surfaces unless a registry row says so); `jarvis/runtime/control_center_scene_page.js:2476` and `jarvis/runtime/control_center_capture_rail.js:1144` read the shared selector; new `tests/unit/test_control_center_shell_layers.py`; `tests/unit/test_scene_renderer_logic.py` (registry part delegated); `tests/unit/test_capture_rail_js.py:408` (selector source).

**Acceptance tests.** `test_control_center_shell_layers.py::test_every_rank_in_css_matches_the_registry` (base + Cosmos + module sheets), `::test_registry_lists_chat_drop_and_rail_dialog_ranks`, `::test_cosmos_overrides_no_shell_position_or_rank`, `::test_every_declared_control_host_matches_control_selector`, `::test_tokens_defined_once_and_reduced_motion_zeroes_durations`; `test_scene_renderer_logic.py::test_the_scene_layer_sits_above_the_face_and_below_every_control` (still green); browser: both themes at 1440x900, 1280x720, 900x600, 600x800, scene objects stop against every control incl. `#chatTab`, `#interactionModeHud`, `#presentationRail`.

**Not in this slice.** No wheel behaviour, no feature moved between zones except the default-theme geometry alignment; no removal of `#voiceHint`, palette or capture rail.

**Preserved invariants.** Every control above the scene (20); relative order of the old registry; Studio/Variantes 9000+ untouched; `#jarvisHands` top; Board chooser and mode chooser stack as today; both themes functional.

**Test migrations here.** `test_scene_renderer_logic.py:1376-1414` (selector list -> shell test, `.voicehint` kept until S06), `test_capture_rail_js.py:389-415` (`CONTROL_SELECTOR` literal -> shell module).
