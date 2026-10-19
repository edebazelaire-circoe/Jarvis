# Slice 01b — Retire user-facing interaction-mode writers (derived mode only)

## Goal

After Slice 01a made the Board type authoritative and Core derives the live mode from it, remove every remaining path by which a human or an agent can set a product mode independently of the Board type, while keeping the transient Presentation Studio run seam and every read-only display of the live mode.

Created by Slice 00 when it split the original Slice 01 (`../../docs/08-readiness-audit.md` §4, plan items 3-5).

## Dependencies

- `01-board-type-contract-migration` (Slice 01a)

## Scope / implementation steps

1. Control Center: delete the `POST /api/interaction-mode` user write path and the replay code (inert since 01a: `_core_boards_own_interaction_mode` always answers `True`) with its sources `startup` / `core_restart` / `save_retry` (`jarvis/runtime/control_center.py`, `jarvis/runtime/interaction_mode_view.py`). The global key in `runtime/control-center-settings.json` is no longer read for behaviour nor written; leave it in the file (no destructive cleanup of user files). `GET /api/status.interaction_mode` stays, read-only, for display.
2. `jarvis/runtime/interaction_mode_settings.py`: reduce to what the display/diagnostic still needs, or delete with its callers; no `describe()` item that offers a mode choice in Réglages.
3. Core `POST /v1/interaction-mode` (`jarvis/protocol/server.py`): refuse **every** source with a stable refusal (e.g. `interaction_mode_derived`, 409, French message saying that behaviour follows the Board type), or delete the route with its client method. No HTTP caller uses `presentation_studio_run`: the Studio calls `InteractionModeService.request` in-process (`jarvis/core/presentation_studio_playback.py:763` entry, `:889` restore), which stays allowed. `GET` unchanged.
4. Brain surfaces: remove the `interaction_mode` item from `settings_set` (`jarvis/runtime/settings_mcp.py`); rewrite the prompt line `jarvis/runtime/claude_local.py:245` (« passe en mode présentation… ») so the brain answers by proposing/creating/switching to a Présentation Board (`board_create` with `board_kind`, `board_switch`), never a mode write (`tool_brain_perception.py:378` was already adapted in 01a).
5. Presentation Studio: verify (do not redesign) that `plan_mode_entry` / `source="presentation_studio_run"` still enters and restores the mode, that restore returns to the **Board-derived** baseline, and that `foreign_change` is now raised only by a Board switch during a run. Update `docs/presentation-studio.md` lines that say the user can change the mode during a run or that restore reads « the stored per-Board preference ».
6. The bottom-left mode HUD may still be composed after this Slice (Slice 02 removes it): it must become display-only (no chooser writes) so no intermediate commit offers a write that Core refuses.
7. Update `docs/interaction-mode.md` (*Control plane*, *Persistence owner*, *The Control Center selector*, *The brain's handle*) to the derived contract (QA 01a: the « persist » wording left at ~l. 419, 568 and 910, and README ~l. 196 « chosen in the Control Center »); remove the superseded statements instead of appending a second story. Update `docs/voice-settings-schema.md` / wake-word docs only where they cite the mode setting (`test_wake_word_docs.py`).
8. Found by QA of Slice 01a, to close here:
   - a `switch_noop` to the Board already active (`board_service.py` `_switch_locked`, early return ~l. 456-459) does not re-apply the Board type's mode, so a legacy live change survives it; re-apply the derived mode there (or prove the writers are gone so it cannot diverge);
   - `POST /api/interaction-mode` answers `stored_value` / `stored_schema_version` although nothing is stored, `requested.previous` reads the global preference, and the top-level `mode` of `GET` is misleading: align the payloads with the derived contract (or remove them with the route).

## Out of scope

- Visual removal/relocation of the HUD and of the Voice presence report (Slice 02).
- Meeting runtime.
- Voice architecture / speaker authorization axes.

## Files likely touched (verified at HEAD 2fb66040)

`jarvis/runtime/control_center.py`, `jarvis/runtime/interaction_mode_view.py`, `jarvis/runtime/interaction_mode_settings.py`, `jarvis/protocol/server.py`, `jarvis/protocol/client.py`, `jarvis/runtime/settings_mcp.py`, `jarvis/runtime/claude_local.py`, `jarvis/runtime/control_center_interaction_mode.js` (write path only), `jarvis/app.py` (view wiring), `docs/interaction-mode.md`, `docs/presentation-studio.md`, `docs/mcp/tool-contract.md`.

Tests: `test_interaction_mode_contract.py`, `test_interaction_mode_control_plane.py`, `test_interaction_mode_protocol.py`, `test_interaction_mode_follower.py`, `test_interaction_mode_hud_js.py`, `test_interaction_mode_hud_browser.py` (+ `_interaction_mode_browser.mjs`), `test_control_center_presentation_status.py`, `test_settings_mcp.py`, `test_mcp_catalog.py`, `test_presentation_studio_roles.py`, `test_presentation_studio_playback_service.py`, `test_variants_run_js.py`, `test_variants_run_browser.py`, `test_wake_word_docs.py`, `test_wake_word_settings_api.py`, `test_v2_continuous_live.py`, `tests/integration/test_presentation_scenarios.py`, `tests/integration/test_board_session_e2e.py`.

## Architecture constraints

- One truth: the active Board's type. The only non-Board source of a live mode change is a running Studio session, transient and restored.
- Voice still observes `interaction.mode.changed` and never restarts on a mode change (D15 of the interaction-mode contract).
- Refusals are explicit and stable-coded; nothing silently ignores a former write.

## Automated validation

- `qa-verification`, `code-review`
- `runtime-validation` in an isolated data root (Core + Control Center + Voice where available): switch Assistant → Présentation → Réunion → Assistant, Studio run on an Assistant Board, Core restart mid-run.
- `agent-trace-analysis`: real trace of « passe en mode présentation » and « passe en mode simple » requests.

## Acceptance criteria

- No HTTP route, MCP tool, setting or prompt lets anyone set a product mode that diverges from the active Board type.
- Studio runs still switch and restore the mode, to the Board-derived baseline.
- `/api/status` still shows the live mode for display.
- Canonical docs teach only the derived model.

## Documentation updates

`docs/interaction-mode.md`, `docs/presentation-studio.md`, `docs/mcp/tool-contract.md`, README section on modes.
