# Slice 04 - Migrate Video, Screenshot, and Audio into the wheel

## Goal
Replace the permanent capture rail presentation with wheel actions while preserving Core capture truth and recovery behavior.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `02-orbital-tool-wheel`
- `03-selection-input-arbitration`

## Scope / implementation steps
Refactor/reuse `control_center_capture_rail.js` logic instead of rewriting capture ownership. The new view consumes the same canonical status and write/re-read flow.

Audio: activation toggles start/stop, duration remains visible when wheel closes, secondary action shows supported audio sources.
Video: activation toggles screen recording, persistent `REC + duration`, secondary action shows supported targets.
Screenshot: immediate one-shot capture with default target; secondary action shows supported targets.

Only expose options backed by current capture adapters/API. Preserve status-loss handling, privacy-first stop, stale poll rejection, Core-derived timing, multi-tab/reload truth and independent audio/video channels.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `jarvis/runtime/control_center_capture_rail.js`
- `jarvis/runtime/control_center.html`
- `docs/capture.md only if contract changes`
- `existing capture JS/unit tests`

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
- Old permanent capture rail can be removed/hidden without losing behavior.
- Audio and Video start/stop match canonical capture state and errors.
- Screenshot executes a real one-shot capture.
- Active capture indicators remain after wheel retracts.
- Reload/status-loss behavior remains at least as safe as before.
- No optimistic local recording state becomes authoritative.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` §5 (D6), D3, D4. QA tier: **critical** (privacy stop path, status truth; mutation testing allowed on the controller model).

**Files.** Core: `jarvis/core/capture_api.py` + `jarvis/protocol/capture_routes.py` (`GET /v1/captures/targets`), screen/audio registries expose `targets()` (`jarvis/adapters/screen_capture.py`, `jarvis/adapters/sounddevice_recording.py`); relay `jarvis/runtime/capture_relay.py` (`GET /api/captures/targets`); `jarvis/protocol/client.py` forwardable path if required. UI: `jarvis/runtime/control_center_capture_rail.js` split into controller/view-model (`JarvisCaptureRail.subscribe(viewModel)`, `start(channel,{device})`, `screenshot({device})`, `stop(id)`, `targets()`) and views (wheel wedges, persistent indicators host `#recIndicators`); old rail view removed; `control_center_tool_wheel.js` (Video/Screenshot/Audio wedges + target sub-arcs); wheel feature flag removed; `docs/capture.md` (§ HTTP API, § Interface rewritten from "left capture rail" to wheel + indicators), `docs/control-center-shell.md`. Tests: `tests/unit/test_capture_targets.py` (Core + relay), `tests/unit/test_capture_rail_js.py` (controller kept, view parts migrated), `tests/unit/test_capture_wheel_browser.py`.

**Acceptance tests.** `test_capture_targets.py::test_targets_list_default_and_displays_in_source_order`, `::test_audio_targets_use_name_tokens_and_default_first`, `::test_enumeration_failure_returns_default_only_and_journals`, `::test_relay_is_read_guarded`; `test_capture_rail_js.py` existing controller tests all green (single flight, cadence, backoff, no stale read after write, Core-derived timers, status-loss stop); `test_capture_wheel_browser.py::test_audio_toggle_start_stop_matches_status`, `::test_video_toggle_rec_timer_survives_wheel_close_and_reload`, `::test_screenshot_one_shot_default_target`, `::test_secondary_lists_only_real_targets_single_entry_informative`, `::test_status_loss_keeps_stop_and_refuses_start`, `::test_two_tabs_same_truth`, `::test_audio_and_video_independent`.

**Not in this slice.** Screenshot preview (S05); final placement of indicators beside the status centre (S06 places them; here they render in a provisional bottom-left-of-centre slot inside the registry rank 40). No window capture, no system audio.

**Preserved invariants.** Core is the only capture truth; no optimistic active paint; privacy-first stop during status loss; `already_active` not an error; captures are not BH tools (D14/D15).

**Test migrations here.** `test_capture_rail_js.py:389-415` (host/placement assertions -> wheel host + indicators), `tests/unit/test_capture_rail_browser.py` (placement scenarios -> wheel scenarios; keyboard/forced-colours/axe kept).
