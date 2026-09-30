# Slice 03 — Remote MCP connection and authentication manager

## Goal
Implement generic remote MCP transport/auth/discovery without provider-specific code: current remote HTTP transport, OAuth discovery/browser flow with PKCE/state and issuer/resource binding, refresh/expiry/step-up where supported, bearer/API-key/custom-header fallback, reconnect/backoff, safe redirects, SSRF/local-network policy, bounded untrusted payloads, and fake MCP/OAuth fixtures.

## Dependencies
02-plugin-registry-and-credential-vault

## Quality gates
qa-verification + code-review + runtime-validation where applicable + agent-trace-analysis for MCP/runtime behavior. Coding loads /caveman and /coding-guideline. Regressions caused by the slice are blocking.

## Acceptance criteria
Canonical contracts/tests updated, no secret leakage, dependencies green, and runtime evidence captured before completion.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §4.1-4.2, §4.3 (connect/refresh/oauth routes), §5, §9.

### Scope (files)
- Create `jarvis/adapters/mcp_http_policy.py` (`PolicyTransport`: DNS resolution + `is_forbidden_address`, https rule, dev loopback flag, 4 MiB response cap, `max_redirects=3`).
- Create `jarvis/adapters/mcp_oauth.py` (`VaultTokenStorage`, `JarvisOAuthProvider` with stored expiry, interactive vs non-interactive handlers, `iss` check support, client metadata of ARCH §5.3).
- Create `jarvis/adapters/remote_mcp.py` (`SdkRemoteMcpConnector`, `RemoteMcpSession`: initialize, paginated bounded `list_tools_all`, `call_tool`, `on_tools_changed`; static bearer/header auth on MCP requests only).
- Extend `jarvis/core/mcp_plugin_service.py`: `PluginConnection` owner task per plugin, `connect` (auto/none/oauth; answers within 20 s with connected, or 202 + `authorization_url`), `complete_oauth`, pending authorizations (single-use state, 300 s TTL), backoff reconnect, `refresh`, `list_changed` handling, boot reconnect (non-interactive only), bounded `stop()`; tools stored through `normalize_remote_tool` (add to `jarvis/domain/mcp_plugins.py`, ARCH §6.2).
- Modify `jarvis/protocol/server.py` / `client.py`: `POST /v1/mcp/plugins/{id}/connect`, `POST /v1/mcp/plugins/{id}/refresh`, `POST /v1/mcp/oauth/callback`.
- Modify `jarvis/app.py:_run_core_v2`: inject `SdkRemoteMcpConnector` (import guarded: `mcp` extra absent => `None` => `mcp_connector_unavailable`), read `JARVIS_MCP_ALLOW_LOOPBACK_HTTP`, and the CC callback base URL `http://127.0.0.1:<ui_port>` (source of `ui_port` for Core: decide env vs. setting, document it in `docs/mcp/plugins.md`).
- Create `tests/fakes/fake_remote_mcp.py`: FastMCP streamable-HTTP app + fake OAuth AS (PRM; AS metadata with/without `authorization_response_iss_parameter_supported`; DCR accepting or rejecting a `refresh_token` grant; PKCE verification; tokens with/without refresh; short expiry; 403 `insufficient_scope`; tool-list mutation + `list_changed`; huge schema; 250 tools; secret-looking error text; cross-origin redirect).

### Out of scope
Catalog merge, gateway and `/v1/mcp/tools*` (Slice 04); CC relay and UI (Slice 06); live Circuit Toolbox (Slice 07); legacy SSE.

### Acceptance criteria
- [ ] Unauthenticated plugin connects; tools normalized with bounds; `rejected_tools` carries codes (name invalid, schema too large, > 200 tools, duplicate).
- [ ] OAuth: 401 -> PRM -> AS metadata (issuer validated) -> DCR -> `authorization_url` with PKCE S256, `state`, `resource`, scope; callback completes; tokens + `expires_at` + client_info sealed in the vault; nothing secret in `public_view`, journal or HTTP bodies.
- [ ] Wrong / replayed / expired `state` -> `mcp_oauth_state_invalid`; wrong `iss` when advertised -> `mcp_oauth_issuer_mismatch`; AS `error=access_denied` -> `auth_status=failed`.
- [ ] No refresh token and expiry passed => `auth_status=expired`, no network attempt at boot, no interactive flow; a call in that state answers `mcp_plugin_reauthorization_required` in < 1 s.
- [ ] Bearer/header strategies send the header only to the plugin origin (asserted on the fake: AS endpoints never receive it); forbidden header names refused.
- [ ] SSRF: private/link-local/metadata/loopback targets (IP literal and DNS-resolved) refused; cross-origin redirect not followed and no auth forwarded; response > 4 MiB aborted.
- [ ] One failing plugin (crash, timeout, malformed JSON-RPC) never affects another plugin nor Core routes; backoff observed; `stop()` <= 5 s.
- [ ] The owner task enters and exits the SDK context in one task (no anyio cancel-scope error in logs).

### Required tests
- `tests/unit/test_mcp_http_policy.py`: address classes, DNS-resolved refusal (monkeypatched resolver), dev flag, byte cap, redirect limit.
- `tests/unit/test_mcp_oauth_adapter.py`: storage round-trip through the vault, expiry restored, non-interactive mode raises, `iss` check, redirect_uri port change => client re-registration.
- `tests/integration/test_remote_mcp_connector.py` (fake server on 127.0.0.1 with the dev flag): full OAuth, no-refresh expiry, step-up 403, bearer, header, `list_changed` => revision +1, malicious payloads, isolation of two plugins, secret sentinel absent from journal/trace/responses.
- `tests/unit/test_mcp_plugin_service.py` (connect / oauth / backoff / boot part) and `tests/unit/test_mcp_protocol_routes.py` (new routes).

### Required evidence for QA
Pytest output; a redacted journal excerpt of one OAuth connect on the fake (codes and ids only); grep for the sentinel across the test run's `trace.jsonl` returning nothing. Agent-trace-analysis not required yet (no model path).

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
