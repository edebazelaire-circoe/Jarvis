# Slice 06 — Control Center MCP plugin manager UI

## Goal
Evolve the existing single MCP inspector into a ChatGPT-like plugin-management center. Keep one MCP button; separate internal exposure and external plugins; add cards with icon/fallback, name/origin, connection/auth status, enable toggle, tool count and Manage; URL onboarding; OAuth handoff; manual token/API-key/custom-header fallback; connect/reconnect/disconnect/remove; reuse the canonical tool inspector.

## Dependencies
03-remote-mcp-connection-manager, 04-intent-tool-registry-and-gateway

## Quality gates
qa-verification + code-review + runtime-validation + agent-trace-analysis. Coding loads /caveman and /coding-guideline; frontend additionally loads /impeccable. Regressions caused by this slice are blocking.

## Acceptance criteria
The requested runtime/UI flow is proven end-to-end without provider-specific hacks or credential leakage, and canonical MCP behavior stays green.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §10, §14 C5/C6. Frontend Slice: `/impeccable` required.

### Scope (files)
- Create `jarvis/runtime/mcp_plugin_routes.py` (CC relay, pattern `board_routes.py` + `CoreSessionTransport.forward`): `GET/POST /api/mcp/plugins`, `PATCH/DELETE /api/mcp/plugins/{id}`, `POST .../connect|disconnect|refresh`, `PUT .../credential`, `GET /api/mcp/oauth/callback` (static FR HTML result page, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, loopback Host check, never echoes `code`/`state`).
- Modify `jarvis/runtime/control_center.py`: register the routes; add `"/api/mcp/plugins"` to `READ_GUARDED_ROUTES` (:239) and keep `/api/mcp/oauth/callback` outside it; `_mcp_json_errors` (:1600-1619) keeps "read-only (GET)" for `/api/mcp/tools*` only; inject the new JS module (`MCP_PLUGINS_SCRIPT_FILE` / `_MARKER` beside :484-489).
- Create `jarvis/runtime/control_center_mcp_plugins.js` (all plugin writes), modify `jarvis/runtime/control_center.html` (tab switch "Exposition interne" / "Plugins externes" inside `#mcpInspector`, marker) and `jarvis/runtime/control_center_mcp_inspector.js` only to expose one reuse entry for tool details (no write path, still GET-only).
- Amend `tests/unit/test_control_center_mcp_api.py` (route set ~:372-376, 405 text scoped to `/api/mcp/tools*`).

### Out of scope
Any Core behavior change (bugs found go back to Slice 03/04 owners via agent 0); plugin marketplace; per-agent toggles; icon fetching by Core.

### Acceptance criteria
- [ ] One MCP button, one dialog; internal view unchanged (existing inspector tests green); external view lists plugin cards (icon or letter fallback, name, host, connection + auth badge, enable toggle, tool count, Gérer).
- [ ] Add by URL -> create -> connect: no-auth plugin becomes connected; OAuth plugin opens the authorization URL in a new tab and the card turns connected after the fake callback; manual Bearer / custom header form is write-only (value never re-rendered, never in any GET body).
- [ ] Enable/disable, reconnect, disconnect, remove (with confirmation) work and reflect Core state after reload.
- [ ] Plugin tools open in the existing inspector detail renderer (`/api/mcp/tools/{plugin_id}/{name}`); no tool name literal in either JS module.
- [ ] Inspector module still refuses non-GET and non-catalog paths (tool-contract §10.7) — test unchanged-green.
- [ ] Cross-origin POST/PATCH/DELETE on `/api/mcp/plugins*` refused 403 coded; callback works from a cross-site navigation; replayed callback shows the coded failure page.
- [ ] Core down: plugin view shows a coded error + "Réessayer"; internal view still works.
- [ ] Keyboard + screen-reader flow (tabs, cards, toggle, forms, dialogs), responsive < 700 px, `prefers-reduced-motion`, page tokens only.

### Required tests
- `tests/unit/test_control_center_mcp_plugins_api.py`: relay status/body verbatim, guard on every method, callback outside the guard, Core unreachable 503, secret sentinel absent from every response and journal line.
- `tests/unit/test_control_center_mcp_plugins_js.py` (node, real API payloads from a real `ControlCenter` + fake Core): card states, add/connect/OAuth polling, manual credential form, enable toggle, remove confirm, reuse of the inspector renderer, no tool-name literal.
- `tests/unit/test_control_center_mcp_inspector_js.py` + `test_control_center_mcp_api.py` (amended, still asserting GET-only for `/api/mcp/tools*`).

### Required evidence for QA
Runtime-validation in a real browser against the fake plugin server (screenshots of each card state, add/OAuth/manual flows, keyboard pass, 375 px width); axe (or equivalent) report; network log showing no secret in any response. Then HV-06-01.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
