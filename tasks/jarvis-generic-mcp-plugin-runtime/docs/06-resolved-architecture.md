# Resolved architecture (Slice 00, code-grounded)

Status: **binding for Slices 01-08.** Written by the Slice 00 planning repair on
branch `task/jarvis-generic-mcp-plugin-runtime`, HEAD `96a9396`, 2026-09-30.
It resolves `02-architecture.md` against the code and the agent-0 decisions
D1-D12. Where the code forced a change to a decision, the change is listed in
§14 *Contradictions found*, never applied silently. File:line anchors are at
HEAD `96a9396`; re-check them before editing (the Board task may move lines).

## 0. Process topology (verified)

Jarvis runs **two** long-lived Python processes that matter here. They are not
the same process; D1/D5 wrote "Core (the Control Center process)", which is
wrong (§14 C1).

| Process | Entry | Server | Auth | Owns |
| --- | --- | --- | --- | --- |
| **Core** | `python -m jarvis core` → `app.py:_run_core_v2` (527-576) | `jarvis/protocol/server.py:LocalProtocolServer` (aiohttp, asyncio), `127.77.0.1:<core_port>` | `Authorization: Bearer <token>` read from `runtime/core.token` (`server.py:90-113`) | `jarvis.sqlite3` via `SQLiteStateRepository` (`core/v2_app.py:61`), Boards/Sessions, scene, conversation events |
| **Control Center (CC)** | `python -m jarvis control-center` → `app.py` (~1312-1333) | `jarvis/runtime/control_center.py:ControlCenter` (aiohttp, asyncio), `127.0.0.1:17654` | loopback Origin/Host guard (`control_center.py:1560-1597`, `READ_GUARDED_ROUTES` :239) | UI, settings JSON, the brain agents (`ClaudeLocalAgent`/`CodexLocalAgent`, `_build_agent` :1131), native MCP catalog routes |

Native MCP servers are stdio children of the brain CLI. Two reach-back patterns
exist and both are reused:

- **Core pattern (token)**: `jarvis-display` gets `JARVIS_CORE_HOST`,
  `JARVIS_CORE_PORT`, `JARVIS_CORE_TOKEN_FILE`, `JARVIS_RUNTIME_DIR` in the env of
  its `--mcp-config` entry (`display_mcp.py:193-260`, `DisplayMcpTarget`); it
  re-reads the token file on (re)connect through `CoreLoopbackTransport`
  (`runtime/core_forwarder.py:47-70`). The config file holds paths and a port,
  never the token (`display_mcp.py:263-270`).
- **CC pattern (loopback, no token)**: `jarvis-console` / `jarvis-barehands`
  get host/port of the CC (`settings_mcp.py:184-242`).

CC → Core relays already exist: `BoardSessionRoutes` (`runtime/board_routes.py`)
through `CoreSessionTransport.forward(method, path, params, body)`
(`runtime/core_sessions.py:74-91`, one 401 replay after re-reading the token).

Layering is **test-enforced** (`tests/unit/test_v2_architecture.py`):
`jarvis/domain` and `jarvis/ports` import no `aiohttp/httpx/sqlite3/...`, no
`jarvis.adapters|core|runtime`; `jarvis/core` imports no transport/provider, no
`jarvis.runtime`, and no `jarvis.adapters` except the named, exhaustive
`CORE_ADAPTER_IMPORT_EXCEPTIONS` of `core/v2_app.py` (:35-52). Concrete
backends are built in `app.py:_run_core_v2` and injected (precedent:
`drive_backend=_drive_backend_from_env()`, `app.py:268,565`).

## 1. Component map

```text
Brain CLI (Claude conversation / Codex)            Control Center (CC)                  Core daemon
  └─ stdio jarvis-tools (gateway)                    /api/mcp/tools (GET, merged)  ──►  GET  /v1/mcp/tools
       list_tools: native catalog (in-process)       /api/mcp/plugins* (manage)    ──►  /v1/mcp/plugins*
                 + external descriptors  ──────────────────────────────────────────►  GET  /v1/mcp/tools
                 ranking/budget (domain)             /api/mcp/oauth/callback       ──►  POST /v1/mcp/oauth/callback
       call_tool ─────────────────────────────────────────────────────────────────►  POST /v1/mcp/tools/call
                                                                                        McpPluginService (core)
                                                                                          ├─ McpPluginRepository (sqlite v4)
                                                                                          ├─ CredentialVault (sealed blobs + Sealer)
                                                                                          └─ RemoteMcpConnector (adapter: mcp SDK,
                                                                                             httpx policy transport, OAuth)
```

Browser closed ⇒ nothing changes for the brain: the gateway talks to Core, and
Core keeps the plugin sessions (D1, `03-implementation-strategy.md` last line).

## 2. Module layout (new unless marked)

| Layer | Module | Role |
| --- | --- | --- |
| domain | `jarvis/domain/mcp_plugins.py` | `McpPlugin`, enums, transitions, id slug, `ExternalToolDescriptor`, bounds, remote-tool normalization, error codes, redaction helper |
| domain | `jarvis/domain/mcp_endpoint.py` | pure endpoint validation (`validate_endpoint`), IP classification (`is_forbidden_address`) |
| domain | `jarvis/domain/tool_relevance.py` | fold/tokenize, synonyms, BM25 index, `rank()` |
| domain | `jarvis/domain/tool_discovery.py` | `build_list_response()` (recommended/others/cursor/byte budget) |
| ports | `jarvis/ports/mcp_plugins.py` | `McpPluginRepository`, `SealedSecretStore`, `Sealer`, `RemoteMcpConnector`, `RemoteMcpSession`, `AuthorizationPrompt` protocols |
| core | `jarvis/core/credential_vault.py` | `CredentialVault` (seal/unseal + binding check) over `SealedSecretStore` + `Sealer` |
| core | `jarvis/core/mcp_plugin_service.py` | `McpPluginService`: CRUD, lifecycle, one `PluginConnection` owner task per plugin, OAuth pending flows, call dispatch, revision |
| adapters | `jarvis/adapters/sqlite_mcp_plugins.py` | registry + sealed blob store over `SQLiteStateRepository.run_serialized` (`sqlite_state.py:318`) |
| adapters | `jarvis/adapters/dpapi_sealer.py` | Windows DPAPI `CryptProtectData/CryptUnprotectData` via `ctypes` (CurrentUser); `UnavailableSealer` elsewhere |
| adapters | `jarvis/adapters/remote_mcp.py` | `SdkRemoteMcpConnector`: `mcp.client.streamable_http.streamable_http_client` + `ClientSession` |
| adapters | `jarvis/adapters/mcp_http_policy.py` | `PolicyTransport(httpx.AsyncBaseTransport)`: SSRF/DNS policy, response byte cap |
| adapters | `jarvis/adapters/mcp_oauth.py` | `VaultTokenStorage` (SDK `TokenStorage`), `JarvisOAuthProvider(OAuthClientProvider)` (issuer `iss` check, expiry persistence, non-interactive mode) |
| protocol | `jarvis/protocol/server.py` (modify) + `jarvis/protocol/client.py` (modify) | `/v1/mcp/*` routes and `LocalCoreClient` methods |
| runtime | `jarvis/runtime/tools_gateway_mcp.py` | stdio FastMCP server `jarvis-tools`: `list_tools`, `call_tool`; `ToolsGatewayTarget`, `mcp_config`, `write_mcp_config`, `codex_config_overrides`, `serve_stdio` |
| runtime | `jarvis/runtime/mcp_catalog.py` (modify) | native catalog + `describe_external_tool()` + `merge_external()`; `build_introspection_server("jarvis-tools")` |
| runtime | `jarvis/runtime/mcp_tool_meta.py` (modify) | `TOOLS = ServerMeta("jarvis-tools", ...)`, `Registration` += `"managed"` |
| runtime | `jarvis/runtime/mcp_plugin_routes.py` | CC relay routes `/api/mcp/plugins*`, `/api/mcp/oauth/callback` (pattern `board_routes.py`) |
| runtime | `jarvis/runtime/control_center_mcp_plugins.js` | UI module "Plugins externes" (write routes live here only) |
| cli | `jarvis/app.py` (modify) | subcommand `tools-mcp`; Core composition injects sealer + connector; CC gets `ToolsGatewayTarget` |

## 3. Data model and persistence (D4, Slice 02)

### 3.1 Domain (`jarvis/domain/mcp_plugins.py`)

```python
AuthStrategy = Literal["none", "oauth", "bearer", "header"]
ConnectionStatus = Literal["disconnected", "connecting", "connected", "error"]
AuthStatus = Literal["unknown", "not_required", "required", "authorizing", "authorized", "expired", "failed"]

@dataclass(frozen=True)
class McpPlugin:
    plugin_id: str            # slug, ^[a-z0-9][a-z0-9-]{0,31}$, never "jarvis-*", immutable
    display_name: str         # ≤ 64, editable; default = serverInfo.name or host
    endpoint: str             # normalized https URL (validate_endpoint)
    endpoint_origin: str      # scheme://host[:port]
    transport: Literal["streamable_http"]
    enabled: bool
    connection_status: ConnectionStatus
    auth_status: AuthStatus
    auth_strategy: AuthStrategy
    credential_ref: str | None          # opaque "cred_<32 hex>", never a secret
    icon_url: str | None                # https only, ≤ 512 chars, from serverInfo.icons when advertised; never fetched by Core
    server_identity: dict | None        # {name, version, protocol_version} from initialize, bounded
    capability_revision: int            # +1 at every tool-list change
    tools: tuple[ExternalToolDescriptor, ...]   # last discovered, bounded (§6.3)
    rejected_tools: tuple[dict, ...]            # [{name, code}] bounded list of refused remote tools
    last_discovered_at: str | None
    last_error_code: str | None         # stable code only (§9), never a remote body
    created_at: str; updated_at: str
    def to_payload(self) -> dict; @classmethod from_payload(cls, raw) -> "McpPlugin"  # strict
    def public_view(self) -> dict       # UI/API shape: no credential_ref
```

- `plugin_id_for(endpoint, taken: set[str]) -> str`: first DNS label of the
  host, lowercased, `[^a-z0-9-]` → `-`, trimmed to 32, prefix `jarvis-`
  refused (→ `p-…`); collision → `-2`, `-3`… (D3). Circuit Toolbox →
  `circoetoolbox-server-production`.
- Duplicate detection: same normalized `endpoint` ⇒ `409 mcp_plugin_duplicate`.
- Transitions are pure functions (`enable/disable/mark_connecting/...`);
  `enabled` never changes `connection_status`, and `disconnect` never changes
  `enabled` (locked intent 2).

### 3.2 Migration v4 (`adapters/sqlite_state.py`)

`_SCHEMA_VERSION = 4`; `_MIGRATIONS[4]` (additive, same style as v3 :36-110;
`data` = canonical `to_payload()`, other columns extracted and cross-checked):

```sql
CREATE TABLE IF NOT EXISTS mcp_plugins (
  plugin_id TEXT PRIMARY KEY,
  endpoint TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
  connection_status TEXT NOT NULL CHECK (connection_status IN ('disconnected','connecting','connected','error')),
  auth_status TEXT NOT NULL CHECK (auth_status IN ('unknown','not_required','required','authorizing','authorized','expired','failed')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mcp_credentials (
  credential_ref TEXT PRIMARY KEY,
  plugin_id TEXT NOT NULL REFERENCES mcp_plugins(plugin_id),
  scheme TEXT NOT NULL CHECK (scheme IN ('dpapi-user-v1')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  blob BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS idx_mcp_credentials_plugin ON mcp_credentials(plugin_id);
```

Frozen snapshot `tests/schema/jarvis_state.v4.sql` via
`JARVIS_WRITE_SCHEMA_SNAPSHOT=1 pytest tests/unit/test_schema_migrations.py`
(CLAUDE.md rule 3). No product row in the migration. Pre-migration backup is
automatic (`sqlite_state.py:289-316`). Plugin row delete and its credential rows
delete run in one `BEGIN IMMEDIATE` transaction (pattern
`sqlite_workspace_board.py:SQLiteBoardRepository._transaction`).
On boot, rows in `connecting` are rewritten `disconnected` (a crash never
leaves a phantom connection).

### 3.3 Credential vault (D4)

- Port `Sealer`: `available: bool`, `scheme: str`, `seal(bytes) -> bytes`,
  `unseal(bytes) -> bytes`. Adapters: `DpapiSealer` (ctypes `crypt32`,
  `CRYPTPROTECT_UI_FORBIDDEN`, optional entropy = `b"jarvis-mcp-v1"`),
  `UnavailableSealer` (non-Windows: `available=False`), tests: `FakeSealer`
  (reversible XOR + marker, `tests/fakes/`).
- Port `SealedSecretStore`: `put(ref, plugin_id, scheme, blob)`, `get(ref)`,
  `delete(ref)`, `delete_for_plugin(plugin_id)` — implemented by
  `SQLiteMcpPluginRepository` (same adapter, table `mcp_credentials`).
- Core `CredentialVault(store, sealer)`: `put_secret(plugin, payload: dict) -> credential_ref`,
  `get_secret(plugin) -> dict | None` (returns `None` when the sealed payload's
  binding `{plugin_id, endpoint_origin}` ≠ the plugin's current values),
  `replace_secret`, `forget(plugin)`, `available`. Sealed payload JSON:
  `{"v":1,"plugin_id","endpoint_origin","kind":"oauth"|"static",`
  `"oauth":{"tokens":{...},"expires_at":epoch|null,"client_info":{...},"issuer","resource","redirect_uri"},`
  `"static":{"header_name","value"}}`.
- Sealer unavailable ⇒ any strategy other than `none` is refused with
  `409 mcp_vault_unavailable` (no plaintext fallback).
- **`jarvis/runtime/credentials.py` is not reused**: it stores API keys in
  plaintext `runtime/control-center-settings.json` and returns them to CC code
  (`secret_for`); plugin secrets must stay in Core, sealed.
- Threat model (same as `display_mcp.py:37-41`): the brain runs as the same OS
  user; DPAPI CurrentUser protects against other users and copies of the DB,
  not against a malicious same-user process. The guarantee is: no secret in
  model context, tool descriptors, API payloads, journals or traces.

## 4. Core service and protocol (Slices 02-04)

### 4.1 `McpPluginService` (`jarvis/core/mcp_plugin_service.py`)

Constructed in `JarvisCoreApplication.__init__` with injected
`connector: RemoteMcpConnector | None` and `sealer: Sealer | None` (new
keyword args, default `None` ⇒ plugins listable but `connect` answers
`503 mcp_connector_unavailable`); the SQLite adapter is constructed in
`v2_app.py` over `self.state` exactly like the Board store, which adds **one**
entry `"jarvis.adapters.sqlite_mcp_plugins"` to
`CORE_ADAPTER_IMPORT_EXCEPTIONS` (§14 C3). `start()` after
`state.initialize()`: resets `connecting`, then schedules background connects
for `enabled` plugins whose auth is `not_required` or `authorized` (never
interactive at boot). `stop()`: closes every connection within 5 s total.

Public API (async, all return domain values or raise `McpPluginError(code, status)`):

```python
list_plugins() -> list[McpPlugin]
create(endpoint: str, display_name: str | None) -> McpPlugin          # validate + duplicate; no network
update(plugin_id, *, enabled: bool | None, display_name: str | None) -> McpPlugin
connect(plugin_id, *, strategy: AuthStrategy | Literal["auto"] = "auto") -> ConnectOutcome
    # ConnectOutcome = {status: "connected"|"authorizing"|"failed", authorization_url?: str, code?: str}
set_static_credential(plugin_id, *, strategy: Literal["bearer","header"], header_name: str | None, value: str) -> McpPlugin
complete_oauth(code: str, state: str, iss: str | None) -> McpPlugin
disconnect(plugin_id) -> McpPlugin                                     # close + forget credentials; keeps row
remove(plugin_id) -> None                                              # disconnect + delete row + creds
refresh(plugin_id) -> McpPlugin                                        # re-list tools
external_tools(since_revision: int | None) -> ExternalCatalog          # enabled+connected descriptors + plugin states
call(tool_id: str, arguments: dict, *, caller: dict) -> ToolCallOutcome
```

`catalog_revision` (external) = monotonic int held in memory, +1 on any plugin
state or tool-list change; restarts at a random base per Core start (like the
`store_id` convention) so a cached value from an old Core never matches.

### 4.2 `PluginConnection` (anyio constraint)

The SDK transport is anyio-based and must be entered/exited in one task
(`streamable_http_client` is an `asynccontextmanager` holding a task group).
So each connected plugin has **one owner `asyncio.Task`** in Core's loop:

```text
owner task: async with connector.open(plugin, auth) as session:   # adapter
               tools = await session.list_tools_all()               # paginated, bounded
               ready.set(); await stop.wait()
other tasks: await session.call_tool(name, args, timeout)           # ClientSession is safe to call concurrently
```

Failure of the owner → `connection_status=error`, `last_error_code`, reconnect
with backoff `(1, 2, 5, 10, 30, 60)` s capped, while `enabled`; a 401/expired
token stops retries with `auth_status=expired` (no interactive flow outside an
explicit `connect`). `notifications/tools/list_changed` (ClientSession
`message_handler`) → re-list, bump `capability_revision` and catalog revision.

### 4.3 Core routes (`jarvis/protocol/server.py`, token-authenticated)

All under `/v1/mcp` — **not** `/v1/tools/call`, which already exists for the
voice `CoreToolRouter` (`server.py:153,586`, §14 C4). Errors keep Core's shape
`{"error": {"code", "message"}}`.

| Method + path | Body / query | 2xx body |
| --- | --- | --- |
| `GET /v1/mcp/plugins` | — | `{"plugins": [public_view…], "vault_available": bool, "catalog_revision": int}` |
| `POST /v1/mcp/plugins` | `{endpoint, display_name?}` | 201 `{"plugin": …}` |
| `GET /v1/mcp/plugins/{id}` | — | `{"plugin": …}` |
| `PATCH /v1/mcp/plugins/{id}` | `{enabled?, display_name?}` | `{"plugin": …}` |
| `POST /v1/mcp/plugins/{id}/connect` | `{strategy?: "auto"\|"none"\|"oauth"}` | 200 connected / 202 `{"status":"authorizing","authorization_url"}` |
| `PUT /v1/mcp/plugins/{id}/credential` | `{strategy:"bearer"\|"header", header_name?, value}` | `{"plugin": …}` (value never echoed) |
| `POST /v1/mcp/plugins/{id}/disconnect` | — | `{"plugin": …}` |
| `POST /v1/mcp/plugins/{id}/refresh` | — | `{"plugin": …}` |
| `DELETE /v1/mcp/plugins/{id}` | — | 200 `{"removed": id}` |
| `POST /v1/mcp/oauth/callback` | `{code, state, iss?, error?}` | `{"plugin": …}` |
| `GET /v1/mcp/tools` | `?since_revision=` | `{"catalog_revision", "unchanged": bool, "plugins": [{plugin_id, display_name, enabled, connection_status, auth_status, tool_count}], "tools": [ExternalToolDescriptor…]}` (only enabled∧connected tools; all plugins listed) |
| `POST /v1/mcp/tools/call` | `{tool_id, arguments, caller:{agent, native_servers_count?}}` | `ToolCallOutcome` (§7.2) |

Body limit for `/v1/mcp/*`: 256 KiB (checked in handler). Client methods on
`LocalCoreClient` (`protocol/client.py:53`) mirror each route.

## 5. Connection, transport, SSRF, OAuth (D5, D6, Slice 03)

### 5.1 Endpoint policy (`jarvis/domain/mcp_endpoint.py`)

`validate_endpoint(raw: str, *, allow_loopback_http: bool) -> str` (normalized)
refuses with `mcp_endpoint_invalid` + reason: scheme ≠ https (http only when
host resolves to loopback **and** `allow_loopback_http`), userinfo present, any
query parameter or fragment carrying credentials (V1: refuse **any** fragment;
refuse query keys matching `token|key|secret|auth|password|sig` case-folded),
IP-literal hosts that are not global, length > 2048, non-ASCII host not
IDNA-encodable. `allow_loopback_http` = env `JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`
(dev only, read in `app.py`, journaled at Core start).
`is_forbidden_address(ip) -> bool`: `not ip.is_global` or in
`100.64.0.0/10`, `169.254.0.0/16`, `fd00::/8`, `::ffff:0:0/96` mapped private
(uses `ipaddress`, stdlib).

### 5.2 `PolicyTransport` (`jarvis/adapters/mcp_http_policy.py`)

Wraps `httpx.AsyncHTTPTransport`; for **every** request (MCP, PRM, AS metadata,
DCR, token — all go through the one `httpx.AsyncClient` handed to the SDK):
resolve host with `loop.getaddrinfo`, refuse if any resolved address is
forbidden (loopback allowed only under the dev flag), refuse non-https except
that flag, cap response bodies at `MAX_RESPONSE_BYTES = 4 MiB` (streamed
counter → `mcp_response_too_large`). Redirects: the SDK already follows only
same-origin, method-preserving redirects for MCP and auth requests
(`mcp/shared/_httpx_utils.py:86-125, 185-215`) and never forwards the bearer to
another origin; `max_redirects=3` on the client. Residual risk (documented,
accepted V1): DNS rebinding between our resolution and httpx's connect.
Timeouts: connect 10 s, read 60 s (tool call), total list/initialize 30 s.

### 5.3 OAuth (verified against `mcp 1.30.0`, `mcp/client/auth/oauth2.py`)

SDK facts: `OAuthClientProvider(server_url, client_metadata, storage,
redirect_handler, callback_handler, timeout=300, client_metadata_url=None)`
(:236-280); it discovers PRM from `WWW-Authenticate resource_metadata`
(SEP-985 fallbacks), validates PRM `resource` against the server URL (RFC 8707,
:281-288), validates AS metadata issuer (`validate_metadata_issuer`, :615),
binds client credentials to the issuer (SEP-2352), does DCR, PKCE S256, `state`
(`secrets.compare_digest`, :367), `resource` param, scope from
`WWW-Authenticate`/PRM, and step-up on `403 insufficient_scope`. It does
**not** check the RFC 9207 `iss` response parameter, and on load
(`_initialize`, :488) it restores tokens **without** an expiry.

Jarvis adapter (`jarvis/adapters/mcp_oauth.py`):

- `VaultTokenStorage(TokenStorage)`: `get_tokens/set_tokens/get_client_info/set_client_info`
  read/write the sealed `oauth` payload through a callback into Core's
  `CredentialVault`; `set_tokens` also stores `expires_at = now + expires_in`.
- `JarvisOAuthProvider(OAuthClientProvider)`: after `_initialize`, sets
  `context.token_expiry_time` from the stored `expires_at` (tested against the
  SDK version; `mcp>=1.2,<2` stays but the test pins behaviour).
- Client metadata: `client_name="Jarvis"`, `redirect_uris=[<CC>/api/mcp/oauth/callback]`,
  `token_endpoint_auth_method="none"`, `grant_types=["authorization_code"]` plus
  `"refresh_token"` **only when** AS metadata `grant_types_supported` lists it
  (§15 Q2, decided by agent 0), `response_types=["code"]`.
- **Interactive mode** (only inside `McpPluginService.connect`):
  `redirect_handler(url)` parses `state` from the URL, registers a
  `PendingAuthorization{state, plugin_id, future, expires_at=now+300 s,
  expected_issuer}` and resolves the connect call's "authorization_url" future;
  `callback_handler()` awaits the pending future. `connect()` runs the owner
  task and returns within 20 s with whichever comes first: connected, or the
  authorization URL (202). The flow then finishes in the background.
- **Non-interactive mode** (boot reconnect, tool calls, backoff): the handlers
  raise `AuthorizationRequired` at once ⇒ `auth_status=expired`,
  `mcp_plugin_reauthorization_required`. A tool call never waits on a browser.
- `complete_oauth(code, state, iss)`: unknown/expired/used state ⇒
  `mcp_oauth_state_invalid` (single use); if the AS metadata says
  `authorization_response_iss_parameter_supported` then `iss` must equal the
  metadata issuer, else `mcp_oauth_issuer_mismatch`; `error=` from the AS ⇒
  `auth_status=failed`, code `mcp_oauth_denied`.
- No refresh token (Circuit Toolbox advertises `grant_types_supported:
  ["authorization_code"]`) ⇒ at expiry the plugin goes `auth_status=expired`,
  `connection_status=disconnected`; the UI shows "Reconnecter".
- Manual fallback: `bearer` ⇒ header `Authorization: Bearer <value>`;
  `header` ⇒ `header_name` matching `^[A-Za-z0-9-]{1,64}$`, not in
  `{host, cookie, content-length, transfer-encoding, connection, mcp-session-id,
  mcp-protocol-version}`; value ≤ 4096 chars, no CR/LF. Sent only to the
  plugin origin (static headers set on the MCP request, not on the client, so
  AS requests never carry them).

### 5.4 Remote session (`jarvis/adapters/remote_mcp.py`)

`SdkRemoteMcpConnector.open(plugin, auth: AuthMaterial, prompt: AuthorizationPrompt | None)`
→ async context manager yielding `RemoteMcpSession` with
`initialize() -> server_identity`, `list_tools_all() -> list[dict]` (follows
`nextCursor` ≤ 10 pages, `tool.model_dump(mode="json", exclude_none=True)`),
`call_tool(name, arguments, timeout_s) -> dict` (`CallToolResult` dumped),
`on_tools_changed(callback)`. Legacy SSE is **not** implemented (D6); a server
answering `405/404` to POST with an SSE hint yields
`mcp_transport_unsupported`.

## 6. Catalog integration (D2-D3, Slice 04)

### 6.1 Native side

- `mcp_tool_meta.py`: add `TOOLS = ServerMeta(server="jarvis-tools",
  module="jarvis.runtime.tools_gateway_mcp", category="general", condition=None,
  registration="jarvis", tools={"list_tools": ToolMeta("Trouver les outils utiles",
  "read", True, "none", "structured"), "call_tool": ToolMeta("Appeler un outil de plugin",
  "destructive", False, "external", "untyped")})` and append to `SERVERS` (:293).
  `Registration` becomes `Literal["jarvis", "operator", "managed"]` (`managed` is
  used only by plugin entries in merged views, never in `SERVERS`).
- `mcp_catalog.build_introspection_server("jarvis-tools")` → `tools_gateway_mcp.build_server(tools=_Inert())`.
- `AGENT_SNAPSHOT_FLAGS["jarvis-tools"] = "tools_gateway"`; both agents'
  `snapshot()` carry `tools_gateway`.
- CC `_mcp_availability` (`control_center.py:4689-4743`) maps
  `"jarvis-tools": "tools_mcp"` like console (no switch).

### 6.2 External descriptor (`ExternalToolDescriptor`, domain)

Produced by `normalize_remote_tool(plugin, raw: dict) -> ExternalToolDescriptor | Rejection`:

| Field | Rule |
| --- | --- |
| `tool_id` | `f"{plugin_id}.{name}"` (D3) |
| `plugin_id`, `name` | wire name must match `^[A-Za-z0-9_.-]{1,128}$` else rejected `mcp_tool_name_invalid` |
| `title` | `title` or `annotations.title`, ≤ 80, control chars stripped |
| `description` | ≤ 4 096 UTF-8 bytes (cut on a character boundary + ` …[tronqué]`) |
| `input_schema` | object schema, compact JSON ≤ 16 KiB, depth ≤ 12, else rejected `mcp_tool_schema_too_large` |
| `output_schema` | kept if ≤ 16 KiB, else dropped |
| `side_effect` | `read` if `readOnlyHint` true; else `write` if `destructiveHint` is false; else `destructive` (MCP default) |
| `idempotent` | `idempotentHint` or false; `atomicity="external"`; `open_world` = `openWorldHint` (default true) |

Plugin bounds: ≤ 200 tools, ≤ 512 KiB of normalized descriptors; excess tools
are rejected with `mcp_tool_list_too_large` (listed in `rejected_tools`).
Duplicate wire names inside one plugin: the second is rejected.

### 6.3 Merge (runtime, `mcp_catalog.py`)

- `describe_external_tool(d: Mapping) -> dict`: the §2 descriptor shape of
  `docs/mcp/tool-contract.md` with `server=plugin_id`, `qualified_name=tool_id`,
  `category="external"`, `label=title or name` (≤ 48), `parameters=parameters_of(input_schema)`,
  `parameter_rules=[]`, `output={format: "structured" if output_schema else "untyped", …}`,
  `deprecation=None`, `context_bytes=model_visible_bytes(...)`, plus
  `invocation="managed_external"`, `plugin_id`.
- `merge_external(native: dict, external: dict | None) -> dict`: returns the
  same `{categories, servers, tools, unavailable}` shape; plugin servers have
  `registration="managed"`, `module=None`, `condition=None`; Core unreachable ⇒
  `unavailable += [{"server": "plugins", "category": "external", "error": "core_unreachable"}]`,
  natives unaffected. `list_view`/`detail_view` must stop calling
  `server_meta()` for non-native servers (today `list_view` :390-395 would
  raise `KeyError` on a plugin).
- Plugin availability fact (no new state enum; inspector badges reuse):
  `{"state": "advertised" if enabled and connected else ("disabled" if not enabled else "known"),
  "condition": None, "condition_value": None, "next_launch": None, "advertised": None,
  "pending_restart": False, "enabled", "connection_status", "auth_status"}`.
- CC `GET /api/mcp/tools` = `list_view(merge_external(cached_catalog(), core.get("/v1/mcp/tools")))`
  with a 2 s Core timeout; `GET /api/mcp/tools/{server}/{name}` works for
  `server=plugin_id` (D9). The native catalog stays built once per process
  (`cached_catalog` :258); the external part is re-read per request
  (`since_revision` cache).

## 7. Gateway `jarvis-tools` (D1, D2, D7, Slice 04)

### 7.1 Server (`jarvis/runtime/tools_gateway_mcp.py`)

- `SERVER_NAME = "jarvis-tools"`, CLI `python -m jarvis tools-mcp`
  (`app.py` subparser next to `console-mcp`, :56), `serve_stdio()`.
- `ToolsGatewayTarget(core_host, core_port, token_file, runtime_root, native_servers: tuple[str, ...], agent: Literal["claude","codex"])`,
  `env()` adds `JARVIS_TOOLS_NATIVE_SERVERS` (comma list) and
  `JARVIS_TOOLS_AGENT`; `from_env()`; `mcp_config(target)` /
  `write_mcp_config(target, directory)` (atomic, same as `display_mcp.py:263`);
  `codex_config_overrides(target) -> list[str]` (§8.2).
- `build_server(target=None, *, tools=None)`; tools registered with
  `annotations=tool_annotations(SERVER_NAME, name)`; `instructions` ≤ 1 200 B.
- Tool schemas (strict, `additionalProperties: false`):

```text
list_tools(intent: str [1..500 chars], cursor: str | None = None, limit: int [1..60] = 30) -> structured
call_tool(tool_id: str [^[a-z0-9][a-z0-9-]{0,31}\.[A-Za-z0-9_.-]{1,128}$ or mcp__…], arguments: object = {}) -> untyped
```

Descriptions (FR, short) must say: call `list_tools` again whenever a new need
appears (repeated discovery is normal); `recommended` entries are immediately
callable; `direct_native` tools are called by their `call_as` name, never
through `call_tool`. Context budget of the two tools (name + description +
input schema) ≤ **2 500 B**, instructions ≤ **1 200 B** (tests).

### 7.2 `list_tools` algorithm (runs in the gateway process — §14 C2)

1. Native candidates: `mcp_catalog.cached_catalog()` filtered to
   `target.native_servers`, excluding `jarvis-tools` itself; entry id =
   `qualified_name` (`mcp__<server>__<name>`), `invocation="direct_native"`,
   `call_as=qualified_name`. Operator servers (`jarvis-drive`) are never
   included (§14 C8).
2. External candidates: `GET /v1/mcp/tools?since_revision=<cached>` (cache by
   revision in the gateway process); Core unreachable ⇒ natives only +
   `notes:["plugins_unavailable"]`.
3. Rank with `tool_relevance.rank(intent, docs)` (§7.4).
4. `tool_discovery.build_list_response(ranked, cursor, limit, budget)`:

```json
{"intent": "…", "catalog_revision": "n<native_fp8>.e<ext_rev>",
 "recommended": [{"id", "name", "invocation", "call_as"?, "source", "description",
                  "input_schema", "side_effect"}],
 "others": [{"id", "summary", "source", "side_effect", "invocation"}],
 "next_cursor": "…" | null, "total": 123, "notes": []}
```

- `recommended`: ≤ 5, only score > 0 and ≥ 0.35 × top score; FULL
  description + input_schema; packed greedily while the recommended part
  ≤ 16 KiB (the top hit always fits: 4 KiB description + 16 KiB schema cap is
  bounded by rejecting at ingestion any tool whose full entry > 16 KiB from
  recommendation — it stays callable and appears in `others` with
  `"detail":"too_large"`).
- `others`: every remaining accessible tool in rank order then id, `summary` =
  first line of description ≤ 120 chars, `source` = server or plugin
  display name; page size `limit`; filled until the **whole response ≤ 24 576
  bytes** (`json.dumps(..., ensure_ascii=False, separators=(",", ":"))`
  encoded UTF-8); `next_cursor` = urlsafe-base64 JSON `{r: revision, o: offset,
  h: sha1(intent)[:8]}`; a cursor whose revision differs restarts at 0 with
  `notes:["catalog_changed"]`; a cursor for another intent → `mcp_cursor_invalid`.
- Empty intent after folding ⇒ `recommended: []`, `others` alphabetical.
- Returned as structured output (FastMCP `structuredContent`, which the Claude
  CLI shows the model as compact JSON, `tool-contract.md` §10.3).

### 7.3 `call_tool`

`tool_id` starting with `mcp__` or matching a native qualified name ⇒ tool
error `native_tool_call_directly` with `call_as`. Otherwise POST Core
`/v1/mcp/tools/call`. `ToolCallOutcome`: `{ok: bool, code?: str, message?: str,
content: [{"type":"text","text"}…], structured?: object, truncated: bool}`;
the gateway returns `content` as MCP text blocks (`isError` when `ok` false or
the remote result `isError`). Core bounds: arguments JSON ≤ 64 KiB, object
type, required keys of the descriptor present, unknown keys refused when the
schema is closed (domain check, no `jsonschema` dependency in Core); result
text ≤ 32 KiB total (cut + `truncated: true`); non-text content blocks are
summarized `{"type":"text","text":"[image omise]"}` in V1; timeout default 60 s,
max 120 s. Stable codes (§9). Every call journaled
`mcp.plugin.tool_called {plugin_id, tool, ok, code, duration_ms, bytes}` —
never arguments or result text.

### 7.4 Relevance (`jarvis/domain/tool_relevance.py`, D7)

Repo search: no reusable ranking helper. `adapters/markdown_memory.py:80-146`
uses SQLite FTS5 `bm25()` with `unicode61 remove_diacritics 2`, but FTS5 is
optional there (fallback `LIKE` path) and `sqlite3` is forbidden in domain;
accent folding is duplicated inline (`markdown_memory.py:250-251`,
`core/actions.py:111-112`). So: pure Python, stdlib only.

```python
def fold(text: str) -> str                      # NFKD, drop combining, casefold
def tokens(text: str) -> list[str]              # split non-alnum + snake/camel/kebab, fold, drop FR/EN stopwords, light stem
SYNONYMS: dict[str, frozenset[str]]             # small bilingual groups: mail/email/courriel/message; envoyer/send;
                                                # agenda/calendar/calendrier/evenement/event/meeting/reunion; contact/personne/people/user;
                                                # fichier/file/document/doc; chercher/search/find/trouver/lookup; lire/read/get/fetch;
                                                # creer/create/add/ajouter/new; supprimer/delete/remove; modifier/update/edit
@dataclass(frozen=True) class ToolDoc: id, name, label, description, param_names, param_texts, source
def rank(intent: str, docs: Sequence[ToolDoc]) -> list[tuple[ToolDoc, float]]
```

BM25F-style: k1 = 1.2, b = 0.75, field weights name 3.0, label 2.0,
param names 1.5, description 1.0, param descriptions + enum values 0.75;
query expansion by synonym group at weight 0.6; IDF over the accessible set
of the call; tie-break `(-score, source_order, id)`; deterministic (no
randomness, no time). Light stem: strip one of `s, x, es, ing, ed, ment, tion→t`.
Quality gate: a fixture corpus (native catalog + fake Circuit-like tools) with
≥ 20 FR/EN intents and expected top-3 membership (recall@3 ≥ 0.9).

## 8. Propagation (D8, Slice 05)

### 8.1 Claude (`jarvis/runtime/claude_local.py`)

- New ctor arg `tools_mcp: ToolsGatewayTarget | None`; `_tools_mcp_args()`
  like `_console_mcp_args` (:923-950): **conversation profile only**, always
  on, written after display/barehands/console args are known so
  `native_servers` = the servers actually declared this launch
  (`jarvis-console` + optional display/barehands). Failure to write ⇒ journal
  `agent.tools_mcp_failed` (error), brain starts without it.
- Order in argv: after `*console_args` (:853). `snapshot()["tools_gateway"]`.
- `RESTRICTED_PROFILES` (:226) unchanged: `--strict-mcp-config`, no gateway.
  `job_result` unchanged (no native MCP in V1, :777-782), documented.
- Prompt: `BRAIN_TOOLS_PROMPT` constant in `claude_local.py`, included in the
  four conversation programs like `BRAIN_SETTINGS_PROMPT` (:165) and declared
  in `runtime/prompt_catalog.py` (:139 pattern); fingerprint tests updated.
- CC wiring: `ControlCenter(..., tools_mcp=ToolsGatewayTarget(...))` built in
  `app.py` from the same `settings.core_host/port/token_file` as
  `DisplayMcpTarget`; `_apply_agent_settings` (:1194-1247) sets
  `agent.tools_mcp` for both CLIs.

### 8.2 Codex (`jarvis/runtime/codex_local.py:253-273`)

`_turn_command` appends, before `-`, the output of
`codex_config_overrides(target)`:

```text
-c mcp_servers.jarvis-tools.command='<python>'
-c mcp_servers.jarvis-tools.args=['-m','jarvis','tools-mcp']
-c mcp_servers.jarvis-tools.env={JARVIS_CORE_HOST='…',JARVIS_CORE_PORT='…',JARVIS_CORE_TOKEN_FILE='…',JARVIS_RUNTIME_DIR='…',JARVIS_TOOLS_NATIVE_SERVERS='',JARVIS_TOOLS_AGENT='codex'}
-c mcp_servers.jarvis-tools.tool_timeout_sec=130
```

Verified on this machine (codex-cli 0.157.0, through the npm `codex.cmd`
shim, `asyncio.create_subprocess_exec`, paths with spaces): `codex mcp get
jarvis-tools --json` shows command/args/env exactly. Values use TOML
**literal** strings `'…'` (no escaping, safe through `cmd.exe`); a value
containing `'` or a control char falls back to a JSON-escaped basic string
(`toml_value()` helper, tested). Applies to `exec` and `exec resume`.
`native_servers` is empty for Codex (it receives no native server).
`CodexLocalAgent.snapshot()["tools_gateway"]` true once armed; the CC
catalog's Codex rule (tool-contract §4.3 amendment C1) is amended for
`jarvis-tools` only.

### 8.3 Delegated subagents (Claude)

Jarvis does not launch subagents; the CLI's `Agent` tool does
(`routing_hook.py:3-7`). Official docs (sub-agents page): "`tools` —
inherits all if omitted"; MCP servers can also be scoped with a `mcpServers`
frontmatter field. Docs are **silent** on whether servers passed by
`--mcp-config` are inherited (§15 Q1). V1 relies on inheritance (same CLI
process, same MCP clients, same gateway env) and **Slice 05 must prove it with
a real trace** (a general-purpose subagent calling
`mcp__jarvis-tools__list_tools`). Fallback adapter if disproved: pass
`--agents` JSON defining Jarvis's delegation agent with
`mcpServers: ["jarvis-tools"]` (reference by name) — designed, not built.
The routing hook's charter (`routing_hook.charter_input`) may carry one line
reminding subagents of `list_tools`; it never carries credentials.

## 9. Stable error codes

`mcp_plugin_unknown` 404, `mcp_plugin_duplicate` 409, `mcp_endpoint_invalid` 400,
`mcp_endpoint_forbidden` 400 (SSRF), `mcp_vault_unavailable` 409,
`mcp_connector_unavailable` 503, `mcp_plugin_disabled` 409,
`mcp_plugin_disconnected` 409, `mcp_plugin_reauthorization_required` 409,
`mcp_oauth_state_invalid` 400, `mcp_oauth_issuer_mismatch` 400,
`mcp_oauth_denied` 400, `mcp_transport_unsupported` 502, `mcp_remote_unreachable` 502,
`mcp_remote_tls` 502, `mcp_remote_protocol` 502, `mcp_response_too_large` 502,
`mcp_remote_timeout` 504, `mcp_remote_tool_error` (200, `ok:false`),
`mcp_tool_unknown` 404, `native_tool_call_directly` 400,
`mcp_arguments_invalid` 400, `mcp_cursor_invalid` 400,
`mcp_tool_name_invalid` / `mcp_tool_schema_too_large` / `mcp_tool_list_too_large`
(ingestion rejections). Messages are Jarvis sentences; a remote error text
reaches the model only through `mcp_remote_tool_error`, bounded to 4 KiB and
passed through `redact(text, known_secrets)` (domain: replaces every vault
value of that plugin and `Bearer\s+\S+`, `[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}` JWT shapes).

## 10. Control Center (D9, Slice 06)

### 10.1 Routes (`jarvis/runtime/mcp_plugin_routes.py`, relay to Core)

| CC route | Core | Guard |
| --- | --- | --- |
| `GET /api/mcp/plugins` | `GET /v1/mcp/plugins` | `READ_GUARDED_ROUTES` (endpoints are private data) |
| `POST /api/mcp/plugins` | `POST /v1/mcp/plugins` | guarded |
| `PATCH /api/mcp/plugins/{id}` | `PATCH …/{id}` | guarded |
| `POST /api/mcp/plugins/{id}/connect` | `POST …/connect` | guarded |
| `PUT /api/mcp/plugins/{id}/credential` | `PUT …/credential` | guarded; body never journaled |
| `POST /api/mcp/plugins/{id}/disconnect` / `/refresh` | same | guarded |
| `DELETE /api/mcp/plugins/{id}` | `DELETE …/{id}` | guarded |
| `GET /api/mcp/oauth/callback?code&state&iss&error` | `POST /v1/mcp/oauth/callback` | **not** in `READ_GUARDED_ROUTES` (the AS redirect is a cross-site top-level navigation, §14 C6); Host must be loopback; answers a static HTML page (FR: "Autorisation reçue, vous pouvez fermer cet onglet" / coded failure), `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, never echoes `code`/`state` |

Relay semantics copy `board_routes.py` (status + JSON body verbatim, Core
unreachable ⇒ 503 `core_unreachable`). `_mcp_json_errors` (:1600-1619)
keeps "read-only (GET)" wording for `/api/mcp/tools*` only; 405 under
`/api/mcp/plugins*` says `method_not_allowed` with the real `Allow`.
Invariant restated for tool-contract §8: **no tool-execution route exists in
the CC** (`call_tool` is Core-only, reached by the gateway).

`redirect_uri` = `http://127.0.0.1:<ui_port>/api/mcp/oauth/callback` (RFC 8252
loopback). A port change makes the stored `client_info.redirect_uris`
mismatch ⇒ Core drops `client_info` and re-registers.

### 10.2 UI

- Same dock button `#openMcpInspector`, same dialog `#mcpInspector`; a
  two-tab switch at the dialog top: "Exposition interne" (today's inspector,
  unchanged) / "Plugins externes".
- New module `control_center_mcp_plugins.js`, injected at
  `/*__CONTROL_CENTER_MCP_PLUGINS_JS__*/` (constants in `control_center.py`
  beside `MCP_INSPECTOR_SCRIPT_*` :484-489). It owns every write call; the
  inspector module keeps its GET-only client unchanged (§10.7 invariant stays
  true and tested).
- Cards: icon (`icon_url` via `<img referrerpolicy=no-referrer>` with
  letter fallback; CSP-safe), display name, host, connection + auth badge,
  enable toggle (PATCH), tool count, "Gérer". Add flow: URL → create →
  connect(auto) → 202 ⇒ `window.open(authorization_url, "_blank", "noopener")`
  + poll `GET /api/mcp/plugins` every 2 s ≤ 5 min; `auth_status=required`
  with no OAuth metadata ⇒ manual form (Bearer / en-tête personnalisé,
  password input, write-only).
- Manage view: actions Reconnecter / Déconnecter / Supprimer (confirm) /
  Actualiser; tool list = `/api/mcp/tools` rows whose `server == plugin_id`,
  expanded through the **existing inspector detail renderer** (the inspector
  module exposes one function, e.g. `M.renderToolDetail(host, descriptor)` or
  opens itself on the external category filtered by server). No second tool
  viewer, no tool name literal in either module.

## 11. Drive (D10, Slice 07)

Three Drive paths exist today, all built on `adapters/google_drive.py` +
OAuth files (`GOOGLE_DRIVE_CLIENT_SECRET`, `GOOGLE_DRIVE_TOKEN`):
(1) `jarvis-drive` stdio (`drive_mcp.py`, operator `claude mcp add --scope
user`, `ServerMeta registration="operator"`), (2) Core voice tools
`DriveService` via `JARVIS_DRIVE_PROVIDER=google` (`app.py:268-285`,
`core/drive_service.py:15`), (3) `python -m jarvis drive-auth`. Classification:
**legacy operator-managed local stdio**, not a remote MCP; not migrated.
Migration criteria (future): a hosted remote Drive MCP with OAuth PRM,
parity for the 7 operations, rollback = keep `jarvis-drive` registered until
parity is proven. Slice 07 proves no regression (catalog still lists it,
introspection still works, `list_tools` does not claim it).

## 12. Docs owned (D11)

Slice 01 amends `docs/mcp/tool-contract.md`: §1 table (barehands **16** tools,
not 5; add `jarvis-tools`; line anchors refreshed), §4.3 (Codex amendment C1
exception for `jarvis-tools`; plugin availability fact), §5.3 (replace "no
meta-tool" by: exactly one discovery server `jarvis-tools` with `list_tools` +
`call_tool`, budgets of §7.1/§7.2), §8 (management routes, no execution
route in CC). New `docs/mcp/plugins.md`: lifecycle/states, auth strategies,
vault, SSRF policy, error codes, list_tools/call_tool contract, propagation
matrix, Drive status. Slice 08 updates `docs/ARCHITECTURE.md`,
`docs/SECURITY.md`, `docs/OPERATIONS.md` (plugin ops), `docs/state-model.md` (v4).

## 13. Test inventory (names are binding; content per SLICE contract)

| File | Slice |
| --- | --- |
| `tests/unit/test_mcp_plugin_domain.py`, `test_mcp_endpoint_policy.py` | 02, 03 |
| `tests/unit/test_mcp_plugin_store_sqlite.py`, `test_schema_migrations.py` (existing, v4 snapshot) | 02 |
| `tests/unit/test_credential_vault.py`, `test_dpapi_sealer.py` (skip off-Windows) | 02 |
| `tests/unit/test_mcp_plugin_service.py`, `test_mcp_protocol_routes.py` | 02-04 |
| `tests/fakes/fake_remote_mcp.py` (FastMCP streamable-HTTP app + fake OAuth AS on 127.0.0.1, configurable: auth none/oauth/bearer, no-refresh, iss, tool mutations, huge schema, secret-looking errors) | 03 |
| `tests/unit/test_mcp_http_policy.py`, `test_mcp_oauth_adapter.py`, `tests/integration/test_remote_mcp_connector.py` | 03 |
| `tests/unit/test_tool_relevance.py`, `test_tool_discovery.py`, `test_tools_gateway_mcp.py`, `test_mcp_catalog.py` (amended) | 04 |
| `tests/unit/test_claude_tools_gateway_args.py`, `test_codex_agent.py` (amended), `test_prompt_*` (fingerprints) | 05 |
| `tests/unit/test_control_center_mcp_plugins_api.py`, `test_control_center_mcp_plugins_js.py`, `test_control_center_mcp_api.py` + `test_control_center_mcp_inspector_js.py` (amended) | 06 |
| `tests/unit/test_v2_architecture.py` (exception +1) | 02 |

## 14. Contradictions found

- **C1 — "Core (the Control Center process)" (D1, D5).** Core and the CC are
  two processes (§0). Resolution: Core daemon owns registry, vault,
  connections, OAuth state and execution (satisfies "not dependent on the
  browser" and D4's `jarvis.sqlite3`, which only Core opens). The CC relays UI
  routes and hosts the browser-facing OAuth callback.
- **C2 — "Core owns relevance" / "gateway is a thin proxy" (D1, D7).**
  `test_core_does_not_import_runtime_modules` forbids `jarvis/core` from
  importing `jarvis.runtime.mcp_catalog`/`mcp_tool_meta`/native servers, so
  Core cannot see the native catalog. Resolution: ranking + budget are pure
  domain modules executed in the gateway process (runtime layer), which has
  the native catalog in-process and fetches external descriptors from Core.
  `call_tool` stays a thin proxy.
- **C3 — Core layering.** Core may not import `httpx`, `aiohttp`, `sqlite3`,
  the `mcp` SDK adapters or DPAPI. Resolution: ports + adapters injected from
  `app.py:_run_core_v2`; the SQLite registry adapter needs one new
  `CORE_ADAPTER_IMPORT_EXCEPTIONS` entry (precedent `sqlite_workspace_board`).
- **C4 — `/v1/tools/call` already exists** (voice `CoreToolRouter` with the
  confirmation broker). New routes live under `/v1/mcp/*`.
- **C5 — `tests/unit/test_mcp_catalog.py:188-195`** asserts no catalog tool
  named `list_tools|get_tool|…`. D1 (gateway in `SERVERS`) must amend this
  test deliberately (exempt `jarvis-tools` only), together with §5.3; and
  `test_control_center_mcp_api.py:~372-387` asserts only two `/api/mcp`
  routes and the "read-only" 405 text — amended in Slice 06.
- **C6 — OAuth callback under `/api/mcp/plugins/…` (D9).** If that prefix is
  read-guarded (it must be: endpoints + writes), the AS redirect arrives
  cross-site and `_loopback_refusal` rejects it. Resolution: callback at
  `/api/mcp/oauth/callback`, outside the guarded prefix, protected by
  single-use state, TTL, `iss` check and a loopback Host check.
- **C7 — Board wiring lost in Core (pre-existing, not this task).** HEAD
  `core/v2_app.py` has no `BoardService`/`sqlite_workspace_board` import:
  merge `b8c3ba1` dropped it (present at `bcaf3b0`, 43 matches; 0 after).
  `protocol/server.py:905-931` calls `self.core.boards` ⇒ `/v1/boards*` fail;
  `test_core_adapter_exceptions_stay_minimal` should be red (stale
  exception). Slice 02 edits the same file: agent 0 must decide
  (fix first vs. baseline) — see READINESS §Baseline.
- **C8 — "native tools the runtime actually has" (D2).** The conversation
  profile loads operator servers (no `--strict-mcp-config`), but Jarvis cannot
  know them (tool-contract §4.3 `known`). V1 excludes operator servers from
  `list_tools`; the model still sees them natively via ToolSearch.
- **C9 — SDK gaps for D5.** The SDK does not check RFC 9207 `iss`, restores
  stored tokens without expiry, and would run an interactive flow on any 401
  (including during a tool call). Resolution: `JarvisOAuthProvider` +
  non-interactive mode (§5.3).
- **C10 — tool-contract §4.3 Codex amendment C1** ("Codex never receives native
  servers") becomes false for `jarvis-tools`; amended in Slice 01.
- **C11 — stale docs.** tool-contract §1 says barehands has 5 tools; metadata
  has 16 (`jarvis-display` 13, `jarvis-console` 12, `jarvis-drive` 7 match).
- **C12 — `Registration`** is `jarvis|operator`; merged plugin servers need
  `managed`, and `list_view` calls `server_meta()` (KeyError for plugins).

## 15. Open questions (not resolvable from code)

Agent 0 decisions (READINESS): Q2 resolved as in §5.3; Q3 resolved — no
confirmation gate in V1. Q1, Q4, Q5 are Slice 05 trace obligations.

- **Q1** Subagent inheritance of `--mcp-config` servers: docs silent; proven or
  refuted by the Slice 05 trace; fallback adapter §8.3.
- **Q2** Circuit Toolbox DCR: does it accept `grant_types` containing
  `refresh_token` when it only supports `authorization_code`, and does it accept
  an `http://127.0.0.1:<port>` redirect URI? Fake AS covers both answers;
  Slice 07 records the real one (fallback: register
  `grant_types=["authorization_code"]`).
- **Q3** Confirmation policy for `destructive` external tools (e.g. send
  mail): V1 applies none beyond the CLI permission mode (brain runs
  `bypassPermissions`, native write tools have no gate either). Recommendation:
  keep V1 without gate; Slice 07 calls read-only tools only. Needs Human/agent-0
  confirmation before release.
- **Q4** Codex MCP approvals in non-bypass sandbox modes (`-c sandbox_mode=…`,
  `codex_local.py:266-268`): does `codex exec` auto-approve MCP tool calls?
  Slice 05 records it with a trace.
- **Q5** Whether `ENABLE_TOOL_SEARCH` deferral hides `jarvis-tools` behind
  ToolSearch on the real API (tool-contract §10.8); if so the prompt must name
  `mcp__jarvis-tools__list_tools` explicitly. Slice 05 measures.

## 16. Errata after Slice 01 (agent 0, binding)

- E1 `CORE_ADAPTER_IMPORT_EXCEPTIONS` lives in `tests/unit/test_v2_architecture.py:35`, not in `core/v2_app.py`.
- E2 Agent MCP targets are set in `ControlCenter._configure_agent` (`control_center.py:1205`), called by `_apply_agent_settings`. Slice 05 edits `_configure_agent`.
- E3 §7.2: a tool whose full recommended entry exceeds 16 KiB is never recommended; it appears in `others` with `"detail":"too_large"` and stays callable.
- E4 Endpoint refusals: syntax problems (scheme, userinfo, fragment, credential-like query, length, IDNA) → `mcp_endpoint_invalid`; any forbidden address — IP literal at validation time or DNS-resolved in `PolicyTransport` — → `mcp_endpoint_forbidden`.
- E5 For plugins, availability `advertised` means enabled ∧ connected (documented in plugins.md).
- E6 `catalog_revision` is the string `n<native_fp8>.e<ext_rev>` everywhere model-facing and in the cursor field `r`; Core's `/v1/mcp/*` keep the integer `catalog_revision` (external part only).
- E7 The ` …[tronqué]` suffix counts inside the 4 096-byte description bound.
- E8 Unknown paths under `/api/mcp/plugins*` are answered by `mcp_plugin_routes.py` itself: `404 mcp_plugin_unknown` (unknown id) / `404 not_found` (unknown sub-path); `_mcp_json_errors` keeps `mcp_tool_unknown` for `/api/mcp/tools*` only.
- E9 Codex `_turn_command` is at `codex_local.py:253-273` (as originally written; Slice 01's 252-272 was wrong).
- E10 Disconnect also attempts best-effort token revocation (RFC 7009) when the AS metadata advertises a `revocation_endpoint`; failure is journaled (code only) and never blocks the local forget. Circuit Toolbox advertises none (local forget only).
- E11 The plugin meaning of `advertised` is documented in tool-contract §4.3 (plugins.md points there).
- E12 (after Slice 02) Boot reconnect also covers static strategies: an `enabled` plugin with `auth_strategy ∈ {bearer, header}` and `auth_status ∈ {unknown, authorized}` is reconnected non-interactively at `start()`; the first successful connect sets `authorized`, a 401 sets `failed`. Slice 03 implements it.
- E13 (after Slice 02) Accepted deviations, now canonical in `docs/mcp/plugins.md`: codes `mcp_plugin_invalid` (400), `mcp_plugin_store_unreadable` / `mcp_plugin_store_failed` (500); `localhost`/`*.localhost` refused without the dev flag; new plugins start `enabled=True`; `disconnect` resets `auth_strategy` to `none`; shared `immediate_transaction` helper in `sqlite_state`; `start()` never raises (journals, routes answer 500).
- E14 `tests/integration/test_conversation_event_store_recovery.py:103` still expects schema v2 against the live DB; it's opt-in (`JARVIS_TEST_REAL_STATE_DB=1`) and was already stale at v3. Out of scope; noted in `Issues/`.
- E15 (after Slice 03) Accepted, canonical in `docs/mcp/plugins.md`: `max_redirects=20` on the httpx client (httpx counts every OAuth-flow hop; same-origin-only redirect following and no cross-origin credential forwarding stay enforced by the SDK/PolicyTransport — QA verifies); Core start and `stop()` set `connected` rows to `disconnected`; one authorization per explicit connect (step-up inside a connect ends `failed`, next Reconnect asks the wider scope); `connect` bodies carry the `plugin` view; `ui_port` from `JARVIS_UI_PORT`; `McpPluginService.invoke()` is the call primitive Slice 04's `call` builds on.
