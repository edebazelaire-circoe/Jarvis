# MCP plugins and intent-aware tool discovery

Handoff `tasks/jarvis-generic-mcp-plugin-runtime/`, Slice 01 (contract).
**Status: target contract, implemented by Slices 02–07 of
`jarvis-generic-mcp-plugin-runtime`. Nothing in this document is shipped at
`6aabefd` unless a sentence says "today".** Shipped by Slice 02: the domain
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
**implemented** — declared to the brains from Slice 05), the Core routes
`GET /v1/mcp/tools` and `POST /v1/mcp/tools/call` (§8.1, **implemented**),
and the merged catalog (§5.2, **implemented**); implementation facts and the
deviations from ARCH: §13. Binding design:
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
| `icon_url` | https only, ≤ 512 chars, from `serverInfo.icons` when advertised; **never fetched by Core** |
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
  (ARCH §16 E10; Circuit Toolbox advertises none: local forget only); (3) the
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
  | same, during an `oauth` flow (second authorization requested, TTL passed, SDK OAuth error) | `failed` | `error` |
  | `mcp_oauth_denied`, `mcp_oauth_issuer_mismatch` | `failed` | `error` |
  | `mcp_vault_unavailable` | `required` | `error` |
  | any other code | unchanged | `error` |
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
`revocation_endpoint` feeds the RFC 7009 revocation of §2.2.

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
  nothing; `trust_env=False` (no environment proxy);
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
| `input_schema` | an object schema, compact JSON ≤ 16 KiB, depth ≤ 12, else rejected `mcp_tool_schema_too_large` |
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
chose is kept. The first https icon of `serverInfo.icons` becomes `icon_url`.

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
profile and to Codex by Slice 05 (§10, still target).

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
3. **Rank** with `tool_relevance.rank(intent, docs)` (§6.4).
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
 "next_cursor": null, "total": 42, "notes": []}
```

`direct_native` entries also carry `call_as`. Bounds:

| Part | Rule |
| --- | --- |
| `recommended` | ≤ **5** entries; only score > 0 **and** ≥ 0.35 × top score; FULL `description` + `input_schema`; packed greedily while the recommended part ≤ **16 KiB**. A tool whose full entry alone exceeds 16 KiB is never recommended: it stays callable and appears in `others` with `"detail": "too_large"` |
| `others` | every remaining accessible tool, rank order then id; `summary` = first description line ≤ 120 chars; `source` = server name or plugin display name; page size `limit` |
| whole response | ≤ **24 576 bytes**, measured as `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` encoded UTF-8; `others` is filled until that bound |
| `next_cursor` | urlsafe-base64 JSON `{r: catalog_revision, o: offset, h: sha1(intent)[:8]}`, or null; `r` is the same **string** as `catalog_revision` |
| `catalog_revision` | the string `n<native fingerprint, 8 chars>.e<external revision>` — this is the only form the model ever sees (ARCH §16 E6); the integer form exists only on Core's `/v1/mcp/*` routes (§8.1) |

- A cursor whose revision differs from the current one restarts at offset 0
  with `notes: ["catalog_changed"]`.
- A cursor issued for another intent ⇒ `mcp_cursor_invalid`.
- An intent empty after folding ⇒ `recommended: []`, `others` alphabetical.
- Normal use never needs a second lookup for a recommended tool; there is **no
  `get_tool`**.

### 6.4 Relevance (`jarvis/domain/tool_relevance.py`)

**Status: implemented (Slice 04).** Quality gate:
`tests/fixtures/tool_intents.json`, 26 FR/EN intents, recall@3 = 0.92
(`tests/unit/test_tool_relevance.py`).

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
  ecrire/write/rediger); query expansion weight 0.6.
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
  "[image omise]"}` in V1. The gateway returns `content` as MCP text blocks,
  `isError` when `ok` is false or the remote result is an error.
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
| `mcp_tool_name_invalid` / `mcp_tool_schema_too_large` / `mcp_tool_list_too_large` | ingestion rejections (in `rejected_tools`, no HTTP answer) |

Messages are Jarvis sentences. A remote error text reaches the model **only**
through `mcp_remote_tool_error`, bounded to 4 KiB and passed through
`redact(text, known_secrets)` (domain): every vault value of that plugin, any
`Bearer\s+\S+`, and JWT shapes
`[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}` are replaced.
**Slice 04 addition:** the value of any `key=value` / `"key": "value"` pair
whose key names a credential (`token`, `access_token`, `refresh_token`,
`id_token`, `secret`, `client_secret`, `password`, `passwd`, `api_key`,
`apikey`) is replaced too — the end-to-end test showed a remote server can
echo a secret the vault does not hold. An already masked value is never
masked twice.

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

UI (Slice 06): same dock button `#openMcpInspector` and dialog
`#mcpInspector`, a two-tab switch « Exposition interne » (today's inspector,
unchanged, still GET-only) / « Plugins externes » (new module
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

## 10. Propagation to agents

V1: an enabled plugin is a **global** Jarvis capability — no per-Board or
per-agent policy.

| Runtime / profile | Gateway `jarvis-tools` | Native servers listed by `list_tools` | Mechanism |
| --- | --- | --- | --- |
| Claude, `conversation` | **yes**, always on | the ones declared this launch (`jarvis-console` + display/Bare Hands when on) | a fourth `--mcp-config`, placed after the console one (`claude_local.py:853`); `snapshot()["tools_gateway"]`; write failure ⇒ `agent.tools_mcp_failed` (error), brain starts without it |
| Claude, delegated subagent (CLI `Agent` tool) | inherited from the parent CLI process (**to be proven by a Slice 05 trace**, READINESS Q1) | same as parent | Jarvis does not launch subagents (`runtime/routing_hook.py:3-7`). Fallback if disproved: `--agents` JSON with `mcpServers: ["jarvis-tools"]` (designed, not built) |
| Claude, `job_result` | **no** | — | unchanged: this profile receives no Jarvis MCP config in V1 (`claude_local.py:777-782`) |
| Claude, `speculative_analysis` | **no** | — | restricted profile (`RESTRICTED_PROFILES`, `claude_local.py:226`): `--strict-mcp-config`, `--tools ""`, unchanged |
| Claude, `presentation_preparation` | **no** | — | restricted profile: `--strict-mcp-config`, Read/Glob/Grep/Web only, unchanged |
| Codex | **yes** | none (`JARVIS_TOOLS_NATIVE_SERVERS` empty: Codex receives no native server) | `-c mcp_servers.jarvis-tools.*` overrides appended by `_turn_command` before `-` (`codex_local.py:253-273`), `exec` and `exec resume`; `tool_timeout_sec=130` |

- Wiring: the Control Center builds one `ToolsGatewayTarget` in `app.py` (same
  Core host, port and token file as `DisplayMcpTarget`) and sets
  `agent.tools_mcp` for both CLIs in `ControlCenter._configure_agent`
  (`control_center.py:1205`, called by `_apply_agent_settings` :1194; ARCH §16
  E2).
- Prompt: a `BRAIN_TOOLS_PROMPT` constant in `claude_local.py`, included in the
  four conversation programs like `BRAIN_SETTINGS_PROMPT` (`claude_local.py:165`)
  and declared in `runtime/prompt_catalog.py`; fingerprint tests updated.
  Whether `ENABLE_TOOL_SEARCH` deferral hides the gateway (then the prompt names
  `mcp__jarvis-tools__list_tools` explicitly) is measured in Slice 05 (Q5).
- Codex overrides use TOML literal strings `'…'`; a value containing `'` or a
  control character falls back to a JSON-escaped basic string. Codex MCP
  approval in non-bypass sandbox modes is recorded by a Slice 05 trace (Q4).
- Restricted profiles do not silently inherit write-capable plugins (locked
  intent 10); changing that needs a product decision and an amendment here.
- The routing hook's charter may carry one line reminding subagents of
  `list_tools`; it never carries credentials.

## 11. Google Drive (`jarvis-drive`)

Three Drive paths exist today, all on `jarvis/adapters/google_drive.py` with
OAuth files located by environment (`GOOGLE_DRIVE_CLIENT_SECRET`,
`GOOGLE_DRIVE_TOKEN`): (1) the `jarvis-drive` stdio server
(`drive_mcp.py`, registered by the operator with `claude mcp add … --scope
user`, `registration="operator"`); (2) Core voice tools (`DriveService` via
`JARVIS_DRIVE_PROVIDER=google`, `app.py:268`); (3) `python -m jarvis
drive-auth`.

**Classification: legacy operator-managed local stdio, not a remote MCP; not
migrated in V1.** It stays in the catalog as today (tool-contract §3,
`known`), and `list_tools` never claims it (§6.2). Migration criteria (future):
a hosted remote Drive MCP with OAuth protected-resource metadata, parity for
the 7 operations, rollback = keep `jarvis-drive` registered until parity is
proven. Slice 07 proves no regression.

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

## 13. Implementation facts (Slice 04)

| Module | Holds |
| --- | --- |
| `jarvis/domain/tool_relevance.py` | `fold`, `tokens`, `SYNONYMS`, `query_weights`, `ToolDoc`, `rank` (§6.4) |
| `jarvis/domain/tool_discovery.py` | `ToolEntry` (`full()` / `compact()`), `build_list_response`, `encode_cursor` / `decode_cursor`, `size_of`, `summary_of`; budgets as constants (`MAX_RECOMMENDED`, `MAX_RECOMMENDED_BYTES`, `MAX_RESPONSE_BYTES`…) |
| `jarvis/domain/mcp_plugins.py` | `parse_tool_id`, `check_tool_arguments`, `call_outcome`, `redact` (§7, §8.2) |
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
- **Journals** (never an intent, argument or result text): gateway
  `tools.server_started`, `tools.list` (intent length, total, recommended
  ids, others count, bytes, revision, notes, duration), `tools.list_refused`,
  `tools.call` (tool id, ok, code, duration), `tools.plugins_unavailable` /
  `tools.plugins_restored` (once per outage), `tools.native_catalog_failed`;
  Core `mcp.plugin.tool_called` gains `agent` and `bytes`.
- **Control Center**: `jarvis-tools` availability reads the agent attribute
  `tools_mcp` (set from Slice 05; absent today ⇒ `disabled`); the inspector's
  overview now lists the two cross-domain tools, and its footer says the
  discovery gateway is the only server announcing catalog tools to the model.
