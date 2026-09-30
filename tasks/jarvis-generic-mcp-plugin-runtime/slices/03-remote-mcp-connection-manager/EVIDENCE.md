# Slice 03 — Evidence

Branch `task/jarvis-generic-mcp-plugin-runtime`, base `b2a5eec`. Commits:
`fc5b313` (policy transport), `b927ec1` (OAuth adapter + ports),
`5b934da` (connector, tool normalization, fake server, endpoint hardening),
`5472663` (service lifecycle + routes), `e62e5ba` (Core wiring + contract),
and the commit that adds this file. Date 2026-09-30, Windows 11, Python
3.14.6, `mcp` 1.30.0, foreground pytest
(`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`).

## 1. Pytest

| Command scope | Result |
| --- | --- |
| `tests/unit/test_mcp_catalog.py`, `test_mcp_endpoint_policy.py`, `test_mcp_http_policy.py`, `test_mcp_oauth_adapter.py`, `test_mcp_plugin_domain.py`, `test_mcp_plugin_service.py`, `test_mcp_plugin_store_sqlite.py`, `test_mcp_protocol_routes.py`, `test_credential_vault.py`, `test_v2_architecture.py`, `test_schema_migrations.py`, `test_app.py` (12 files) | **413 passed** |
| `tests/unit/test_*protocol*` + `test_*core*` (9 files) + `tests/integration/test_board_session_e2e.py` | **164 passed** |
| `tests/integration/test_remote_mcp_connector.py` (fake server on 127.0.0.1) | **31 passed** (≈ 56 s) |

No failure outside READINESS §Baseline. One Slice 02 test changed on purpose:
`test_start_resets_connecting_rows_only` → `test_start_resets_live_looking_rows_only`
(Core start now also resets `connected`; see §4).

## 2. Journal excerpt — one OAuth connect on the fake (codes and ids only)

Full `trace.jsonl` of a scratch run (`running_fakes(FakeConfig(auth="oauth"))`:
create → connect → browser approve → callback → disconnect → stop):

```text
mcp.plugin.created {"plugin_id": "127", "endpoint_origin": "http://127.0.0.1:58090"}
mcp.plugin.connecting {"plugin_id": "127", "strategy": "oauth", "interactive": true}
mcp.plugin.authorization_pending {"plugin_id": "127", "iss_supported": true, "ttl_s": 300.0}
mcp.plugin.connected {"plugin_id": "127", "auth_strategy": "oauth", "auth_status": "authorized", "tool_count": 3, "rejected_count": 0, "rejected_codes": []}
mcp.plugin.oauth_completed {"plugin_id": "127", "connection_status": "connected", "auth_status": "authorized"}
mcp.plugin.revoked {"plugin_id": "127"}
mcp.plugin.disconnected {"plugin_id": "127", "credentials_forgotten": 1}
mcp.plugins.stopped {"connections": 0, "cancelled": 0, "duration_ms": 0}
```

Same run: sentinel in trace **False**, OAuth `state` in trace **False**,
authorization `code` in trace **False** (the authorization URL is never
journaled).

## 3. Sentinel grep

`SENTINEL-SECRET-7f3a` is the access/refresh token prefix, the bearer and
header values and the text of the fake's `leak_error` tool. After the test
runs above: `find %TEMP%/pytest-of-Clarice -name trace.jsonl -newer jarvis/app.py`
→ 63 files; `xargs grep -l SENTINEL-SECRET-7f3a` → **0**. In-test checks:
`public_view`, every Core HTTP body of the route e2e test
(`test_core_routes_run_the_oauth_flow_and_never_echo_a_secret`), sealed blob
bytes, and `error_description` of an AS refusal.

## 4. Acceptance → proving test (`tests/integration/test_remote_mcp_connector.py` = IT, `tests/unit/…` = U)

- **Unauthenticated connect, normalized bounded tools, `rejected_tools` codes** —
  IT `test_unauthenticated_plugin_connects_with_normalized_bounded_tools`
  (name invalid, schema > 16 KiB, depth > 12, duplicate), IT
  `test_more_than_200_tools_are_bounded` (250 → 200 + 50
  `mcp_tool_list_too_large`); U `test_mcp_plugin_domain.py` (bounds, 512 KiB,
  description suffix E7, side effects).
- **OAuth 401 → PRM → AS metadata (issuer validated) → DCR → URL with PKCE S256,
  state, resource, scope; callback; tokens + `expires_at` + client_info sealed;
  nothing secret out** — IT `test_full_oauth_flow_seals_tokens_and_leaks_nothing`,
  IT `test_core_routes_run_the_oauth_flow_and_never_echo_a_secret`, U
  `test_mcp_oauth_adapter.py::test_full_interactive_flow_registers_with_pkce_state_resource_and_scope`;
  the fake AS verifies the PKCE verifier. Q2: IT
  `test_refresh_grant_follows_the_as_metadata`, U
  `test_refresh_grant_is_requested_only_when_the_as_lists_it`.
- **Wrong / replayed / expired state → `mcp_oauth_state_invalid`; wrong `iss` →
  `mcp_oauth_issuer_mismatch`; `access_denied` → `failed`** — IT
  `test_bad_state_is_refused[wrong|replayed|expired]`,
  `test_wrong_iss_is_refused_when_advertised` (code never exchanged),
  `test_missing_iss_is_refused_when_advertised`,
  `test_iss_not_advertised_is_not_required`,
  `test_access_denied_marks_the_plugin_failed`; U
  `test_complete_oauth_refusals`, `test_state_is_single_use`,
  `test_expired_state_is_refused`, `test_rfc9207_issuer_check`.
- **No refresh + expiry ⇒ `expired`, no boot network, no interactive flow, call
  → reauth in < 1 s** — IT
  `test_expired_token_without_refresh_needs_reauthorization_without_network`
  (running session and afterwards, request count unchanged),
  `test_boot_with_an_expired_token_makes_no_network_attempt`; U
  `test_stored_expiry_is_restored_and_non_interactive_mode_raises_before_sending`,
  `test_boot_reconnects_only_non_interactive_candidates`.
- **Bearer/header only to the plugin origin; forbidden header names refused** —
  IT `test_static_credentials_go_to_the_plugin_origin_only[bearer|header]`
  (AS receives nothing), `test_cross_origin_redirect_is_not_followed_and_carries_no_auth`;
  header names: U `test_static_credential_refusals` (Slice 02, unchanged).
- **SSRF (IP literal and DNS-resolved), cross-origin redirect, > 4 MiB** — U
  `test_mcp_http_policy.py` (address classes, resolver-injected refusals,
  disguised hosts, dev flag, streamed and declared cap, redirect bound), U
  `test_mcp_endpoint_policy.py` (QA item C inputs), IT
  `test_dns_resolved_forbidden_address_is_refused_before_any_request`,
  `test_hostile_or_broken_servers_get_a_stable_code[/huge]`.
- **Isolation, backoff, `stop()` ≤ 5 s** — IT
  `test_one_failing_plugin_never_affects_another_and_backs_off` (crash,
  malformed JSON-RPC, hanging server; healthy calls < 1 s; delays 0.05/0.1/0.2),
  `test_stop_is_bounded_with_a_hanging_server_and_leaves_no_task`,
  `test_disabled_plugin_is_not_retried`; U
  `test_transport_failures_back_off_then_reconnect_non_interactively`,
  `test_stop_is_bounded_even_with_a_hanging_owner`.
- **Owner task enters and exits the SDK context in one task; no anyio
  cancel-scope error** — both IT isolation/stop tests assert no log record
  mentions "cancel scope" (`caplog` at WARNING).
- Also: `list_changed` → revision +1 (IT `test_list_changed_bumps_the_capability_revision`),
  step-up 403 (IT `test_step_up_403_during_connect_then_reconnect_widens_the_scope`),
  boot reconnect OAuth/static without a new authorization (IT
  `test_boot_reconnects_valid_oauth_and_static_plugins_non_interactively`),
  RFC 7009 revocation (IT `test_disconnect_revokes_then_forgets`, U
  `test_disconnect_revokes_best_effort_then_forgets`), connector absent (U
  `test_app.py::test_mcp_connector_is_none_without_the_sdk`, route 503 test).

## 5. Deviations (all written into `docs/mcp/plugins.md`)

1. `max_redirects=20`, not 3 (ARCH §5.2): httpx counts every `httpx.Auth`
   request in the redirect history; `3` broke every OAuth connection.
2. Core start resets `connected` rows too (not only `connecting`).
3. `connect` 200/202 bodies also carry `plugin`; the callback accepts and
   ignores `error_description`.
4. One authorization per explicit connect (a step-up inside the same connect
   ends `failed`; « Reconnecter » then asks the wider scope).
5. Fake MCP server uses the SDK low-level `Server` + `StreamableHTTPSessionManager`
   (not `FastMCP`) to serve arbitrary schemas, invalid names and 250 tools.
6. `ui_port` for the redirect URI: env `JARVIS_UI_PORT` (the CC's own source).
