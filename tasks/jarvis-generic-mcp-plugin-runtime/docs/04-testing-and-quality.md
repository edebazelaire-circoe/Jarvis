# Testing and quality

## Baseline doctrine

Every implemented Slice receives `qa-verification`. Code changes receive `code-review`. User-visible/runtime changes receive `runtime-validation`. MCP/tool/routing/agent work receives `agent-trace-analysis` with real trace evidence.

A regression introduced by the current Slice blocks progress and cannot be parked in `Issues/`.

## Automated test layers

### Contract/unit

- plugin model transitions and persistence;
- credential-vault indirection and redaction;
- endpoint validation/SSRF policy;
- OAuth discovery/PKCE/state/issuer/resource binding with deterministic fake authorization servers;
- bearer/API-key/custom-header fallback;
- token expiry/refresh and insufficient-scope behavior;
- transport negotiation and malformed protocol payloads;
- dynamic tool descriptor normalization and name collisions;
- `list_tools(intent)` relevance, FULL recommended descriptors, compact remainder, pagination/byte budget and repeated intent calls;
- generic call dispatch and stable error normalization;
- native MCP catalog parity unchanged.

### Runtime/integration

- fake remote MCP server with configurable auth and dynamic tool-list revisions;
- restart/reload behavior for enabled/disabled plugins;
- Claude normal conversation path has discovery/call gateway;
- Codex normal conversation path has equivalent capability path or explicitly documented host-supported bridge;
- delegated subagent inherits gateway access without raw credentials;
- deliberately restricted profiles remain restricted;
- UI APIs never return secrets.

### Adversarial/failure cases

Cover invalid/unreachable URLs, TLS failure, redirect origin changes, malformed `.well-known` metadata, auth refusal, expired/revoked token, insufficient scope, duplicate plugin, duplicate tool names, huge/malicious schemas, tool-list mutation, disabled plugin, connection loss, partial server failure, and secret-looking strings in remote error bodies.

## Live acceptance trace: Circuit Toolbox

Against `https://circoetoolbox-server-production.up.railway.app/mcp`, capture evidence for:

1. Add URL.
2. Discover the actual transport/auth requirements advertised at test time.
3. Complete auth if required.
4. Plugin becomes connected and enabled.
5. Tools enter the canonical global catalog.
6. `list_tools(intent)` returns a relevant Circuit Toolbox tool in `recommended` with a complete input schema.
7. `call_tool` executes a safe read-only/diagnostic tool successfully.
8. A normal Brain can perform the discovery + call.
9. A delegated subagent can perform the same through the inherited gateway without receiving credentials.
10. Disable removes it from normal availability/discovery; re-enable restores it.
11. Disconnect prevents execution and removes usable auth/session state safely.

Do not assume the server currently uses a particular auth flow. Record what it actually advertises.

## Drive compatibility validation

Classify current `jarvis-drive` as legacy/operator-managed vs managed plugin. Prove no regression while introducing the generic path. If migrated, require a documented rollback/deprecation path and equivalent core operations before deleting the old route.

## Human validation

Human validation is reserved for browser consent/login and final visual UX checks after machine tests. It does not replace OAuth protocol tests, automated accessibility checks, secret-redaction tests, or runtime traces.
