# MCP plugins and intent-aware tool discovery

Handoff `tasks/jarvis-generic-mcp-plugin-runtime/`, Slice 01 (contract).
**Status: target contract, implemented by Slices 02–07 of
`jarvis-generic-mcp-plugin-runtime`. Nothing in this document is shipped at
`6aabefd` unless a sentence says "today".** Binding design:
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
| `tools` | last discovered `ExternalToolDescriptor`s, bounded (§5) |
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
- **Disconnect** closes the session **and forgets its credentials**; the row
  stays (`auth_status` back to `unknown`/`required` on the next connect).
- **Remove** = disconnect + delete the row and its credential rows in **one**
  `BEGIN IMMEDIATE` transaction.
- On Core start, rows left `connecting` are rewritten `disconnected` (a crash
  never leaves a phantom connection). Then Core reconnects in background every
  `enabled` plugin whose `auth_status` is `not_required` or `authorized` —
  **never interactively**.
- A failed connection owner ⇒ `connection_status=error` + `last_error_code`,
  reconnect with backoff `(1, 2, 5, 10, 30, 60)` s, capped, while `enabled`. A
  401 / expired token stops retries with `auth_status=expired`.
- `notifications/tools/list_changed` ⇒ re-list, bump `capability_revision`
  and the external catalog revision.

One owner `asyncio.Task` per connected plugin holds the SDK transport (it is
anyio-based and must be entered and exited in one task); other tasks call
tools on its `ClientSession` concurrently (ARCH §4.2).

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

`connect(strategy="auto")` probes and picks `none` or `oauth`. Manual
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
S256, single-use `state`, scope from `WWW-Authenticate`/metadata, and step-up
on `403 insufficient_scope`. Jarvis adds what the SDK lacks (C9):

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
re-registers.

Interactive flow (only inside an explicit `connect`):

1. `POST /v1/mcp/plugins/{id}/connect` starts the connection owner task; the
   SDK redirect handler registers a pending authorization
   `{state, plugin_id, expires_at = now + 300 s, expected_issuer}`.
2. Within 20 s, `connect` answers `200` connected, or
   `202 {"status":"authorizing","authorization_url"}`.
3. The UI opens `authorization_url`; the user consents; the AS redirects the
   browser to the CC `GET /api/mcp/oauth/callback?code&state&iss&error`, which
   relays `POST /v1/mcp/oauth/callback`.
4. `complete_oauth`: unknown, expired or already used `state` ⇒
   `mcp_oauth_state_invalid` (single use); `error=` from the AS ⇒
   `auth_status=failed`, `mcp_oauth_denied`; else tokens are sealed and the
   connection finishes in background.

**No refresh token** (Circuit Toolbox advertises only `authorization_code`):
at expiry the plugin becomes `auth_status=expired`,
`connection_status=disconnected`, and the UI offers « Reconnecter » (a new
interactive flow).

### 3.4 Non-interactive rule

Boot reconnect, backoff reconnects and **every tool call** run
non-interactively: an authorization need raises at once ⇒
`auth_status=expired`, code `mcp_plugin_reauthorization_required`. **A tool
call never waits on a browser.**

## 4. Endpoint policy and HTTP transport

### 4.1 Endpoint validation (`jarvis/domain/mcp_endpoint.py`)

`validate_endpoint(raw, *, allow_loopback_http)` normalizes the URL or refuses
with `mcp_endpoint_invalid` and a reason:

- scheme other than `https` (http only when the host resolves to loopback
  **and** `allow_loopback_http`);
- userinfo present;
- any fragment; any query key matching `token|key|secret|auth|password|sig`
  (case-folded);
- an IP-literal host that is not global;
- length > 2048; a non-ASCII host that is not IDNA-encodable.

`allow_loopback_http` = environment `JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`
(development only, read in `app.py`, journaled at Core start).

`is_forbidden_address(ip)`: `not ip.is_global`, or in `100.64.0.0/10`,
`169.254.0.0/16`, `fd00::/8`, or an `::ffff:0:0/96`-mapped private address
(stdlib `ipaddress`).

### 4.2 `PolicyTransport` (`jarvis/adapters/mcp_http_policy.py`)

One `httpx.AsyncClient`, handed to the SDK, carries **every** request of a
plugin (MCP, protected-resource metadata, AS metadata, registration, token):

- resolves the host (`loop.getaddrinfo`) and refuses when **any** resolved
  address is forbidden (loopback only under the development flag) —
  `mcp_endpoint_forbidden`;
- refuses non-https except under that flag;
- caps every response body at `MAX_RESPONSE_BYTES = 4 MiB` (streamed counter
  ⇒ `mcp_response_too_large`);
- `max_redirects=3`; the SDK follows only same-origin, method-preserving
  redirects and never forwards the bearer to another origin;
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
| `description` | ≤ 4 096 UTF-8 bytes, cut on a character boundary + ` …[tronqué]` |
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
`list_tools_all()` follows `nextCursor` over at most 10 pages.

### 5.2 In the catalog

`mcp_catalog.describe_external_tool()` maps a descriptor to the §2 shape of
[tool-contract.md](tool-contract.md) (`server = plugin_id`,
`qualified_name = tool_id`, `category = "external"`, `invocation =
"managed_external"`, `registration = "managed"`). `merge_external()` adds the
enabled ∧ connected plugins' tools to the native catalog; Core unreachable ⇒
one `unavailable` entry `{"server": "plugins", "category": "external",
"error": "core_unreachable"}`, natives unaffected. Availability of a plugin
server: tool-contract §4.3. **One catalog**: the Control Center, the
inspector and `list_tools` all read these views; no frontend copy.

## 6. Model-facing discovery: `jarvis-tools`

### 6.1 The server

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
| `next_cursor` | urlsafe-base64 JSON `{r: revision, o: offset, h: sha1(intent)[:8]}`, or null |
| `catalog_revision` | `n<native fingerprint, 8 chars>.e<external revision>` |

- A cursor whose revision differs from the current one restarts at offset 0
  with `notes: ["catalog_changed"]`.
- A cursor issued for another intent ⇒ `mcp_cursor_invalid`.
- An intent empty after folding ⇒ `recommended: []`, `others` alphabetical.
- Normal use never needs a second lookup for a recommended tool; there is **no
  `get_tool`**.

### 6.4 Relevance (`jarvis/domain/tool_relevance.py`)

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
  modifier/update/edit); query expansion weight 0.6.
- BM25F-style: k1 = 1.2, b = 0.75; field weights name 3.0, label 2.0,
  parameter names 1.5, description 1.0, parameter descriptions + enum values
  0.75; IDF over the accessible set of the call.
- Deterministic: tie-break `(-score, source_order, id)`; no randomness, no
  clock.
- Quality gate: a fixture corpus (native catalog + fake Circuit-like tools),
  ≥ 20 FR/EN intents, recall@3 ≥ 0.9.

## 7. `call_tool` semantics

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
- Timeout: default **60 s**, max **120 s** (`mcp_remote_timeout`).
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
| `POST /v1/mcp/plugins/{id}/connect` | `{strategy?: "auto"\|"none"\|"oauth"}` | 200 connected / 202 `{"status":"authorizing","authorization_url"}` |
| `PUT /v1/mcp/plugins/{id}/credential` | `{strategy: "bearer"\|"header", header_name?, value}` | `{"plugin": …}` (value never echoed) |
| `POST /v1/mcp/plugins/{id}/disconnect` | — | `{"plugin": …}` |
| `POST /v1/mcp/plugins/{id}/refresh` | — | `{"plugin": …}` |
| `DELETE /v1/mcp/plugins/{id}` | — | 200 `{"removed": id}` |
| `POST /v1/mcp/oauth/callback` | `{code, state, iss?, error?}` | `{"plugin": …}` |
| `GET /v1/mcp/tools` | `?since_revision=` | `{"catalog_revision", "unchanged": bool, "plugins": [{plugin_id, display_name, enabled, connection_status, auth_status, tool_count}], "tools": [ExternalToolDescriptor…]}` — tools of enabled ∧ connected plugins only; every plugin listed |
| `POST /v1/mcp/tools/call` | `{tool_id, arguments, caller: {agent, native_servers_count?}}` | `ToolCallOutcome` (§7) |

Core without a connector (`connector=None`) ⇒ plugins listable, `connect`
answers `503 mcp_connector_unavailable`. The external `catalog_revision` is a
monotonic in-memory int, +1 on any plugin state or tool-list change, starting
from a random base at each Core start (a value cached from an old Core never
matches).

### 8.2 Stable error codes

| Code | HTTP |
| --- | ---: |
| `mcp_plugin_unknown` | 404 |
| `mcp_plugin_duplicate` | 409 |
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

## 9. Control Center

Relay routes (`jarvis/runtime/mcp_plugin_routes.py`, pattern
`runtime/board_routes.py`, status + JSON body verbatim, Core unreachable ⇒
`503 core_unreachable`) and the callback page are listed in
[tool-contract.md](tool-contract.md) §8. Why the callback is
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
| Codex | **yes** | none (`JARVIS_TOOLS_NATIVE_SERVERS` empty: Codex receives no native server) | `-c mcp_servers.jarvis-tools.*` overrides appended by `_turn_command` before `-` (`codex_local.py:252-272`), `exec` and `exec resume`; `tool_timeout_sec=130` |

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
