# Target architecture

## 1. Plugin model

Introduce one Jarvis-owned plugin registry with a contract equivalent to:

```text
McpPlugin
  id                  stable local id
  display_name
  endpoint
  endpoint_origin
  icon                 optional remote/local metadata, bounded and sanitized
  transport
  protocol_profile
  enabled
  connection_status
  auth_status
  auth_strategy
  credential_ref       opaque secret-vault reference only
  discovered_server_identity
  capability_revision
  last_discovered_at
  last_error_code      safe/redacted
```

Do not persist access tokens, refresh tokens, API keys or custom auth headers directly in ordinary plugin config.

## 2. Connection manager

A `RemoteMcpConnectionManager` (exact name follows repo conventions) owns:

- endpoint validation and transport negotiation;
- remote MCP discovery and capability refresh;
- authorization discovery and OAuth browser flow;
- manual bearer/API-key/custom-header fallback where standards discovery is unavailable;
- token refresh/expiry/step-up;
- pooled/reused remote sessions where protocol semantics permit it;
- retry/backoff and per-plugin failure isolation;
- redacted health/status surfaced to the Control Center.

Prefer modern remote MCP HTTP transport. Support legacy behavior through an adapter only when tests prove the compatibility need.

## 3. Credential vault boundary

All auth material lives behind a vault interface. Requirements:

- encrypted/OS-backed storage where the platform provides it, with a repository-compatible fallback contract for tests;
- no secret values in `McpPlugin`, catalog descriptors, MCP tool results, normal journal events, browser payloads, or model context;
- credential entries bound to the expected plugin/resource/origin/issuer;
- disconnect/revoke clears or revokes credentials where supported;
- static tokens/custom headers can be replaced without recreating the whole plugin.

## 4. Canonical global tool registry

Extend the existing canonical catalog rather than duplicating it. Native server introspection and managed-remote MCP introspection should normalize into one descriptor model.

External descriptors need at least:

- stable `tool_id` / qualified name, namespaced by plugin;
- plugin id + server identity;
- wire tool name;
- description;
- input schema;
- output schema when advertised;
- side-effect/open-world hints when advertised or conservatively classified;
- enabled/connected/available state;
- descriptor/capability revision;
- invocation mode (`direct_native` vs `managed_external` or equivalent).

Remote descriptions/schemas are untrusted and size-bounded.

## 5. Agent-facing discovery gateway

Expose a stable Jarvis capability gateway to normal agent runtimes. Its core discovery contract is:

```text
list_tools(intent, ...optional bounds/cursor...)
  -> recommended[]   # FULL actionable descriptor/schema
  -> others[]        # compact descriptor only
  -> continuation?   # when catalog cannot safely fit
  -> catalog_revision
```

The recommended set must be small and immediately callable. `others` must preserve enough identity/summary/provider information for the agent to notice that another tool may fit and issue a new `list_tools(intent)` call.

Tool selection should use a tested hybrid relevance approach over tool name, description, schema terms, capability metadata and semantic matching. Do not make a paid/external embedding dependency mandatory unless the existing repository already provides one suitable for this path.

`get_tool(tool_id)` may remain for UI/debug/backward compatibility, but the recommended discovery path cannot require it after `list_tools(intent)`.

## 6. Generic execution gateway

Provide a stable `call_tool(tool_id, arguments)` or repository-equivalent execution primitive for managed external MCP tools.

The gateway:

- validates that plugin is enabled and connected;
- resolves the latest matching descriptor/revision;
- validates/bounds arguments before dispatch when possible;
- attaches auth below the model boundary;
- calls the remote MCP;
- normalizes protocol errors into stable Jarvis codes without swallowing server details that are safe/useful;
- never exposes tokens/headers;
- records redacted trace evidence.

## 7. Agent and subagent propagation

Normal Jarvis conversational agents should receive the same stable discovery/execution gateway. Delegated subagents should inherit access to that gateway through the host runtime or an explicit Jarvis adapter, rather than copying plugin secrets into subagent prompts/configs.

Claude and Codex paths must both be validated. The current repository has asymmetric MCP wiring; Slice 05 owns resolving that asymmetry.

Existing intentionally restricted profiles (`speculative_analysis`, `presentation_preparation`, or current equivalents) remain restricted unless an explicit product contract says otherwise.

## 8. Control Center

Refactor the existing MCP inspector into a broader MCP center without losing its source-of-truth behavior.

Suggested navigation:

```text
MCP
  Internal exposure
  External plugins
```

External plugin cards show icon/fallback, name, host/origin, connected/auth state, enabled toggle, tool count and Manage. `+ Add plugin` begins with URL and continues through discovery/auth. The plugin detail view reuses the existing tool inspector descriptor rendering.

## 9. Security boundary for user-supplied endpoints

At minimum:

- HTTPS by default; explicit local-development exception;
- reject malformed/suspicious endpoint forms;
- no credentials in URL query/fragment;
- bounded redirects and no auth-header forwarding to a changed origin/issuer;
- SSRF protections for metadata/link-local/private ranges unless explicitly approved local development behavior applies;
- bounded response/schema/tool-list sizes;
- robust parsing of untrusted metadata;
- one plugin failure never breaks the native catalog or other plugins.
