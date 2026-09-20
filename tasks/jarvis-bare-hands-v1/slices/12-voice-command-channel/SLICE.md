# Slice 12 — Bare Hands command channel from the brain to the page

## Goal

Give the brain a way to drive Bare Hands in the running Control Center page, so that voice can activate/deactivate Bare Hands, launch calibration, launch the tutorial and exit an overlay. This Slice builds the transport; Slice 09 wires the tutorial and calibration flows onto it.

## Context

Added by Slice 00 (2026-09-19) after the readiness audit, on Human decision D2. Decision 6 and Slice 09 assume a "current Jarvis voice command architecture" that does not exist:

- There is no voice command registry and no intent router in this repository.
- In the default `continuous_brain` architecture the Realtime surface is given **zero** tools (`jarvis/runtime/realtime_tools.py:30`, Décision 34) and is forbidden from claiming any action (`jarvis/adapters/openai_realtime.py:74-97`). The whole turn is forwarded to the brain.
- Therefore voice must route utterance → brain (Claude CLI) → MCP tool → server → page. The last hop does not exist for Bare Hands: `/api/status` carries no Bare Hands field, and the page only polls `GET /api/barehands` at load and after a toggle.

Without this Slice, Slice 09's voice bullets are undeliverable.

## Canonical Concepts

- brain-facing MCP tool surface (`jarvis/runtime/display_mcp.py`)
- request/receipt delivery to the visible page (scene `capture_request`)
- Bare Hands settings route and lifecycle
- prompt catalog as the brain's capability list

## Scope

### In Scope

1. A brain-facing MCP tool surface for Bare Hands commands: activate, deactivate, start calibration, start tutorial, exit overlay. Follow the `@mcp.tool()` shape of `display_mcp.py:2217+`, with stable issue codes and no false success.
2. A server-side command queue with a bounded deadline, and delivery to the page over the existing long-poll idiom, modelled on `jarvis/runtime/scene_view.py:314-322` (`capture_request`) and `POST /api/scene/captures/{id}` for the receipt.
3. A page-side consumer that dispatches each command to the **same** runtime entry points the UI button uses. No parallel implementation.
4. Gating consistent with the rest of the subsystem: the tool surface is offered to the brain only when Bare Hands is enabled, mirroring how `display_mcp` is gated on `scene["enabled"]` in `control_center.py`.
5. A prompt descriptor so the brain knows the capability exists (`jarvis/runtime/prompt_catalog.py`), registered like the existing `BRAIN_DISPLAY_PROMPT` family.
6. Journal events for every command issued, delivered, refused and expired, through `RuntimeJournal.emit` with a stable `code` in `data`.

### Out of Scope

- Wake-word or phrase matching. The brain decides intent; this Slice only transports the resulting command.
- The calibration and tutorial flows themselves (Slices 08 and 09).
- V2/Realtime surface tools — they are closed in the default architecture and are not the delivery path.
- Any change to the AGPL upstream board server or its `/cmd` protocol.

## Dependencies

02, 07

## Implementation Steps

1. Load /caveman and /coding-guideline before coding; this Slice touches browser code, so also load /impeccable.
2. Freshness-check `display_mcp.py`, `scene_view.py`, `control_center.py` routes and `prompt_catalog.py` before editing.
3. Define the command vocabulary and its refusal codes first, as a pure module with node/unit tests, before wiring transport.
4. Implement the server queue and route, then the page consumer, then the MCP tool.
5. Register any new page module as a marker in `control_center.py` and `control_center.html`, and assert its load order (see Slice 00 finding F3).
6. Add deterministic tests: queue bounds and expiry, refusal codes, receipt handling, and a page-side test that a delivered command calls the same entry point as the UI button.
7. Record durable discoveries in LOG.md.

## Files Likely Touched

- a new Bare Hands MCP module, or an extension of `jarvis/runtime/display_mcp.py`
- `jarvis/runtime/control_center.py` (routes, gating, marker constants)
- `jarvis/runtime/control_center.html` (marker placement)
- `jarvis/runtime/control_center_barehands.js` or the extracted Bare Hands modules
- `jarvis/runtime/prompt_catalog.py`
- `jarvis/app.py` if a separate stdio server is introduced
- Bare Hands and MCP tests

## Architecture Constraints

- The page must never receive a command it cannot refuse cleanly; every refusal carries a stable code, surfaced in `X-Jarvis-Error-Code` for HTTP.
- Commands expire. A stale command must not fire after the user has moved on; follow the bounded-deadline pattern of `scene_capture`.
- Voice and UI must converge on one runtime entry point per action.
- No new always-on polling loop: reuse the existing long-poll idiom rather than adding a second timer to the page.
- Bare Hands remains off by default; the channel must be inert when the subsystem is disabled.

## Automated Validation

Unit tests for the command vocabulary, queue bounds and expiry; MCP tool tests asserting stable issue codes and refusal on unknown commands; a page-side node test proving command dispatch reaches the shared entry point; route registration and marker/load-order assertions server-side.

## Acceptance Criteria

- The brain can activate and deactivate Bare Hands, start calibration, start the tutorial and exit an overlay, in the default `continuous_brain` architecture.
- Every command is journaled and every refusal carries a stable code.
- No parallel implementation of any action already reachable from the UI.
- The channel is inert, and the tool surface absent, when Bare Hands is disabled.

## Documentation Updates

Document the command vocabulary, refusal codes and the delivery contract alongside the Bare Hands settings documentation, and add the events to the observability contract.

## Handoff Notes

This Slice changes agent tool surfaces and routing, so QA is baseline `qa-verification` plus `code-review`, `runtime-validation` and **`agent-trace-analysis` with real trace evidence** from `runtime/trace.jsonl`. Slice 09 depends on this Slice for its voice entry points.
