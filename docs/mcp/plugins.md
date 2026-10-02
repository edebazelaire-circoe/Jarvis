# MCP plugins and intent-aware tool discovery

Handoff `tasks/jarvis-generic-mcp-plugin-runtime/`, Slice 01 (contract).
**Status: implemented** by Slices 02–08 of `jarvis-generic-mcp-plugin-runtime`
(release facts and final numbers: §15). **Still pending (Slice 07/08 phase B,
live login):** the Circuit Toolbox items of §14 that need an authorized
session, the real Circuit Toolbox `list_tools` budget, the final Brain and
delegated-subagent traces and the Human checks (§15.4). Shipped by Slice 02: the domain
(`jarvis/domain/mcp_plugins.py`, `mcp_endpoint.py`), the v4 registry and sealed
credential store (`jarvis/adapters/sqlite_mcp_plugins.py`), the DPAPI sealer
(`jarvis/adapters/dpapi_sealer.py`), `CredentialVault`, the CRUD part of
`McpPluginService` and the Core routes of §8.1 except `connect`, `refresh`,
the OAuth callback and `/v1/mcp/tools*`. Shipped by Slice 03: the remote
connection and authentication runtime — `PolicyTransport`
(`jarvis/adapters/mcp_http_policy.py`), the OAuth adapter
(`jarvis/adapters/mcp_oauth.py`), `SdkRemoteMcpConnector`
(`jarvis/adapters/remote_mcp.py`), tool normalization
(`normalize_remote_tools`, domain), the connection lifecycle of
`McpPluginService` (§2.2, §3.3-§3.5) and the Core routes `connect`, `refresh`
and `POST /v1/mcp/oauth/callback`. Shipped by Slice 04: relevance and the
bounded `list_tools` response (`jarvis/domain/tool_relevance.py`,
`jarvis/domain/tool_discovery.py`), the `jarvis-tools` gateway
(`jarvis/runtime/tools_gateway_mcp.py`, `python -m jarvis tools-mcp`; §6-§7,
**implemented**), the Core routes
`GET /v1/mcp/tools` and `POST /v1/mcp/tools/call` (§8.1, **implemented**),
and the merged catalog (§5.2, **implemented**). Shipped by Slice 05: the
gateway declared to the Claude conversation brain, to Codex and — by
inheritance, proven by trace — to delegated subagents (§10, **implemented**).
Shipped by Slice 06: the Control Center relay routes, the OAuth callback page
and the « Plugins externes » tab of the MCP dialog (§9, **implemented**).
Slice 07 (phase A): the Drive classification (§11) and the unauthenticated
conformance record of Circuit Toolbox (§14); the live login run is phase B.
Slice 08 (phase A): secret sentinel, restart persistence, re-measured budgets,
release docs (§15). Implementation facts and the deviations from ARCH: §13
(Slice 04), §10.1 (Slice 05), §9.1 (Slice 06), §15 (Slice 08). Binding design:
`tasks/jarvis-generic-mcp-plugin-runtime/docs/06-resolved-architecture.md`
(cited as ARCH §n); where this document and ARCH disagree, ARCH wins and this
document is corrected. Native catalog, descriptors, availability and the
Control Center inspector: [tool-contract.md](tool-contract.md), which this
document extends and never duplicates.

A **plugin** is a remote MCP server the user adds from a URL in the Control
Center. Jarvis holds its definition, its authorization and its connection; the
brain reaches its tools through one Jarvis-owned gateway, `jarvis-tools`, and
never sees a credential. There is no provider-specific code: Circuit Toolbox
(`https://circoetoolbox-server-production.up.railway.app/mcp`) is a
conformance target, not a special case.

## 1. Process topology

Two long-lived processes matter (ARCH §0, contradiction C1 — they are **not**
one process):

| Process | Entry | Server | Auth | Owns for plugins |
| --- | --- | --- | --- | --- |
| **Core** | `python -m jarvis core` → `app.py:_run_core_v2` (`jarvis/app.py:527`) | `LocalProtocolServer` (`jarvis/protocol/server.py:74`), `127.77.0.1:<core_port>` | `Authorization: Bearer <token>` (`server.py:92-99`), token read from the Core token file | plugin registry, credential vault, remote connections, OAuth pending state, tool execution, external catalog revision |
| **Control Center (CC)** | `python -m jarvis control-center` | `ControlCenter` (`jarvis/runtime/control_center.py`), `127.0.0.1:17654` | loopback Origin/Host guard (`_origin_guard`, `control_center.py:1560`; `READ_GUARDED_ROUTES` :239) | the UI, the relay routes `/api/mcp/plugins*`, the browser-facing OAuth callback, the brain agents |

The **gateway** `jarvis-tools` is a stdio MCP server, child of the brain CLI
like the native servers. It reaches Core with the token-file pattern of
`jarvis-display` (`DisplayMcpTarget`, `display_mcp.py:206`; the config file
holds host, port and the token **file path**, never the token;
`CoreLoopbackTransport`, `runtime/core_forwarder.py:47`).

```text
Brain CLI (Claude / Codex)          Control Center                     Core
  └─ stdio jarvis-tools               /api/mcp/tools (merged view) ──►  GET  /v1/mcp/tools
       list_tools: native catalog      /api/mcp/plugins*        ──────►  /v1/mcp/plugins*
         (in-process) + external       /api/mcp/oauth/callback  ──────►  POST /v1/mcp/oauth/callback
         descriptors ─────────────────────────────────────────────────►  GET  /v1/mcp/tools
       call_tool ─────────────────────────────────────────────────────►  POST /v1/mcp/tools/call
                                                                          McpPluginService
                                                                           ├─ registry (SQLite v4)
                                                                           ├─ CredentialVault (sealed)
                                                                           └─ RemoteMcpConnector (mcp SDK)
```

Rules that follow from the code:

- **Relevance ranking runs in the gateway process**, not in Core (C2): Core may
  not import `jarvis.runtime` (`tests/unit/test_v2_architecture.py:119`,
  `test_core_does_not_import_runtime_modules`), so it cannot see the native
  catalog. Ranking and the byte budget are pure domain modules
  (`jarvis/domain/tool_relevance.py`, `jarvis/domain/tool_discovery.py`)
  executed by the gateway; `call_tool` stays a thin proxy to Core.
- **Core layering is unchanged** (C3): Core imports no `httpx`, `aiohttp`,
  `sqlite3`, `mcp` SDK or DPAPI code. Ports live in `jarvis/ports/mcp_plugins.py`;
  adapters are built in `app.py:_run_core_v2` and injected (precedent
  `drive_backend=_drive_backend_from_env()`, `app.py:268,565`). The SQLite
  registry adapter adds exactly one entry,
  `"jarvis.adapters.sqlite_mcp_plugins"`, to `CORE_ADAPTER_IMPORT_EXCEPTIONS`
  (`tests/unit/test_v2_architecture.py:35`).
- **Plugin routes live under `/v1/mcp/*`** (C4): `/v1/tools/call` already
  exists for the voice `CoreToolRouter` (`server.py:153`) and is not reused.
- **Browser closed ⇒ nothing changes for the brain**: the gateway talks to
  Core, and Core keeps the plugin sessions.

## 2. Plugin model

### 2.1 Fields (`McpPlugin`, `jarvis/domain/mcp_plugins.py`)

| Field | Rule |
| --- | --- |
| `plugin_id` | slug `^[a-z0-9][a-z0-9-]{0,31}$`, immutable, never `jarvis-*` |
| `display_name` | ≤ 64 chars, editable; default = `serverInfo.name` or host |
| `endpoint` | normalized https URL (§4.1) |
| `endpoint_origin` | `scheme://host[:port]` |
| `transport` | `streamable_http` only (legacy SSE is not implemented: `mcp_transport_unsupported`) |
| `enabled` | bool |
| `connection_status` | `disconnected` \| `connecting` \| `connected` \| `error` |
| `auth_status` | `unknown` \| `not_required` \| `required` \| `authorizing` \| `authorized` \| `expired` \| `failed` |
| `auth_strategy` | `none` \| `oauth` \| `bearer` \| `header` |
| `credential_ref` | opaque `cred_<32 hex>` or null — **never a secret**, never in a UI/API payload |
| `icon_url` | ≤ 512 chars, from `serverInfo.icons` when advertised, kept only if it passes the **static endpoint policy** of §4.1 without the loopback flag (`icon_url_from`, ARCH §16 E23), else `null`; **never fetched by Core** |
| `server_identity` | `{name, version, protocol_version}` from `initialize`, bounded |
| `capability_revision` | +1 at every tool-list change |
| `tools` | last discovered descriptors: the JSON form (`ExternalToolDescriptor.to_payload()`, §5.1) of the normalized tools, ≤ 200 |
| `rejected_tools` | bounded `[{name, code}]` of refused remote tools |
| `last_discovered_at`, `created_at`, `updated_at` | timestamps |
| `last_error_code` | a stable code of §8 only, never a remote body |

`public_view()` is the UI/API shape: every field except `credential_ref`.

**Identity.** `plugin_id_for(endpoint, taken)`: first DNS label of the host,
lowercased, `[^a-z0-9-]` → `-`, trimmed to 32; a `jarvis-` prefix is refused
(→ `p-…`); a collision appends `-2`, `-3`… Circuit Toolbox →
`circoetoolbox-server-production`. The same normalized `endpoint` twice is
`409 mcp_plugin_duplicate`.

### 2.2 States and transitions

Two independent axes (locked intent 2): **enabled** (user's choice) and
**connection/auth** (what is true on the wire).

- `enabled` never changes `connection_status`; `disconnect` never changes
  `enabled`.
- **Disable** keeps credentials and the row; the plugin's tools leave every
  catalog view and `list_tools`, and calls answer `mcp_plugin_disabled`.
- **Create**: a new plugin starts `enabled=True`, `connection_status=
  disconnected`, `auth_status=unknown`, `auth_strategy=none`, no credential
  (ARCH §16 E13); creating never touches the network.
- **Disconnect**, in this order: (1) the connection owner is stopped (≤ 5 s)
  and writes nothing more; (2) for an OAuth plugin whose AS metadata
  advertised a `revocation_endpoint`, a **best-effort RFC 7009 revocation** of
  the refresh then access token — a failure or a 10 s timeout is journaled by
  code only (`mcp.plugin.revocation_failed`) and **never blocks** what follows
  (ARCH §16 E10; Circuit Toolbox advertises none: local forget only). The
  tokens are sent **only** to an endpoint on the origin (scheme, host, port)
  of the issuer their client registration is bound to (`client_info.issuer`,
  SEP-2352); any other endpoint, or a registration without an issuer, is
  refused before any request (`mcp_oauth_issuer_mismatch`, journaled by code); (3) the
  row becomes `connection_status=disconnected`, `auth_status=unknown`,
  **`auth_strategy=none`**, `credential_ref=null`, `last_error_code=null`
  (E13); (4) **every** sealed credential row of the plugin is deleted.
  `enabled`, the display name, the discovered tools and the row itself are
  kept: disconnect **never changes `enabled`**, in either direction. The next
  `connect` starts from `auth_status=unknown`.
- **Remove** = stop the connection + best-effort revocation + delete the row
  and its credential rows in **one** `BEGIN IMMEDIATE` transaction (the
  shared `sqlite_state.immediate_transaction` helper, also used by the Board
  store — E13).
- **Start never raises** on a store failure (E13): an unreadable registry is
  journaled `mcp.plugin.store_failed` and Core keeps running; every plugin
  route then answers the same store error (`500 mcp_plugin_store_unreadable`
  or `mcp_plugin_store_failed`) with its table and key.
- On Core start, rows left `connecting` **or `connected`** are rewritten
  `disconnected` (a Core that stopped or crashed holds no session; `auth_status`
  and `last_error_code` are kept — Slice 03 widened the Slice 02 rule, which
  only covered `connecting`). Then Core reconnects in background, **never
  interactively**, every `enabled` plugin whose strategy is `none` with
  `auth_status=not_required`, `oauth` with `authorized`, or `bearer`/`header`
  with `unknown`/`authorized` (ARCH §16 E12). An `oauth` plugin whose stored
  token is expired **and** has no refresh token becomes `auth_status=expired`,
  `connection_status=disconnected`, `last_error_code=
  mcp_plugin_reauthorization_required` **without any network attempt**
  (`mcp.plugin.expired_at_boot`). On Core stop, `McpPluginService.stop()`
  closes every plugin connection within **5 s total** (stragglers are
  cancelled) and writes `disconnected` for each (ARCH §4.1).
- A failed connection owner ⇒ `connection_status=error` + `last_error_code`,
  reconnect **non-interactively** with backoff `(1, 2, 5, 10, 30, 60)` s,
  capped, while `enabled` — only for transport failures
  (`mcp_remote_unreachable`, `mcp_remote_timeout`, `mcp_remote_protocol`,
  `mcp_remote_tls`, `mcp_response_too_large`, a dropped session). Any other
  code (authorization, SSRF refusal, `mcp_transport_unsupported`) stops
  retries. Authorization outcome of a failure:

  | Failure | `auth_status` | `connection_status` |
  | --- | --- | --- |
  | `mcp_plugin_reauthorization_required`, `bearer`/`header` (401/403) | `failed` | `error` |
  | same, strategy `none` (the server wants auth; also `auto` without a vault) | `required` | `error` |
  | same, `oauth` plugin that was `authorized`/`expired` (token expired, 401 or step-up outside a `connect`) | `expired` | `disconnected` |
  | same, during an `oauth` flow (second authorization requested, SDK OAuth error) | `failed` | `error` |
  | `mcp_oauth_timeout` (no browser return within the 300 s TTL) | `failed` | `error` |
  | `mcp_oauth_denied`, `mcp_oauth_issuer_mismatch` | `failed` | `error` |
  | **any** code while the connection's interactive flow is open (authorization URL issued, not yet connected — e.g. `mcp_remote_timeout` on the code exchange) | `failed` | `error`, **no retry** |
  | `mcp_vault_unavailable` | `required` | `error` |
  | any other code | unchanged | `error` |
- A **local** failure of the connection owner — a store error, a bug in
  Jarvis's own code running inside the connector context (normalization,
  re-listing, row writes), or a vault write failing under the SDK's OAuth flow
  — is **not** a remote failure: the connector re-raises it unchanged (never
  classified, never `mcp_remote_protocol`), the owner journals
  `mcp.plugin.owner_crashed` (`exception_type`, `code` when it has one; the
  text only for a store error, which carries table and key), writes
  `connection_status=error`, and **does not retry**. A store failure keeps
  its own code: `connect` answers it (500 with table and key) and the row's
  `last_error_code` stays `null`. Any other local bug ⇒ `connect` answers
  `500 mcp_plugin_internal_error` in Core's `{"error": {"code", "message"}}`
  shape with a Jarvis sentence (no exception text), and the row's
  `last_error_code` is `mcp_plugin_internal_error` (ARCH §16 E18). Transport
  failures name their **leaf** exception types, never `ExceptionGroup`, and
  keep the cause chained.
- `notifications/tools/list_changed` ⇒ re-list, bump `capability_revision`
  and the external catalog revision.

One owner `asyncio.Task` per connected plugin holds the SDK transport (it is
anyio-based and must be entered and exited in one task); other tasks call
tools on its `ClientSession` concurrently (ARCH §4.2). Every request of the
session is *guarded*: the SDK silently drops some read errors (unparsable
JSON, a cut SSE stream, a policy refusal while reading) and would leave the
request waiting for its timeout, so the adapter records the first failure and
fails every pending or later request with that code at once. A replaced or
stopped connection writes nothing more to the plugin row.

### 2.3 Persistence

`jarvis.sqlite3` (Core-owned), migration **v4** in
`jarvis/adapters/sqlite_state.py` (`_SCHEMA_VERSION` 3 → 4, additive), tables
`mcp_plugins` (row per plugin, `data` = canonical `to_payload()`) and
`mcp_credentials` (sealed blobs, `scheme` = `dpapi-user-v1`), frozen snapshot
`tests/schema/jarvis_state.v4.sql`, automatic `<db>.v3.bak` before migrating
(repository rule, `CLAUDE.md`). DDL: ARCH §3.2. No product row in the
migration.

## 3. Authorization and the credential vault

### 3.1 Strategies

| Strategy | When | What is sent |
| --- | --- | --- |
| `none` | the server answers without auth | nothing |
| `oauth` | the server answers 401 with protected-resource metadata | `Authorization: Bearer <access token>` from the OAuth flow (§3.3) |
| `bearer` | manual fallback for a non-standard server | `Authorization: Bearer <value>` |
| `header` | manual fallback | `<header_name>: <value>` |

`connect(strategy="auto")`: a plugin holding a `bearer`/`header` credential
connects with it; otherwise the connection carries the OAuth provider and the
outcome says which strategy applied — no 401 during the handshake ⇒ `none` /
`not_required`, tokens obtained ⇒ `oauth` / `authorized`. Without a vault,
`auto` connects without the OAuth provider (a 401 then ends `required`), and
`strategy="oauth"` is refused `409 mcp_vault_unavailable`. `connect` refuses a
disabled plugin (`409 mcp_plugin_disabled`). Manual
fallback (`PUT …/credential`): `header_name` matches `^[A-Za-z0-9-]{1,64}$` and
is not one of `host`, `cookie`, `content-length`, `transfer-encoding`,
`connection`, `mcp-session-id`, `mcp-protocol-version`; `value` ≤ 4096 chars,
no CR/LF, never echoed. Static headers are set on the MCP request only, never
on the HTTP client, so authorization-server requests never carry them, and
they go only to the plugin origin.

### 3.2 Vault

- `CredentialVault` (`jarvis/core/credential_vault.py`) over two ports:
  `SealedSecretStore` (rows of `mcp_credentials`) and `Sealer`
  (`available`, `scheme`, `seal`, `unseal`). Adapters: `DpapiSealer` (Windows
  DPAPI CurrentUser via `ctypes`, `CRYPTPROTECT_UI_FORBIDDEN`, entropy
  `jarvis-mcp-v1`), `UnavailableSealer` elsewhere, `FakeSealer` in tests.
- The sealed payload is bound to `{plugin_id, endpoint_origin}`; a mismatch
  makes `get_secret` return nothing (a copied blob never authorizes another
  plugin or origin).
- Sealer unavailable ⇒ every strategy but `none` is refused with
  `409 mcp_vault_unavailable`. **No plaintext fallback.**
- `jarvis/runtime/credentials.py` is **not** reused: it keeps API keys in
  plaintext in the Control Center settings file and hands them to CC code.

**Threat model** (same as `display_mcp.py:37-41`): the brain runs as the same
OS user as Core. DPAPI CurrentUser protects against other users and copies of
the database, not against a malicious same-user process. The guarantee is: **no
secret in model context, tool descriptors, API/UI payloads, journals or
traces.**

### 3.3 OAuth

Built on `mcp.client.auth.OAuthClientProvider` (mcp 1.30), subclassed, never
reimplemented. The SDK already does protected-resource discovery, RFC 8707
`resource` binding, AS issuer validation, dynamic client registration, PKCE
S256, a constant-time `state` check (`secrets.compare_digest`), scope from
`WWW-Authenticate`/metadata, and step-up on `403 insufficient_scope`. Jarvis
adds what the SDK lacks (C9), including **single use** of `state`, which comes
from Jarvis's own pending authorization (§3.3 step 4), not from the SDK:

- **RFC 9207 `iss` check**: when the AS metadata advertises
  `authorization_response_iss_parameter_supported`, the callback `iss` must
  equal the metadata issuer, else `mcp_oauth_issuer_mismatch`.
- **Expiry persistence**: tokens are stored with `expires_at`, and restored
  with it (the SDK restores them without an expiry).
- **Non-interactive mode** (§3.4).

Client registration: `client_name="Jarvis"`,
`redirect_uris=["http://127.0.0.1:<ui_port>/api/mcp/oauth/callback"]` (RFC 8252
loopback), `token_endpoint_auth_method="none"`, `response_types=["code"]`,
`grant_types=["authorization_code"]` plus `"refresh_token"` **only when** the
AS metadata `grant_types_supported` lists it (READINESS Q2). A UI-port change
makes the stored `redirect_uris` mismatch ⇒ Core drops the client info and
re-registers. **`ui_port` source (decided in Slice 03): the environment
variable `JARVIS_UI_PORT`** (default `17654`), read by Core in
`app.py:_mcp_oauth_redirect_uri` — the same variable the Control Center reads
for its own port, and both processes are started from the same environment.
Core journals the redirect URI it uses (`mcp.plugins.connector_ready`).

Sealed OAuth payload (`kind: "oauth"`): `{tokens, expires_at, client_info,
issuer, iss_supported, revocation_endpoint, redirect_uri}` — `issuer` is the
raw `issuer` string of the AS metadata (compared to the callback `iss`),
`revocation_endpoint` feeds the RFC 7009 revocation of §2.2. `issuer`,
`iss_supported` and `revocation_endpoint` come **only** from AS metadata the
SDK has **accepted** (issuer validated against the expected one, RFC 8414
§3.3) and are sealed **with the tokens that server issued**, in the same
write (`set_tokens`); a metadata response that is merely read — then
rejected, or followed by an abandoned consent — changes nothing stored. When
the protected resource names **another** authorization server, the SDK drops
the registration bound to the old issuer and its tokens (SEP-2352); Jarvis
then forgets them in the vault too (tokens, `expires_at`, `client_info`,
`issuer`, `iss_supported`, `revocation_endpoint`), so a later Disconnect has
nothing to send anywhere.

Interactive flow (only inside an explicit `connect`):

1. `POST /v1/mcp/plugins/{id}/connect` starts the connection owner task; the
   SDK redirect handler registers a pending authorization
   `{state, plugin_id, expires_at = now + 300 s, expected_issuer,
   iss_supported}` and the plugin becomes `auth_status=authorizing`.
2. Within 20 s, `connect` answers `200 {"status":"connected","plugin"}`, or
   `202 {"status":"authorizing","authorization_url","plugin"}` (the `plugin`
   public view is an addition to ARCH §4.3). No outcome within 20 s ⇒ the
   attempt is stopped, `504 mcp_remote_timeout`. A failure answers its own
   code and status (§8.2).
3. The UI opens `authorization_url`; the user consents; the AS redirects the
   browser to the CC `GET /api/mcp/oauth/callback?code&state&iss&error`, which
   relays `POST /v1/mcp/oauth/callback`.
4. `complete_oauth`: unknown, expired or already used `state` ⇒
   `mcp_oauth_state_invalid` (single use); `error=` from the AS ⇒
   `auth_status=failed`, `mcp_oauth_denied` (only an `error` matching
   `[a-z_]{1,64}` is quoted back; `error_description` is accepted and ignored,
   never journaled nor echoed); a wrong or missing advertised `iss` ⇒
   `mcp_oauth_issuer_mismatch` and the code is never exchanged; else the SDK
   exchanges the code (PKCE verifier), the tokens are sealed, and the call
   answers the plugin once the connection is established or failed (at most
   15 s; after that, the state as it is).
5. No browser return within the TTL ⇒ the owner ends the flow with
   `mcp_oauth_timeout`, `auth_status=failed`, `connection_status=error`, no
   retry; the UI offers « Relancer l’autorisation » (never the manual token
   form: an unanswered consent is not a refusal).

**The consent wait is not a network wait** (S7 generic fix, ARCH §16 E22).
The SDK awaits the browser callback *inside* the `initialize` request (or a
`tools/list` page, on a step-up). The OAuth provider wraps that wait in the
session's `consent_window()`, and the session's budget clock stops while the
window is open: the 30 s `initialize`/list budget (ARCH §5.2) covers only the
network exchanges before and after the consent, and the consent itself is
bounded by the pending-authorization TTL (300 s) alone. The httpx connect/read
bounds are per network operation and never run during the wait. A failure of
any kind while the interactive flow is open (URL issued, not yet connected)
is **never** retried: a non-interactive reconnect cannot finish an
authorization and would only turn the plugin `failed` behind the user's back.
The live Circuit Toolbox run of Slice 07 hit exactly that before the fix
(`mcp_remote_timeout` at 30 s while the user was on the consent page, then
`mcp_plugin_reauthorization_required` from the backoff retry).

**One authorization per explicit connect.** A second authorization request in
the same connection (e.g. a `403 insufficient_scope` step-up on `tools/list`
right after the first consent) is not opened: the plugin ends
`auth_status=failed`, `mcp_plugin_reauthorization_required`. The next
« Reconnecter » starts with the stored token, meets the same 403, and the SDK
builds the authorization URL with the wider scope of `WWW-Authenticate` — the
UI always has exactly one URL to open.

**No refresh token** (Circuit Toolbox advertises only `authorization_code`):
at expiry the plugin becomes `auth_status=expired`,
`connection_status=disconnected`, and the UI offers « Reconnecter » (a new
interactive flow).

### 3.4 Non-interactive rule

Boot reconnect, backoff reconnects and **every tool call** run
non-interactively: an authorization need raises at once ⇒
`auth_status=expired`, code `mcp_plugin_reauthorization_required`. **A tool
call never waits on a browser.** Concretely (`JarvisOAuthProvider`): a stored
token past its `expires_at` with no refresh token raises **before any request
is sent**; a 401 or `403 insufficient_scope` raises on that response, without
metadata discovery, registration or browser. Once a connection is
established, its prompt is disarmed: later 401s during tool calls are
non-interactive too. Core's `invoke` (the call primitive Slice 04's `call`
builds on) checks `enabled`, `auth_status != expired` and a live session
before any network, so a call on an expired plugin answers
`409 mcp_plugin_reauthorization_required` at once.

## 4. Endpoint policy and HTTP transport

### 4.1 Endpoint validation (`jarvis/domain/mcp_endpoint.py`)

`validate_endpoint(raw, *, allow_loopback_http)` normalizes the URL or refuses
it with a reason (ARCH §16 E4). **Syntax** problems ⇒ `mcp_endpoint_invalid`:

- scheme other than `https` (http only when the host resolves to loopback
  **and** `allow_loopback_http`);
- userinfo present;
- any fragment; any query key matching `token|key|secret|auth|password|sig`
  (case-folded);
- length > 2048; a non-ASCII host that is not IDNA-encodable;
- a `%` in the host (percent-encoding, IPv6 zone id) or port `0`;
- a host that *looks* like an IPv4 address but is not in canonical dotted form
  and decodes to a public address (`https://134744072/` = 8.8.8.8), or does not
  decode (`1.2.3.4.5`, `example.123`, `09.0.0.1`). Such hosts are decoded like
  `inet_aton` does (decimal `2130706433`, hex `0x7f000001`, octal
  `0177.0.0.1`, short `127.1`, `0`); a forbidden result is
  `mcp_endpoint_forbidden` (Slice 03, from the Slice 02 QA).

A **forbidden address** ⇒ `mcp_endpoint_forbidden`, whether it is an IP-literal
host refused here (`is_forbidden_address`) or a DNS-resolved address refused by
`PolicyTransport` (§4.2). The host name `localhost` (and `*.localhost`) is
classified as loopback without DNS: forbidden unless `allow_loopback_http`.

Normalization: scheme and host lower-cased, IDNA host in ASCII (`xn--…`),
default port dropped, empty path → `/`, query kept verbatim. Duplicate
detection compares the normalized form.

`allow_loopback_http` = environment `JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`
(development only, read in `app.py`, journaled at Core start).

**Icon policy (ARCH §16 E23).** Core never fetches a plugin icon, but the
Control Center's browser does. `icon_url_from` (domain) therefore keeps an
advertised icon only if `validate_endpoint(url, allow_loopback_http=False)`
accepts it — the same static checks, **never** relaxed by the development
flag: https only; no private, loopback, link-local, metadata or disguised IP
literal; no `localhost`/`*.localhost`; no userinfo; no credential-like query
key; no fragment; plus ≤ 512 ASCII printable characters. The URL is kept as
advertised (not normalized). A refused icon becomes `null` and the card draws
its letter tile. `McpPlugin.public_view()` applies the same filter, so a row
written before E23 never hands a refused icon to the UI. No DNS check: a
public name that resolves privately is the browser's request, bounded by
`referrerpolicy=no-referrer` and the page CSP, and accepted as V1 residual
risk like §4.2's rebinding.

`is_forbidden_address(ip)`: `not ip.is_global`, or in `100.64.0.0/10`,
`169.254.0.0/16`, `fd00::/8`, or an IPv6 that carries a forbidden IPv4 —
`::ffff:0:0/96` mapped, NAT64 `64:ff9b::/96` and `64:ff9b:1::/48`,
IPv4-compatible `::/96`, 6to4, Teredo (stdlib `ipaddress`; `::127.0.0.1` and
`64:ff9b::a9fe:a9fe` are `is_global` for Python, hence the explicit check).

### 4.2 `PolicyTransport` (`jarvis/adapters/mcp_http_policy.py`)

One `httpx.AsyncClient`, handed to the SDK, carries **every** request of a
plugin (MCP, protected-resource metadata, AS metadata, registration, token):

- resolves the host (`loop.getaddrinfo`) and refuses when **any** resolved
  address is forbidden (loopback only under the development flag) —
  `mcp_endpoint_forbidden`;
- decodes IPv4-looking hosts and refuses `%` in the host or port `0` before
  any DNS query (same rules as §4.1);
- refuses non-https except under that flag;
- caps every response body at `MAX_RESPONSE_BYTES = 4 MiB` (streamed counter
  ⇒ `mcp_response_too_large`);
- `max_redirects=20` (httpx default) — **deviation from ARCH §5.2's `3`**:
  httpx appends every request of an `httpx.Auth` flow to the redirect
  history, and one OAuth flow makes up to ~12 requests (discovery fallbacks,
  registration, token, retry), so `3` aborts every OAuth connection with
  `TooManyRedirects`. The SDK follows only same-origin, method-preserving
  redirects and never forwards the bearer to another origin; a cross-origin
  redirect answers `mcp_remote_protocol` and the other origin receives
  nothing; `trust_env=False` (no environment proxy). The same `20` is also
  the SDK's **same-origin redirect budget for MCP requests**
  (`mcp.shared._httpx_utils.stream_within_origin` follows at most
  `client.max_redirects` redirects, then hands back the redirect response as
  a non-success): a same-origin redirect loop stops after **21 requests**
  (the original plus 20 followed) and answers `mcp_remote_protocol`;
- timeouts: connect 10 s, read 60 s (tool call), total 30 s for
  `initialize`/`list_tools`.

Accepted V1 residual risk: DNS rebinding between Jarvis's resolution and
httpx's connect.

## 5. External tool descriptors

### 5.1 Normalization (`normalize_remote_tool`, domain)

Remote schemas and descriptions are **untrusted data**. Each remote tool
becomes an `ExternalToolDescriptor` or a rejection:

| Field | Rule |
| --- | --- |
| `tool_id` | `<plugin_id>.<name>` (stable namespacing: two plugins' `search` never collide) |
| `plugin_id`, `name` | wire `name` must match `^[A-Za-z0-9_.-]{1,128}$`, else rejected `mcp_tool_name_invalid` |
| `title` | `title` or `annotations.title`, ≤ 80 chars, control chars stripped |
| `description` | ≤ 4 096 UTF-8 bytes **including** the ` …[tronqué]` suffix added when cut (cut on a character boundary; ARCH §16 E7) |
| `input_schema` | an object schema, compact JSON ≤ 16 KiB, depth ≤ 12, else rejected `mcp_tool_schema_too_large`; `properties` (when present) an object whose values are objects and `required` (when present) a list of strings, else rejected `mcp_tool_schema_invalid` (QA 2 of Slice 04: such a schema made `parameters_of` raise and took down `list_tools` and `/api/mcp/tools`) |
| `output_schema` | kept if ≤ 16 KiB, else dropped |
| `side_effect` | `read` if `readOnlyHint` is true; else `write` if `destructiveHint` is false; else `destructive` (MCP default) |
| `idempotent` | `idempotentHint`, default false |
| `atomicity` | `external` |
| `open_world` | `openWorldHint`, default true |

Per plugin: ≤ **200 tools** and ≤ **512 KiB** of normalized descriptors; tools
beyond are rejected `mcp_tool_list_too_large`. A duplicate wire name inside one
plugin: the second is rejected. Every rejection is kept in `rejected_tools`
(`{name, code}`), shown in the UI, never sent to the model.
`list_tools_all()` follows `nextCursor` over at most 10 pages. A wire name
that is refused is kept in `rejected_tools` as a printable string of at most
128 characters (`?` when there is none). `mark_connected` replaces a
`display_name` still equal to the host by `serverInfo.name`; a name the user
chose is kept. The first icon of `serverInfo.icons` that passes the icon policy (§4.1) becomes `icon_url`.

### 5.2 In the catalog

`mcp_catalog.describe_external_tool()` maps a descriptor to the §2 shape of
[tool-contract.md](tool-contract.md) (`server = plugin_id`,
`qualified_name = tool_id`, `category = "external"`, `invocation =
"managed_external"`, `registration = "managed"`). `merge_external()` adds the
enabled ∧ connected plugins' tools to the native catalog; Core unreachable ⇒
one `unavailable` entry `{"server": "plugins", "category": "external",
"error": "core_unreachable"}`, natives unaffected. Availability of a plugin
server: tool-contract §4.3 — for a plugin, the state `advertised` means
**enabled ∧ connected** (offered by `list_tools`, callable through `call_tool`
now), never "declared to the CLI" (ARCH §16 E5, E11). **One catalog**: the Control Center, the
inspector and `list_tools` all read these views; no frontend copy.

## 6. Model-facing discovery: `jarvis-tools`

### 6.1 The server

**Status: implemented (Slice 04)**; declared to the Claude conversation
profile and to Codex by Slice 05 (§10, **implemented**).

`jarvis/runtime/tools_gateway_mcp.py`, CLI `python -m jarvis tools-mcp`,
stdio. It exposes **exactly two tools** (strict schemas,
`additionalProperties: false`):

```text
list_tools(intent: str [1..500 chars], cursor: str | null = null, limit: int [1..60] = 30) -> structured
call_tool(tool_id: str, arguments: object = {}) -> untyped
```

`tool_id` matches `^[a-z0-9][a-z0-9-]{0,31}\.[A-Za-z0-9_.-]{1,128}$` (a plugin
tool) or starts with `mcp__` (a native name, refused at call time, §7).

Metadata: `list_tools` — label « Trouver les outils utiles », `read`,
idempotent, atomicity `none`, `structured`; `call_tool` — label « Appeler un
outil de plugin », `destructive`, not idempotent, atomicity `external`,
`untyped`. Category `general`, `registration="jarvis"`.

Descriptions (French, short) say: call `list_tools` again whenever a new need
appears (repeated discovery is normal: mail → address → user id);
`recommended` entries are immediately callable, no second lookup;
`direct_native` tools are called by their `call_as` name, never through
`call_tool`. **Budgets (tested):** the two tools' name + description + input
schema ≤ **2 500 B**; server instructions ≤ **1 200 B**.

### 6.2 `list_tools(intent)` algorithm

Runs in the gateway process (C2):

1. **Native candidates**: `mcp_catalog.cached_catalog()` filtered to the
   servers actually declared to this brain launch
   (`JARVIS_TOOLS_NATIVE_SERVERS`), excluding `jarvis-tools` itself. Entry id =
   `qualified_name` (`mcp__<server>__<name>`), `invocation="direct_native"`,
   `call_as` = that name. **Operator servers (`jarvis-drive`) are never
   included** (C8: Jarvis cannot prove they are declared; the model still sees
   them natively through the CLI).
2. **External candidates**: `GET /v1/mcp/tools?since_revision=<cached>` (the
   gateway caches by revision). Core unreachable ⇒ natives only and
   `notes: ["plugins_unavailable"]`.
3. **Rank** with `tool_relevance.rank(intent, index)` (§6.4). The gateway
   keeps the tokenized documents (`tool_relevance.build_index` → `RankIndex`)
   for the current `catalog_revision` and rebuilds them only when it changes
   (journal `tools.index_built`). A malformed tool item from Core (missing or
   mistyped `tool_id`, `plugin_id`, `name`, `description`…, or an
   `input_schema` of the wrong shape — `mcp_catalog.external_descriptor_ok`,
   shared with `merge_external`) is skipped, never the whole list: natives and
   the valid externals stay listed, and `tools.external_item_skipped {code:
   mcp_tool_descriptor_invalid, count, tool_ids}` is journaled once per
   revision. The Control Center's `merge_external` skips the same items
   (journal `mcp.catalog.descriptor_skipped`, once per skipped set), and
   `parameters_of` reads any unreadable schema node as `any` instead of
   raising.
4. **Pack** with `tool_discovery.build_list_response(...)` (§6.3).

### 6.3 Response contract

Structured output (FastMCP `structuredContent`, shown to the model as compact
JSON, tool-contract §10.3):

```json
{"intent": "envoyer un mail à Paul",
 "catalog_revision": "n1a2b3c4d.e17",
 "recommended": [{"id": "example-mail.send_message", "name": "send_message",
                  "invocation": "managed_external", "source": "Example Mail",
                  "description": "…", "input_schema": {"type": "object", "…": "…"},
                  "side_effect": "destructive"}],
 "others": [{"id": "mcp__jarvis-console__settings_get", "summary": "…",
             "source": "jarvis-console", "side_effect": "read",
             "invocation": "direct_native"}],
 "next_cursor": null, "total": 12, "native_total": 30, "notes": []}
```

`direct_native` entries also carry `call_as`. **Natives are never in
`others`** (ARCH §16 E21): the CLI already shows every native name in its
deferred tool list, so a compact native card only costs context. Bounds:

| Part | Rule |
| --- | --- |
| `recommended` | ≤ **5** entries, of which ≤ **2** `direct_native` (E21); only score > 0 **and** ≥ 0.35 × top score; FULL `description` + `input_schema` (natives keep it, E17/E19); packed greedily while the recommended part ≤ **16 KiB**. A tool whose full entry alone exceeds 16 KiB is never recommended: it stays callable and, if external, appears in `others` with `"detail": "too_large"` |
| `others` | every remaining accessible **external** tool, rank order then id; `summary` = first description line ≤ 120 chars; `source` = plugin display name; page size `limit` |
| `total` / `native_total` | `total` = the external tools the response pages over (recommended externals + every `others` page); `native_total` = the accessible natives, ranked but only ever recommended |
| whole response | ≤ **24 576 bytes**, measured as `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` encoded UTF-8; `others` is filled until that bound |
| `next_cursor` | urlsafe-base64 JSON `{r: catalog_revision, o: offset, h: sha1(intent)[:8]}`, or null; `r` is the same **string** as `catalog_revision` |
| `catalog_revision` | the string `n<native fingerprint, 8 chars>.e<external revision>` — this is the only form the model ever sees (ARCH §16 E6); the integer form exists only on Core's `/v1/mcp/*` routes (§8.1) |

- A cursor whose revision differs from the current one restarts at offset 0
  with `notes: ["catalog_changed"]`.
- A cursor issued for another intent, unreadable, or with a negative offset
  ⇒ `mcp_cursor_invalid` (the next step « rappelle list_tools sans curseur »
  is added once, by the gateway).
- An intent empty after folding ⇒ `recommended: []`, `others` alphabetical.
- Normal use never needs a second lookup for a recommended tool; there is **no
  `get_tool`**.
- **A recommended native keeps its full `input_schema` (ARCH §16 E17, decided
  by the Slice 05 measurement).** On the real CLI (Claude Code 2.1.285) the
  native servers *and* `jarvis-tools` are deferred behind ToolSearch (the
  session's `deferred_tools_delta` lists them), yet a `direct_native` tool is
  callable by its `call_as` straight after `list_tools`, without ToolSearch:
  the CLI accepts the call of a deferred, unloaded tool. The schema returned
  here is then the only one the model has, so it stays.
- **Native context cost (ARCH §16 E21, QA rework of Slice 04).** Natives
  never appear in `others`, and at most two are recommended (same 0.35
  threshold). Measured on the three EVIDENCE intents (real Core, fake remote
  plugin, natives `jarvis-console` + `jarvis-display`): « répondre au dernier
  mail de Paul » 13 082 → **7 797 B**, « trouver l'adresse email de Paul »
  11 236 → **5 729 B**, « archiver un mail » 10 697 → **5 408 B**.

### 6.4 Relevance (`jarvis/domain/tool_relevance.py`)

**Status: implemented (Slice 04).** Quality gates
(`tests/unit/test_tool_relevance.py`): `tests/fixtures/tool_intents.json`, 26
FR/EN intents, recall@3 = 0.923 (≥ 0.9); and the **regression** set
`tests/fixtures/tool_intents_regression.json` (QA rework: 20 intents, another
author persona, Graph-style camelCase tools), recall@3 = 0.900 (≥ 0.8; 0.600
before the vocabulary rework). It is **not** a held-out set: its intents
paraphrase the misses QA published, so it guards that vocabulary and says
nothing about fresh wording (see the known V1 limit in §7). No more
vocabulary tuning (agent 0, QA 2).

Pure Python, stdlib only (no reusable ranking helper exists; SQLite FTS5 is
optional in `markdown_memory.py` and forbidden in domain):

- `fold`: NFKD, combining marks dropped, casefold. `tokens`: split on
  non-alphanumerics and snake/camel/kebab boundaries, fold, drop FR/EN stop
  words, light stem (strip one of `s`, `x`, `es`, `ing`, `ed`, `ment`,
  `tion→t`).
- Small bilingual synonym groups (mail/email/courriel/message; envoyer/send;
  agenda/calendar/calendrier/evenement/event/meeting/reunion;
  contact/personne/people/user; fichier/file/document/doc;
  chercher/search/find/trouver/lookup; lire/read/get/fetch;
  creer/create/add/ajouter/new; supprimer/delete/remove;
  modifier/update/edit — Slice 04 adds a few members to these groups
  (inbox, rdv, adresse/address, rechercher, afficher/show, archiver…) and
  three groups: lister/list, reglage/setting/parametre, brouillon/draft,
  ecrire/write/rediger); query expansion weight 0.6. The QA rework adds
  reply/répondre/réponds/réponse, forward/transférer/« faire suivre »,
  phone/téléphone/numéro/tel/mobile, task/tâche/todo/« à faire »,
  attachment/« pièce jointe »/PJ, folder/dossier, share/partager,
  download/télécharger, upload/téléverser/« envoyer un fichier »,
  schedule/planifier/programmer, cancel/annuler, and retrouver in the search
  group. A **multi-word member** (`PHRASES`) expands its group only when its
  folded words follow each other in the intent (stop words included, so « à
  faire » works); its words alone expand nothing (« envoyer un mail » never
  pulls `upload`).
- Camel split keeps the plural `s` of an acronym: « PDFs » → `pdf`, « URLs »
  → `url`, « IDs » → `ids` (never « PD » + « Fs »); « HTTPServer » →
  `http`, `server`.
- Light stem as implemented (Slice 04): one plural (`s`, `x`, or `es` after
  s/x/z/ch/sh), **then** one derivational suffix (`tion`→`t`, `ment`, `ing`,
  `ed`), **then** a final `e`, each step only when ≥ 3 letters remain. ARCH
  §7.4 says "strip one of"; chaining is needed for « événements » /
  « événement » and « messages » / « message » to share a stem.
- BM25F-style: k1 = 1.2, b = 0.75; field weights name 3.0, label 2.0,
  parameter names 1.5, description 1.0, parameter descriptions + enum values
  0.75; IDF over the accessible set of the call.
- Deterministic: tie-break `(-score, source_order, id)`; no randomness, no
  clock.
- Quality gate: a fixture corpus (native catalog + fake Circuit-like tools),
  ≥ 20 FR/EN intents, recall@3 ≥ 0.9.

## 7. `call_tool` semantics

**Status: implemented (Slice 04).**

- `tool_id` starting with `mcp__` (a native qualified name) ⇒ tool error
  `native_tool_call_directly` carrying `call_as`: native tools are called
  directly, never proxied.
- Otherwise the gateway posts Core `POST /v1/mcp/tools/call {tool_id,
  arguments, caller: {agent, native_servers_count?}}`.
- Core checks, before any network: the plugin is known, enabled, connected;
  `arguments` is an object, JSON ≤ **64 KiB**, required keys of the descriptor
  present, unknown keys refused when the schema is closed (domain check, no
  `jsonschema` in Core) ⇒ `mcp_arguments_invalid`.
- Result `ToolCallOutcome = {ok, code?, message?, content: [{"type": "text",
  "text"}…], structured?, truncated}`; text ≤ **32 KiB** total (cut +
  `truncated: true`); non-text blocks become `{"type": "text", "text":
  "[image omise]"}` in V1. **A successful result is masked too** (locked
  intent 3, QA rework of Slice 04): every text block goes through `redact`
  and `structured` through `redact_structured` (every string leaf; a string
  under a credential-named key — `access_token`, `password`, `cookie`,
  `authorization`, `session_id`… — is masked whole; keys and shape stay, the
  JSON stays valid; the key rules are the same as for text, §8.2, so paging
  tokens pass). The gateway returns `content` as MCP text blocks,
  `isError` when `ok` is false or the remote result is an error.
- **Known V1 limit — relevance on fresh wording (agent 0, QA 2 of Slice
  04).** The lexical ranking (§6.4) finds the right tool in the top 3 for
  0.923 of the fixture and 0.900 of the regression set, but QA measured only
  **5/15** on intents worded independently of both. Mitigation, by design:
  every accessible external tool stays visible in the compact, pageable
  `others` (the model can read its summary and page with `next_cursor`), and
  the model is told to call `list_tools` again (a more precise intent) when a
  need appears or a card in `others` needs its schema (§6.1). No further
  vocabulary tuning in V1.
- Timeout: default **60 s**, max **120 s** (`mcp_remote_timeout`). The
  route body accepts an optional `timeout_s` (1–120; Slice 04 addition, the
  gateway never sends it); Core clamps the session call to 120 s.
- No confirmation gate for `destructive` external tools in V1 (READINESS Q3:
  native write tools have none; the brain runs under the CLI permission mode);
  descriptors carry `side_effect` conservatively. To revisit at acceptance.
- Every call is journaled `mcp.plugin.tool_called {plugin_id, tool, ok, code,
  duration_ms, bytes}` — **never arguments nor result text**.

## 8. Core routes and error codes

### 8.1 Routes (`jarvis/protocol/server.py`, token-authenticated)

All under `/v1/mcp`; errors keep Core's shape `{"error": {"code",
"message"}}`; body limit 256 KiB; `LocalCoreClient` (`protocol/client.py:53`)
mirrors each route.

| Method + path | Body / query | 2xx body |
| --- | --- | --- |
| `GET /v1/mcp/plugins` | — | `{"plugins": [public_view…], "vault_available": bool, "catalog_revision": int}` |
| `POST /v1/mcp/plugins` | `{endpoint, display_name?}` | 201 `{"plugin": …}` (validation + duplicate check, no network) |
| `GET /v1/mcp/plugins/{id}` | — | `{"plugin": …}` |
| `PATCH /v1/mcp/plugins/{id}` | `{enabled?, display_name?}` | `{"plugin": …}` |
| `POST /v1/mcp/plugins/{id}/connect` | `{strategy?: "auto"\|"none"\|"oauth"}` or empty | 200 `{"status":"connected","plugin"}` / 202 `{"status":"authorizing","authorization_url","plugin"}` (§3.3) |
| `PUT /v1/mcp/plugins/{id}/credential` | `{strategy: "bearer"\|"header", header_name?, value}` | `{"plugin": …}` (value never echoed) |
| `POST /v1/mcp/plugins/{id}/disconnect` | — | `{"plugin": …}` |
| `POST /v1/mcp/plugins/{id}/refresh` | — | `{"plugin": …}` |
| `DELETE /v1/mcp/plugins/{id}` | — | 200 `{"removed": id}` |
| `POST /v1/mcp/oauth/callback` | `{state, code?, iss?, error?, error_description?}` (`error_description` ignored) | `{"plugin": …}` |
| `GET /v1/mcp/tools` | `?since_revision=` (integer; any other query ⇒ 400 `mcp_plugin_invalid`) | `{"catalog_revision": int, "unchanged": bool, "plugins": [{plugin_id, display_name, enabled, connection_status, auth_status, tool_count}], "tools": [ExternalToolDescriptor…]}` — tools of enabled ∧ connected plugins only; every plugin listed, sorted by id; `unchanged: true` (since_revision = current) ⇒ `plugins` and `tools` are **empty** (keep the cached copy) — Slice 04 |
| `POST /v1/mcp/tools/call` | `{tool_id, arguments?, caller?: {agent, native_servers_count?}, timeout_s?}` | `ToolCallOutcome` (§7) — Slice 04 |

Core without a connector (`connector=None`) ⇒ plugins listable, `connect`
answers `503 mcp_connector_unavailable`. On these Core routes
`catalog_revision` is an **integer** covering the external part only: a
monotonic in-memory int, +1 on any plugin state or tool-list change, starting
from a random base at each Core start (a value cached from an old Core never
matches). The gateway embeds it as the `e<…>` part of the model-facing string
revision (§6.3).

### 8.2 Stable error codes

| Code | HTTP |
| --- | ---: |
| `mcp_plugin_unknown` | 404 |
| `mcp_plugin_duplicate` | 409 |
| `mcp_plugin_invalid` (a refused field or body: display name, header name, credential value, unknown key, bad JSON, > 256 KiB; added by Slice 02 — ARCH §9 named no code for it) | 400 |
| `mcp_plugin_store_unreadable` (damaged row) / `mcp_plugin_store_failed` (SQLite refused) — same family as `board_store_*` | 500 |
| `mcp_plugin_internal_error` (the connection owner crashed on a local bug — not a store failure, not a remote one; Jarvis sentence, never the exception text; also the row's `last_error_code`; ARCH §16 E18) | 500 |
| `mcp_endpoint_invalid` | 400 |
| `mcp_endpoint_forbidden` (SSRF) | 400 |
| `mcp_vault_unavailable` | 409 |
| `mcp_connector_unavailable` | 503 |
| `mcp_plugin_disabled` | 409 |
| `mcp_plugin_disconnected` | 409 |
| `mcp_plugin_reauthorization_required` | 409 |
| `mcp_oauth_state_invalid` | 400 |
| `mcp_oauth_issuer_mismatch` | 400 |
| `mcp_oauth_denied` | 400 |
| `mcp_oauth_timeout` (no browser return within the 300 s TTL; a row code — the late callback itself answers `mcp_oauth_state_invalid`; S7 fix, ARCH §16 E22) | 408 |
| `mcp_transport_unsupported` | 502 |
| `mcp_remote_unreachable` | 502 |
| `mcp_remote_tls` | 502 |
| `mcp_remote_protocol` | 502 |
| `mcp_response_too_large` | 502 |
| `mcp_remote_timeout` | 504 |
| `mcp_remote_tool_error` | 200, `ok: false` |
| `mcp_tool_unknown` | 404 |
| `native_tool_call_directly` | 400 |
| `mcp_arguments_invalid` | 400 |
| `mcp_cursor_invalid` | 400 |
| `mcp_tool_name_invalid` / `mcp_tool_schema_too_large` / `mcp_tool_schema_invalid` / `mcp_tool_list_too_large` | ingestion rejections (in `rejected_tools`, no HTTP answer) |

Not in this table on purpose — **UI-only codes** of the Control Center tab
(§9.1), never sent by Core nor by the relay: `bad_response` (a 2xx whose body
is not the JSON object expected, e.g. a proxy page; Core and the relay always
answer JSON, so only something between them and the page can produce it),
`forbidden_route`, `oauth_timeout`, `oauth_url_invalid`, `timeout`,
`network`. Relay-local codes (`core_unreachable`, `core_unconfigured`,
`core_timeout`, `not_found`, `method_not_allowed`, `forbidden_host`) are
listed in [tool-contract.md](tool-contract.md) §10.6.

Messages are Jarvis sentences. A remote error text reaches the model **only**
through `mcp_remote_tool_error`, bounded to 4 KiB; it and every successful
result (§7) pass through
`redact(text, known_secrets)` (domain): every vault value of that plugin, any
`Bearer\s+\S+`, and JWT shapes
`[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}` are replaced.
**Slice 04 addition:** the value of any `key=value` / `"key": "value"` pair
whose key names a credential (`token`, `access_token`, `refresh_token`,
`id_token`, `secret`, `client_secret`, `password`, `passwd`, `api_key`,
`apikey`) is replaced too — the end-to-end test showed a remote server can
echo a secret the vault does not hold. **QA rework of Slice 04 (ARCH §16
E21):** also the value of an `Authorization` header of any scheme (`Basic`,
`Digest`… — the scheme stays readable), the whole value of a `Cookie:` /
`Set-Cookie:` header, `session=` / `session_id=`, `X-Amz-Credential=`,
`X-Amz-Signature=`, `X-Amz-Security-Token=`, `sig=`, `signature=`; a quoted
value is masked whole, spaces and escaped quotes included (`"token": "abc
def"`); a quoted `Authorization` value is masked whole
(`{"Authorization": "Basic abc DEF"}` → `"Basic [secret masqué]"`). An
already masked value is never masked twice, and ordinary words (« session :
ouverte », `design=`, « Basic setup ») stay.

**QA 2 of Slice 04 — paging survives redaction.** A credential key must
**start a word** (no letter, digit or `_` right before it), and
`page`/`next`/`skip`/`sync`/`cursor`/`delta`/`continuation`/`resume` tokens
written as two words (`page-token`) are exempt: `nextPageToken`,
`$skiptoken=` inside `@odata.nextLink`, `next_page_token=`, `syncToken`
pass intact, so the model can still page. Prefixed credential keys stay
masked (`access_`/`refresh_`/`id_`/`auth_`/`bearer_`/`csrf_`/`oauth_`/
`session_`/`security_token`). An unquoted key and value after a word with
`:` is prose (« Remaining token: 512 » stays). `session` is masked only in
the `session=` form (URL, cookie), never as a JSON key holding prose
(`{"session": "Morning session"}` stays). Text and `structured` apply the
same key list.

## 9. Control Center

Relay routes (`jarvis/runtime/mcp_plugin_routes.py`, pattern
`runtime/board_routes.py`, status + JSON body verbatim, Core unreachable ⇒
`503 core_unreachable`) and the callback page are listed in
[tool-contract.md](tool-contract.md) §8. Unknown paths under
`/api/mcp/plugins*` are answered by `mcp_plugin_routes.py` itself:
`404 mcp_plugin_unknown` for an unknown plugin id, `404 not_found` for an
unknown sub-path (ARCH §16 E8); `mcp_tool_unknown` stays reserved to
`/api/mcp/tools*`. Why the callback is
`/api/mcp/oauth/callback` and not under `/api/mcp/plugins/…` (C6): the
plugins prefix is read-guarded (endpoints are private data, and writes), and
the authorization server's redirect is a cross-site top-level navigation that
`_loopback_refusal` (`control_center.py:273`) would reject. The callback is
protected instead by single-use `state`, a 300 s TTL, the `iss` check and a
loopback Host check; it answers a static French page (« Autorisation reçue,
vous pouvez fermer cet onglet » or a coded failure) with
`Cache-Control: no-store` and `Referrer-Policy: no-referrer`, and never echoes
`code` or `state`.

UI (Slice 06, **implemented**): same dock button `#openMcpInspector` and
dialog `#mcpInspector`, a two-tab switch « Exposition interne » (today's
inspector, unchanged, still GET-only) / « Plugins externes » (module
`control_center_mcp_plugins.js`, the only one that writes). Cards: icon
(`icon_url` with `referrerpolicy=no-referrer`, letter fallback), display name,
host, connection + auth badges, enable toggle, tool count, « Gérer ». Add
flow: URL → create → connect(auto) → 202 ⇒ open `authorization_url` in a new
tab and poll `GET /api/mcp/plugins` every 2 s for at most 5 min;
`auth_status=required` without OAuth metadata ⇒ manual form (Bearer / en-tête
personnalisé, password input, write-only). Manage view: « Reconnecter »,
« Déconnecter », « Supprimer » (confirmed), « Actualiser »; the plugin's tools
render through the **existing inspector detail renderer** — no second tool
viewer, no tool name literal.

### 9.1 Implementation facts (Slice 06)

Routes, delays, guard and callback page: [tool-contract.md](tool-contract.md)
§10.6 (plugin paragraph). Tab and the inspector's single reuse export
(`toolRowsHtml`): tool-contract §10.7. What the tab does, as shipped:

- **Two modules, two clients.** `JarvisMcpPluginsCore.createClient` only
  reaches `/api/mcp/plugins` and `/api/mcp/plugins/{id}[/connect|disconnect|
  refresh|credential]` (id checked against the §2.1 slug before the network),
  with a 15 s deadline, 45 s for connect/disconnect/refresh/delete. A
  plugin's tools are read with the **inspector's** read-only client
  (`/api/mcp/tools`, rows whose `server === plugin_id`, then the detail
  route) and rendered by `JarvisMcpInspectorCore.toolRowsHtml`; they appear
  only while the plugin is enabled and connected (the catalog lists no
  others), otherwise the view says so and shows the discovered count.
- **Card.** Letter tile always drawn, the remote icon over it; an icon that
  fails to load is removed and never requested again. Switch =
  `<button role="switch" aria-checked>` with a visible « Activé /
  Désactivé »; a disabled plugin reads « désactivé : outils retirés » (its
  connection badge stays true to Core: `enabled` never changes
  `connection_status`, §2.2). The last error shows its stable code and a
  French title, never a remote text. One primary action when useful:
  « Connecter », « Reconnecter » (after an error, an expiry or a previous
  discovery) or « Relancer l’autorisation » when an OAuth authorization was
  cut (`authorizationCut`): Core still `authorizing` while this screen no
  longer waits, `mcp_oauth_timeout` / `mcp_oauth_denied` /
  `mcp_oauth_state_invalid`, or `auth_status=failed` with a timeout code on a
  plugin that is not `bearer`/`header` (Core marks any failure of an open
  interactive flow `failed`, §2.2); its access badge then reads « Autorisation
  interrompue » (warn), not « Accès refusé ». A **disabled** plugin never offers a
  connection (Core would answer `mcp_plugin_disabled`); its badges stay true
  to Core but muted — « Connecté · en pause », never a green badge; a
  credential saved on it is kept and the tab says to enable it instead of
  connecting. **Core down** (the last re-read failed while a list is shown):
  each card reads « État non vérifié » (muted, dashed; the last known state
  in the chip's title), without its last error or primary action, until a
  re-read succeeds.
- **OAuth.** `window.open(url, "_blank", "noopener,noreferrer")` — the AS
  receives no `Referer` naming the Control Center (the runtime check showed
  plain `noopener` still sent it). `authorization_url` is opened **and**
  linked only when its scheme is `https:`, or `http:` to a loopback host
  (`localhost`, `127.x.x.x`, `[::1]`, which only the development flag lets
  Core issue), without userinfo; anything else (`javascript:`, `data:`,
  remote `http:`…) is neither opened nor rendered as `href`: the tab shows
  the coded error `oauth_url_invalid` (« Page d’autorisation refusée »,
  toast + inline in « Gérer »), journals it, and the card keeps « Relancer
  l’autorisation ». The response arrives after the click, so a
  popup blocker may refuse the tab: the card keeps a link « Ouvrir la page
  d’autorisation » (`rel="noopener noreferrer"`), a live counter « reste …»,
  and « Ne plus attendre ». The wait ends on `connected` (toast), on a
  failure (toast; when the code or state calls for it — §3.1 — the Manage
  view opens with the manual form: `auth_status=required` (no OAuth
  metadata) or a refusal of the OAuth token; **never for a timeout**
  (`mcp_remote_timeout`, `mcp_oauth_timeout`, `oauth_timeout`, `timeout`,
  `core_timeout`), which is not a refusal — the card offers « Relancer
  l’autorisation »), or after 5 min
  (`oauth_timeout`, UI-side, said on screen and journaled). Transient read failures (`core_unreachable`,
  timeouts) do not end the wait before its deadline.
- **Manual access.** The form says why it is there: « demande un accès sans
  proposer OAuth » only when Core says `required`; after an OAuth refusal,
  « Le serveur refuse l’accès obtenu par OAuth » ; opened by hand, a neutral
  sentence. While it is open its « Enregistrer et connecter » is the only
  primary button of the view. The form's secret field is `type=password`, has no
  `value` attribute, is read once on submit and emptied **before** the
  request; the value lives only in that function and the `PUT` body, never in
  the tab's state, the DOM, the page journal or a toast. Then `connect`
  runs. Bearer ↔ header only shows or hides the header-name field (no
  re-render, so nothing typed is lost or copied).
- **Actions.** Toggle = `PATCH {enabled}`; « Déconnecter » is confirmed
  (page `confirmDialog`) when the plugin holds an access (its tokens or key
  are forgotten, §2.2); « Supprimer » is always confirmed (danger style,
  « Annuler » focused). Every action shows what it is doing with elapsed
  seconds, disables its controls, shows a coded failure (inline in the
  Manage view + toast), logs `[mcp-plugins] mcp.plugins.action_failed`
  (code, status, `plugin_id` — never a value) and re-reads Core in `finally`.
- **Errors.** Every stable code of §8.2 used by these routes, plus
  `core_unreachable`, `core_unconfigured`, `core_timeout`,
  `forbidden_origin`, `method_not_allowed`, `not_found`, `timeout`,
  `network`, `bad_response`, `oauth_timeout`, `oauth_url_invalid`,
  `forbidden_route`, has a French title and a recourse (tested). An error
  block leads with the French title, the recourse and its button; Core's raw
  message (escaped text), the code and the HTTP status sit under a collapsed
  « Détail technique » disclosure, which stays open across background
  re-renders (a slot is rewritten only when the HTML to write changes).
  UI-only codes, never answered by Core or the relay:
  - `forbidden_route` — the tab's client (`createClient`, whose single gate
    `request` is exported) refused, **before the network**, a path outside
    `/api/mcp/plugins[/{id}[/connect|disconnect|refresh|credential]]`, an
    id outside the §2.1 slug, or a method outside GET/POST/PATCH/PUT/DELETE.
    Status 0; it can only mean a defect of the page, never a user mistake.
  - `bad_response` — a 2xx whose body is not a JSON object;
  - `oauth_url_invalid` — see OAuth above; `oauth_timeout` — the 5 min wait;
    `timeout` / `network` — the page's own deadline or a failed fetch. Core down: the tab shows the coded error and
  « Réessayer »; « Exposition interne » keeps working (natives served, the
  `plugins` pseudo-server `described: false`).
- **Keyboard and reading.** Dialog tabs with roving `tabindex` and arrows;
  focus kept across every re-render, including a control disabled during its
  own action (the intent is held until it is enabled again); the body is made
  of slots rewritten only when their HTML changes, so a background re-read
  (every 2 s while waiting) never wipes a field being typed; Escape steps back
  (manual form → Manage view → list, add form → list) before the dialog's own
  Escape closes it, and never while the page confirmation is open. Live
  region `#mcppAnnounce` for outcomes; elapsed seconds are `aria-hidden`.
  Tokens only, one card per row under 700 px, `prefers-reduced-motion`
  stops the switch and spinner motion. Remote text never widens the view:
  card name and host are ellipsized, and the Manage view (title, facts,
  rejected tools) and the inspector rows it reuses (label, wire name, open
  summary, description, parameter table, rules, notes) wrap anywhere —
  measured in headless Chrome with 3 000-character words at 1 440 and 375 px
  (`test_a_3000_character_word_never_widens_the_plugin_view`).

## 10. Propagation to agents

V1: an enabled plugin is a **global** Jarvis capability — no per-Board or
per-agent policy.

| Runtime / profile | Gateway `jarvis-tools` | Native servers listed by `list_tools` | Mechanism |
| --- | --- | --- | --- |
| Claude, `conversation` | **yes**, always on | the ones declared this launch (`jarvis-console` + display/Bare Hands when on) | a fourth `--mcp-config`, placed after the console one (`claude_local.py:853`); `snapshot()["tools_gateway"]`; write failure ⇒ `agent.tools_mcp_failed` (error), brain starts without it |
| Claude, delegated subagent (CLI `Agent` tool) | **inherited** from the parent CLI process — proven by a real trace (Slice 05, Q1: a `general-purpose` background subagent, events with `parent_tool_use_id`, ran `ToolSearch` → `list_tools` → `call_tool`) | same as parent | Jarvis does not launch subagents (`runtime/routing_hook.py:3-7`). The `--agents` fallback of ARCH §8.3 is **not built** (inheritance holds). The brain passes the discovery hint in its delegation prompt (`BRAIN_TOOLS_PROMPT`); the routing charter is unchanged |
| Claude, `job_result` | **no** | — | unchanged: this profile receives no Jarvis MCP config in V1 (`claude_local.py:777-782`) |
| Claude, `speculative_analysis` | **no** | — | restricted profile (`RESTRICTED_PROFILES`, `claude_local.py:226`): `--strict-mcp-config`, `--tools ""`, unchanged |
| Claude, `presentation_preparation` | **no** | — | restricted profile: `--strict-mcp-config`, Read/Glob/Grep/Web only, unchanged |
| Codex | **yes** (unless `tools_mcp_unsafe_argv`, below) | none (`JARVIS_TOOLS_NATIVE_SERVERS` empty: Codex receives no native server) | `-c mcp_servers.jarvis-tools.*` overrides appended by `_turn_command` before `-`, `exec` and `exec resume`; values in the Codex process environment, forwarded by `env_vars`; `tool_timeout_sec=130` |

- Wiring: the Control Center builds one `ToolsGatewayTarget` in `app.py` (same
  Core host, port and token file as `DisplayMcpTarget`) and sets
  `agent.tools_mcp` for both CLIs in `ControlCenter._configure_agent`
  (`control_center.py:1205`, called by `_apply_agent_settings` :1194; ARCH §16
  E2).
- Prompt: a `BRAIN_TOOLS_PROMPT` constant in `claude_local.py`, declared in
  `runtime/prompt_catalog.py` and composed **only when the gateway is declared
  for that launch or turn** (ARCH E20): Claude programs
  `backend.claude.conversation.tools_*` (config written), Codex program
  `backend.codex.tools_turn` (overrides passed and sandbox
  `danger-full-access`; a turn with no context and no active behaviour, which
  otherwise goes out as raw text, then gets `backend.codex.tools_plain_turn`:
  the tools layer followed by the request unchanged). Under
  `workspace-write`/`read-only` Codex refuses
  `call_tool` (Q4 below), so the layer is **omitted** there (simpler than a
  variant; `list_tools` stays reachable, unadvertised).
  **Q5 (measured, Slice 05): the gateway is deferred behind ToolSearch** like
  every MCP tool of the launch; the model loads it with
  `ToolSearch select:mcp__jarvis-tools__list_tools,mcp__jarvis-tools__call_tool`,
  so the prompt names both tools in full. Codex receives the same text
  through its turn program (`backend.codex.tools_turn`, prompt id
  `backend.conversation.tools`).
- **Codex argv is not safe for values.** `codex` is the npm shim
  `codex.CMD`, run by `cmd.exe`: `&` splits the command, `%VAR%` is expanded,
  `^` is stripped, whatever the TOML quoting. So the overrides carry **names**
  only — `env_vars=['JARVIS_CORE_HOST', …, 'JARVIS_TOOLS_AGENT']` — and the
  values (`ToolsGatewayTarget.env()`: host, port, paths of the token file and
  runtime, never the token) are set in the Codex child process environment;
  Codex forwards exactly the listed variables to the server (codex-cli
  0.157.0, verified with `codex mcp get --json` and a real probe server). The
  only path left in argv is `command` (`sys.executable`, TOML literal `'…'`,
  JSON-escaped basic string when it contains `'`). If the resolved Codex
  executable is a `.cmd`/`.bat` and an override carries a `cmd.exe`
  metacharacter (`& | < > ^ % ! "`, CR/LF), the turn runs **without** the
  gateway: `agent.tools_mcp_failed` (error, `tools_mcp_unsafe_argv`),
  `snapshot()["tools_gateway"]` false, no tools prompt layer. Round-trip
  through the real `codex mcp get jarvis-tools --json` launched by
  `asyncio.create_subprocess_exec` (runtime dir with a space, `'`, `R&D`) is
  tested (`requires_codex`).
- **Q4 (measured, Slice 05, codex-cli 0.157.0).** Default Control Center mode
  `danger-full-access` (`--dangerously-bypass-approvals-and-sandbox`):
  `list_tools` and `call_tool` run. Non-bypass mode (`-c
  sandbox_mode=workspace-write`, `codex exec` approval policy `never`):
  `list_tools` (annotated read-only) runs, `call_tool` (annotated
  destructive) is **refused by Codex** with `MCP tool call requires approval,
  but approval policy is never`; the model reports the refusal. V1 keeps this:
  the gateway follows the CLI permission mode (as Q3: no gate beyond it), and
  Jarvis does not widen a mode the user restricted. Opening it would take
  `-c mcp_servers.jarvis-tools.default_tools_approval_mode=…` (key present in
  0.157.0, not wired) and a product decision.
- Restricted profiles do not silently inherit write-capable plugins (locked
  intent 10); changing that needs a product decision and an amendment here.
- The routing hook's charter may carry one line reminding subagents of
  `list_tools`; it never carries credentials. Not needed in V1: the brain
  wrote the hint into the subagent's prompt in the Slice 05 trace.

### 10.1 Implementation facts (Slice 05)

- `ClaudeLocalAgent(tools_mcp=…)` → `_tools_mcp_args(native_servers)` writes
  `runtime/tools-mcp.json` (host, port, **path** of the token file, env names —
  never the token) with `JARVIS_TOOLS_NATIVE_SERVERS` = the servers declared
  by this same launch, in argv order `jarvis-display`, `jarvis-barehands`,
  `jarvis-console`, `jarvis-capture` (session-context-recording, Slice 09) (a
  server whose own config failed to write is not listed);
  `agent.start` carries `tools_mcp`; a write failure journals
  `agent.tools_mcp_failed` (`tools_mcp_config_write_failed`, error) and the
  brain starts without the gateway. Restricted profiles and `job_result`:
  argv byte-identical with or without the target (tested).
- `CodexLocalAgent(tools_mcp=…)`: `_turn_command` appends the four overrides
  just before `-`, on `exec` and `exec resume`, with `native_servers=()` and
  `agent="codex"`, and the turn's process environment carries
  `target.env()`; `snapshot()["tools_gateway"]` is true while a target is set,
  the session is `ready`/`running` and the last plan did not drop the gateway
  (`tools_mcp_unsafe_argv`) — each turn reads the current target, so it never
  shows a pending restart, even before the first turn. The catalog therefore
  reads `advertised` on a `ready` snapshot too
  (`mcp_catalog.advertised_from_agent_snapshot`; Claude is never `ready`).
- `ControlCenter(tools_mcp=…)` built in `app.py` from Core's host, port and
  token file; `_configure_agent` hands it to both CLIs.
- Prompt: `BRAIN_TOOLS_PROMPT` (prompt id `backend.conversation.tools`,
  read-only, 669 B) after the settings layer in the four Claude
  `conversation_tools_*` programs, and between the turn addition and the brief
  in `backend.codex.tools_turn` (E20: only where the gateway is declared;
  `compose_agent_turn(agent=…)` asks `CodexLocalAgent.turn_declares_tools_gateway()`). `test_brain_delegation::test_the_voice_agent_starts_
  with_the_rule_and_with_the_agent_tool_available` stays red exactly as
  before (READINESS §Baseline): it compares the whole appended prompt to
  `BRAIN_SYSTEM_PROMPT` alone, which the settings layer already broke; the
  tools layer adds no new failing assertion.

## 11. Google Drive (`jarvis-drive`)

**Classification (ARCH §11, Slice 07): legacy operator-managed local stdio,
not a remote MCP plugin; not migrated in V1.** Three Drive paths exist, all on
the one adapter `jarvis/adapters/google_drive.py` (`GoogleDriveBackend`) and the
same OAuth files, located by environment (`GOOGLE_DRIVE_CLIENT_SECRET`, falling
back to `GOOGLE_CALENDAR_CLIENT_SECRET`, and `GOOGLE_DRIVE_TOKEN`):

| Path | What it is | Who declares it | Model reach |
| --- | --- | --- | --- |
| 1. `jarvis-drive` | stdio MCP server `jarvis/runtime/drive_mcp.py` (`SERVER_NAME`, 7 tools `drive_search`, `drive_get`, `drive_read`, `drive_create`, `drive_update`, `drive_delete`, `drive_share`), backend built lazily per call | the **operator**, once: `claude mcp add … --scope user` (`docs/OPERATIONS.md`); `ServerMeta registration="operator"`; Jarvis never writes a `--mcp-config` for it | the Claude CLI loads it from the user scope, directly (`mcp__jarvis-drive__*`) — never through `jarvis-tools` |
| 2. Core voice `DriveService` | `jarvis/core/drive_service.py`, built by `app.py:_drive_backend_from_env` | `JARVIS_DRIVE_PROVIDER=google` (default `none`: no Drive in Core) | the voice tools of Core; no MCP |
| 3. `python -m jarvis drive-auth` | one-time interactive consent that writes `GOOGLE_DRIVE_TOKEN` | the operator | none; paths 1 and 2 refuse to open a browser and point to it |

Consequences, proven by tests (Slice 07): the merged catalog still lists and
introspects `jarvis-drive` next to managed plugins — `registration=operator`,
`described=true`, availability `known`, its 7 tools
(`test_mcp_catalog.py::test_jarvis_drive_stays_an_introspected_operator_server_next_to_plugins`);
`list_tools` never recommends nor lists it, even when a launch declares it and a
plugin is connected (`test_tools_gateway_mcp.py::test_drive_intents_never_surface_the_operator_server_next_to_a_plugin`,
`::test_the_operator_server_is_never_listed_even_if_declared`); `test_drive.py`
stays green. Its token never enters the plugin vault and the plugin runtime
never reads its files.

**Migration criteria (future, all required).** Moving Drive to a managed plugin
needs: (a) a hosted **remote** Drive MCP over Streamable HTTP with OAuth
protected-resource metadata (RFC 9728) and AS metadata (RFC 8414) the generic
adapter accepts without a provider-specific line; (b) **parity** for the 7
operations (same inputs, same results, same refusals), proven by a
side-by-side run on the same files; (c) correct
`readOnlyHint`/`destructiveHint` on its tools so `side_effect` is right; (d) the
voice path (2) given an equivalent or kept as is — a plugin never feeds Core's
voice tools; (e) a Human decision recorded in the task that performs it.

**Rollback rule.** `jarvis-drive` stays registered (user scope) and working
until parity is proven **and** accepted; the plugin is added next to it, never
instead of it. Rollback = disable or remove the plugin in the Control Center
(`enabled=false` removes it from `list_tools` at once; `DELETE` forgets its
sealed tokens) — `jarvis-drive` was never touched, so nothing needs restoring.
Only after acceptance may the operator run `claude mcp remove jarvis-drive
--scope user`; re-adding it is the rollback of that step.

**Pending (Slice 07 phase B, live):** one brain turn that reads a Drive file
through `mcp__jarvis-drive__*` (trace excerpt: tool id and ok only).

## 12. Tests (binding names, content per Slice contract)

ARCH §13: `test_mcp_plugin_domain.py`, `test_mcp_endpoint_policy.py`,
`test_mcp_plugin_store_sqlite.py`, `test_schema_migrations.py` (v4 snapshot),
`test_credential_vault.py`, `test_dpapi_sealer.py`,
`test_mcp_plugin_service.py`, `test_mcp_protocol_routes.py`,
`tests/fakes/fake_remote_mcp.py`, `test_mcp_http_policy.py`,
`test_mcp_oauth_adapter.py`, `tests/integration/test_remote_mcp_connector.py`,
`test_tool_relevance.py`, `test_tool_discovery.py`,
`test_tools_gateway_mcp.py`, `test_mcp_catalog.py` (amended),
`test_claude_tools_gateway_args.py`, `test_codex_agent.py` (amended),
`test_control_center_mcp_plugins_api.py`,
`test_control_center_mcp_plugins_js.py`, `test_v2_architecture.py`
(exception +1).
Slice 07: `tests/integration/test_live_circoe_toolbox.py` — marked `live`
(marker declared in `pyproject.toml`), skipped unless `JARVIS_LIVE_CIRCOE=1`
and an authorized OAuth plugin exists in the given data root
(`JARVIS_LIVE_CIRCOE_DATA_ROOT`, else `JARVIS_DATA_ROOT` read at import);
it works on a sqlite copy of that root: non-interactive connect, list, one
read-only call, no token or client id in any output.
Slice 08: `tests/unit/test_mcp_secret_sentinel.py` (end-to-end sentinel),
`tests/integration/test_mcp_plugin_restart.py` (Core and Control Center
restart), budget re-measures in `test_tool_discovery.py` /
`test_tools_gateway_mcp.py` (`test_s8_*`).

## 13. Implementation facts (Slice 04)

| Module | Holds |
| --- | --- |
| `jarvis/domain/tool_relevance.py` | `fold`, `tokens`, `SYNONYMS`, `PHRASES`, `query_weights`, `ToolDoc`, `RankIndex`, `build_index`, `rank` (§6.4) |
| `jarvis/domain/tool_discovery.py` | `ToolEntry` (`full()` / `compact()`), `build_list_response`, `encode_cursor` / `decode_cursor`, `size_of`, `summary_of`; budgets as constants (`MAX_RECOMMENDED`, `MAX_RECOMMENDED_NATIVES`, `MAX_RECOMMENDED_BYTES`, `MAX_RESPONSE_BYTES`…) |
| `jarvis/domain/mcp_plugins.py` | `parse_tool_id`, `check_tool_arguments`, `call_outcome`, `redact`, `redact_structured` (§7, §8.2) |
| `jarvis/core/mcp_plugin_service.py` | `external_tools(since_revision)`, `call(tool_id, arguments, caller=, timeout_s=)` on the state check shared with `invoke` (`_ready_session`) |
| `jarvis/runtime/tools_gateway_mcp.py` | `ToolsGatewayTarget`, `mcp_config`, `write_mcp_config`, `codex_config_overrides`, `toml_value`, `CoreToolsTransport`, `native_entries`, `external_entries`, `ToolsGateway`, `build_server`, `serve_stdio` |
| `jarvis/runtime/mcp_catalog.py` | `describe_external_tool`, `merge_external`, `plugin_availability`, `plugin_facts`; `build_introspection_server("jarvis-tools")` |
| `jarvis/runtime/mcp_results.py` | `ToolListResult` (closed output schema of `list_tools`; costs no model context, tool-contract §10.3) |

Behaviour fixed by the implementation (within ARCH, or recorded deviations):

- **Measured budgets**: the two tools cost **1 544 B** (name + description +
  input schema, bound 2 500 B); the server instructions **584 B** (bound
  1 200 B). Tested in `tests/unit/test_tools_gateway_mcp.py`.
- **`recommended` only on the first page**: a `next_cursor` page (offset > 0)
  answers `recommended: []`; the `others` list excludes the recommended
  entries on every page, so paging visits each tool exactly once.
- **Greedy packing**: a candidate that no longer fits the 16 KiB recommended
  part is skipped (it stays in `others`, without `detail`), and the next one
  may still fit; only an entry that alone exceeds 16 KiB carries
  `"detail": "too_large"` (E3).
- **Revision when Core is unreachable**: `n<fp8>.e0` (Core's integer revision
  starts at a random base ≥ 1, so `e0` never matches a real one) and
  `notes: ["plugins_unavailable"]`; the gateway gives Core **5 s** for
  `GET /v1/mcp/tools` (the Control Center gives it 2 s). The native
  fingerprint is `sha1` of the listed natives' `[id, description,
  input_schema]`, first 8 hex characters.
- **Errors to the model** are MCP tool errors (`isError`) whose text is
  `<code> : <message> — <next step>` (e.g. `mcp_plugin_disabled : … — le
  plugin est désactivé dans le Control Center : dis-le à l'utilisateur`),
  followed by the remote text for `mcp_remote_tool_error`. Codes added at the
  gateway: `core_unreachable` (Core did not answer a call) and
  `mcp_catalog_unavailable` (the native catalog could not be built). A
  `mcp__…` tool id is refused by the gateway **and** by Core
  (`native_tool_call_directly`), before any network.
- **Schema hardening** reuses `jarvis-display`'s (`_without_titles`, unknown
  argument refused, pydantic refusals bounded); `intent`, `limit` and
  `tool_id` are strict (no `"30"` for `30`).
- **Result shaping**: a success whose content has no text but a
  `structured` object is rendered as its compact JSON; `truncated: true` adds
  the text « [résultat tronqué : borne de 32 Kio atteinte] ».
- **Latency (QA rework)**: `list_tools` on a warm index, descriptions of
  4 KB: 500 tools 752 → **25 ms**, 2 000 tools 2 747 → **105 ms** (cold
  first call, index build included: ~0.6 s / ~2.9 s).
- **Journals** (never an intent, argument or result text): gateway
  `tools.server_started`, `tools.list` (intent length, total, native_total,
  recommended ids, others count, bytes, revision, notes, duration),
  `tools.index_built` (revision, tool count), `tools.external_item_skipped`
  (code, count, tool ids), `tools.list_refused`,
  `tools.call` (tool id, ok, code, duration), `tools.plugins_unavailable` /
  `tools.plugins_restored` (once per outage), `tools.native_catalog_failed`;
  Core `mcp.plugin.tool_called` gains `agent` and `bytes`.
- **Control Center**: `jarvis-tools` availability reads the agent attribute
  `tools_mcp` (set by Slice 05 for both CLIs; absent ⇒ `disabled`); the inspector's
  overview now lists the two cross-domain tools, and its footer says the
  discovery gateway is the only server announcing catalog tools to the model.

## 14. Conformance: Circuit Toolbox

Target `https://circoetoolbox-server-production.up.railway.app/mcp`, probed on
**2026-09-30** (Slice 07 phase A) with unauthenticated, read-only HTTP, plus
**one** Dynamic Client Registration built by Jarvis's own code
(`client_metadata()` of `jarvis/adapters/mcp_oauth.py`, `grant_types` rule of
§3.3, scope chosen by the SDK's `get_client_metadata_scopes`). No token was
requested. The same requests also passed through `validate_endpoint` and
`PolicyTransport` (public address, https): accepted. **Live-login items are
pending phase B** (Human consent, HV-07-01).

| Item | Observed | Jarvis behaviour |
| --- | --- | --- |
| Unauthenticated `POST /mcp` (and `GET`, `DELETE`, `HEAD`) | `401`, body `{"error":"authentication_required"}`, `WWW-Authenticate: Bearer resource_metadata="https://…/.well-known/oauth-protected-resource", scope="mail calendar contacts"` | `auto` ⇒ OAuth; scope taken from the header |
| PRM (RFC 9728) | at the **root** well-known (`/.well-known/oauth-protected-resource`; the path-suffixed `…/oauth-protected-resource/mcp` answers 404) — `resource` = the endpoint exactly, `authorization_servers: ["https://…app"]`, `scopes_supported: [mail, calendar, contacts]` | found through `resource_metadata`; RFC 8707 `resource` check passes |
| AS metadata (RFC 8414) | `/.well-known/oauth-authorization-server` 200 (`openid-configuration` 404); `issuer` = origin without trailing `/` (PRM lists it with one — the SDK's `issuers_match` accepts both) | issuer validated |
| Endpoints | `authorization_endpoint /authorize`, `token_endpoint /token`, `registration_endpoint /register`, all on the same origin | — |
| `grant_types_supported` | `["authorization_code"]` only | DCR registers `["authorization_code"]` (no `refresh_token`) |
| PKCE | `code_challenge_methods_supported: ["S256"]` | S256 (SDK) |
| Client auth | `token_endpoint_auth_methods_supported: ["none"]` (public clients) | `none` |
| `response_types_supported` | `["code"]` | `["code"]` |
| RFC 9207 | `authorization_response_iss_parameter_supported: true` | callback `iss` must equal the metadata `issuer` string (§3.3) |
| Revocation (RFC 7009) | **no `revocation_endpoint` advertised** | Disconnect = local forget only (E10) |
| Scopes | `mail`, `calendar`, `contacts` (header, PRM and AS agree) | authorization asks `mail calendar contacts` |
| DCR (Q2) | request `{"redirect_uris":["http://127.0.0.1:17790/api/mcp/oauth/callback"],"token_endpoint_auth_method":"none","grant_types":["authorization_code"],"response_types":["code"],"scope":"mail calendar contacts","client_name":"Jarvis"}` ⇒ **`201`**, body `{client_id: "e0Pi2B…", client_id_issued_at, client_name, redirect_uris (echoed unchanged), grant_types: ["authorization_code"], response_types: ["code"], token_endpoint_auth_method: "none"}` — no `client_secret`, no `registration_access_token`, `scope` not echoed; the SDK parses it (`OAuthClientInformationFull`) | loopback `http://127.0.0.1:<port>` redirect **accepted** |
| Transport | only the 401 is visible without a token | pending phase B (Streamable HTTP expected: `initialize` over POST) |
| Token lifetime (`expires_in`), refresh token issued or not, tool count, rejected tools, one read-only call, brain + subagent (+ Codex) access, disable/re-enable, disconnect/reconnect, expiry | — | **pending phase B** |

**Q2 answer (ARCH §15).** (1) An `http://127.0.0.1:<port>` loopback redirect
URI is accepted by the real registration endpoint. (2) Whether it would accept
`grant_types` containing `refresh_token` was **not** probed and does not need
to be: the AS advertises only `authorization_code`, so the adapter never sends
it (§3.3); the fake AS covers the refusal case
(`FakeConfig.accept_refresh_grant=False`).

No generic defect was found by these probes; no product code changed.

## 15. Release facts (Slice 08)

### 15.1 Final numbers (measured 2026-09-30, phase A)

| Surface | Measured | Bound |
| --- | --- | --- |
| `jarvis-tools` model context (`list_tools` 923 B + `call_tool` 621 B) | **1 544 B** | 2 500 B |
| Gateway server instructions | **584 B** | 1 200 B |
| `BRAIN_TOOLS_PROMPT` (`backend.conversation.tools`) | 669 B | — |
| `list_tools`, 3 declared natives + 500 heavy plugin tools, first page (5 intents) | 15 609–20 501 B | 24 576 B |
| same, largest cursor page | 20 501 B | 24 576 B |
| `list_tools`, domain worst case (500 tools, descriptions at 4 096 B, limit 60), largest page | 23 469 B | 24 576 B |
| `list_tools`, three mail tools (realistic), 5 intents | 669–5 561 B | 24 576 B |
| Native display / console context (tool-contract §10.10) | 31 864 / 9 616 B | 33 090 / 10 000 B (unchanged) |
| `list_tools` on the real Circuit Toolbox catalog | **pending phase B** | 24 576 B |

Recall@3 (Slice 04 rework, unchanged): 0.923 on the fixture intents, 0.900 on
the regression set; fresh wording stays a known V1 limit (§7).

### 15.2 Secrets (sentinel)

`tests/unit/test_mcp_secret_sentinel.py`, for a `bearer` credential and for an
OAuth authorization: create → credential/consent → connect → list → call
(including a remote error quoting the secret) → disconnect → delete, through
the Control Center relay, Core, `SdkRemoteMcpConnector`, the fake remote server
and the `jarvis-tools` gateway. The sentinel appears in no `/api/*` or
`/v1/mcp/*` response body, no model-facing `list_tools`/`call_tool` result,
not in `tools-mcp.json` nor the Codex `-c` overrides, not in `trace.jsonl`,
`errors.jsonl` or any other file of the run; `jarvis.sqlite3` (with its
`-wal`) holds it only sealed (the sealer's marker is there, the plaintext
never). The only place it travels in clear is the body of the browser's
`PUT …/credential` **request**. Removing the redaction of remote errors makes
the test fail (mutation checked). Real CLI transcripts (stream-json) were
scanned in Slice 05; the final live scan is phase B.

### 15.3 Restart persistence

`tests/integration/test_mcp_plugin_restart.py` (real Core, four fake
servers): a Core restart keeps every row, `enabled` flag and sealed blob
byte-identical; enabled `oauth`, `bearer` and `none` plugins reconnect at
`start()` with no UI and no new authorization; an OAuth token expired without
refresh becomes `auth_status=expired` (`mcp.plugin.expired_at_boot`) with no
network request; a disabled plugin stays `disconnected` and its server sees
nothing; `mcp.plugins.boot_reconnect` lists exactly the ids whose
non-interactive reconnect was launched. A
Control Center stopped and started again in front of the same Core returns the
same `/api/mcp/plugins` and changes no plugin and no remote request (the CC
keeps no plugin state, §1).

### 15.4 Pending phase B (live)

- Circuit Toolbox after login (§14 last rows): transport, token lifetime,
  refresh or not, tool count, rejected tools, one read-only call, brain +
  delegated subagent (+ Codex) access, disable/re-enable, disconnect/reconnect,
  expiry; the real `list_tools` bytes.
- Final Brain + delegated-subagent traces through `jarvis-tools` against
  Circuit Toolbox, reviewed by agent-trace analysis; final live secret scan
  of the CLI transcripts.
- Human checks HV-06-01 (plugin manager visual UX) and HV-07-01 (real OAuth
  consent); Q3 (no confirmation gate for destructive plugin tools in V1)
  confirmed by the Human at acceptance.

### 15.5 Known pre-existing fact (not this handoff's)

The Claude conversation brain is launched **without** `--strict-mcp-config`
(only `RESTRICTED_PROFILES` pass it, `claude_local.py`), so the operator's
user-level MCP servers — `jarvis-drive`, claude.ai connectors,
`claude-in-chrome` — load next to Jarvis's four `--mcp-config` servers.
`list_tools` never lists them (ARCH C8, §11); the model can still reach them
through ToolSearch. Changing that is a product decision outside this handoff.
