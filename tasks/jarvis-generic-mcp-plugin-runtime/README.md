# Jarvis — Generic MCP Plugin Runtime & Intent-Aware Tool Discovery

## Purpose

Turn Jarvis's existing MCP inspector/catalog into a **real generic MCP plugin system** and give the agent an intent-aware capability discovery primitive.

The user must be able to add a remote MCP server from a URL, authenticate it (OAuth when supported, token/API-key fallback when necessary), connect/disconnect it, enable/disable it, inspect its tools, and make those enabled tools available to Jarvis and its delegated subagents without teaching Jarvis provider-specific integration code.

In parallel, add or evolve the model-facing tool discovery flow to support repeated calls to **`list_tools(intent)`**. The normal result must include complete actionable schemas for the recommended tools selected for the current intent, plus a bounded compact view of the remaining accessible tools so the model can notice alternatives without paying the full schema cost for everything.

This handoff deliberately builds on the existing MCP catalog and inspector. It must **not** create a second catalog, second MCP panel, or a provider-specific `connectCircoeToolbox()` integration.

## Project identity

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Branch inspected: `main`
- Source commit inspected: `58eeb181e592bb10c4266fb265c33c74151f0a86`
- Freshness date: 2026-09-30
- Drive destination: `Jarvis/task/to-do/jarvis-generic-mcp-plugin-runtime/`

## Repository facts that motivated this task

- `jarvis/runtime/mcp_catalog.py` already builds the canonical MCP catalog from real FastMCP introspection plus shared metadata.
- `jarvis/runtime/mcp_tool_meta.py` is the shared native-tool metadata source and already has an `external` category.
- `docs/mcp/tool-contract.md` currently states that catalog meta-tools such as `list_tools` / `get_tool` are **not** exposed to the model. This task intentionally changes that policy for an intent-aware discovery gateway.
- `jarvis/runtime/control_center_mcp_inspector.js` is a read-only MCP inspector backed by `/api/mcp/tools`; it is the UI foundation to extend rather than replace.
- `jarvis/runtime/drive_mcp.py` is a special stdio Google Drive MCP coded in Jarvis. It expects OAuth files in environment-configured paths and must already be authorized outside the UI. It is therefore a useful migration/compatibility case, not the target generic plugin architecture.
- Claude conversation sessions currently receive selected Jarvis-native MCP configs in `jarvis/runtime/claude_local.py`. Codex can observe MCP call events but its current command construction does not establish the same Jarvis MCP capability path. “All agents” therefore requires an explicit cross-runtime design, not an assumption.
- A predecessor handoff, `jarvis-mcp-semantic-batch-inspector`, already delivered the native catalog/inspector. Treat it and `docs/mcp/tool-contract.md` as canonical predecessor material.

## Locked product intent

1. **Generic remote MCP onboarding.** Add a remote MCP from URL; no per-provider connection code.
2. **Plugin lifecycle.** A plugin has distinct connection/auth state and enabled/disabled state. Disabling does not automatically delete credentials. Disconnecting/revoking removes usable authorization where possible while retaining the plugin definition unless explicitly removed.
3. **Auth is runtime-owned.** OAuth tokens, bearer tokens, API keys and custom auth headers never enter model context, tool descriptions, normal logs, or UI payloads.
4. **One canonical catalog.** Native and managed-external tools flow into the existing catalog/registry contract. Frontend copies of tool lists are forbidden.
5. **Stable namespacing.** External tools receive stable qualified identities scoped by plugin/provider so collisions such as multiple `search` tools are harmless.
6. **Intent-aware discovery.** `list_tools(intent)` may be called repeatedly in one reasoning chain. It returns:
   - full actionable descriptors/schemas for a small recommended set relevant to the stated intent;
   - compact descriptors for other accessible tools, bounded/paginated when required.
   Normal use must not require `get_tool()` for recommended tools.
7. **Dynamic discovery.** Jarvis may call `list_tools(intent)` again whenever a tool reveals another dependency, e.g. mail -> email address -> user id.
8. **Generic execution gateway.** Managed external MCP tools are invoked through a Jarvis-owned gateway so the model does not receive plugin credentials and every agent runtime does not maintain an independent OAuth implementation.
9. **Global V1 availability.** Enabled plugins are global Jarvis capabilities for normal conversational agents and delegated subagents. Per-board/per-agent plugin policy is explicitly out of scope for V1.
10. **Restricted profiles stay restricted.** Existing profiles intentionally configured without MCP/tool access must not silently inherit write-capable plugins. Any change to those safety boundaries requires an explicit product decision and contract update.
11. **Control Center UX.** Reuse the existing MCP button/surface. Add an external plugins management view with compact plugin cards, status, optional icon/fallback, enable toggle, Add Plugin flow, connect/reconnect/disconnect/remove, and existing tool inspection.
12. **First real target.** Validate the generic path against Circuit Toolbox: `https://circoetoolbox-server-production.up.railway.app/mcp`.
13. **Drive compatibility.** Audit the existing `jarvis-drive` special server and classify/migrate it deliberately. Do not delete a working path merely to make the architecture diagram prettier.

## Architecture guardrails

- Prefer remote Streamable HTTP for managed remote MCP servers; preserve compatibility with older transport forms only through explicit adapters where verified useful.
- OAuth discovery and browser authorization must live below the Brain. Use standards-compliant PKCE/state and issuer/resource binding. Provide static bearer/API-key/custom-header auth only as a fallback for non-standard servers.
- Store secrets through a dedicated credential-vault abstraction. Plugin configuration stores only an opaque credential reference.
- Do not forward auth headers across unexpected origin/issuer redirects. Add SSRF/local-network protections appropriate to a user-supplied remote endpoint, with an explicit localhost development exception if needed.
- External tool schemas/descriptions are untrusted remote data: bound sizes, validate protocol payloads, redact secrets, and isolate one bad plugin from the rest of Jarvis.
- Do not hard-code the Circuit Toolbox tool list. It is a conformance target, not a special provider.

## How the Project Manager starts

Open `slices/TODO.md`, then execute **Slice 00 — Project Manager** yourself. Do not dispatch implementation before Slice 00 reaches `READY`.

Slice 00 must first perform an independent blind audit of the current repository and active Jarvis task queue, then reconcile it with this handoff. In particular, check for drift from the inspected commit and for concurrent edits from `jarvis-board-session-context-runtime` around `mcp_tool_meta.py`, `mcp_catalog.py`, `settings_mcp.py`, `control_center.py`, and related docs.

## QA and Human validation doctrine

Every implemented Slice gets `qa-verification`. Code changes also get `code-review`. User-visible or runtime behavior also gets `runtime-validation`. Any Slice touching MCP tools, tool discovery, routing, prompts, agent/subagent runtime, or plugin execution also gets `agent-trace-analysis` with real trace evidence.

A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation is not a substitute for machine QA. Before any Human check, exhaust the reasonable automated/runtime checks and clear everything machines could have caught.

All coding Slices require `/caveman` and `/coding-guideline`. Frontend Slices additionally require `/impeccable` and a Claude Work Agent when the host supports that routing rule.

## Planning blocker carried into Slice 00

The current Workspace Task Type vocabulary is not available to the task creator. No Task Type is invented in this handoff. Slice 00 must resolve valid existing Task Types before dispatch or stop that Slice as required by the host.
