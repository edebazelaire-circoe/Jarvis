# Decision log

## 2026-09-30 — Generic plugin runtime, not provider integrations

The user chose one generic MCP plugin mechanism. Circuit Toolbox and Drive are validation/migration targets, not bespoke implementations.

## 2026-09-30 — Extend the existing MCP catalog

Repository evidence shows `mcp_catalog.py`, `mcp_tool_meta.py`, `/api/mcp/tools`, and the MCP inspector are already canonical. The new plugin system must extend/refactor this source of truth instead of introducing a parallel external catalog.

## 2026-09-30 — Change the old “no list_tools for models” policy

`docs/mcp/tool-contract.md` currently forbids model-facing catalog meta-tools. The user now explicitly wants `list_tools(intent)`. The contract must therefore be revised deliberately and parity/context-budget tests updated.

## 2026-09-30 — `list_tools(intent)` returns mixed detail levels

Recommended tools selected for the current intent contain full actionable schemas. Other accessible tools are returned as compact entries, with strict output budgets/pagination as needed. Recommended tools should not need an immediate `get_tool()` round-trip.

## 2026-09-30 — Repeated discovery is normal

Jarvis may call `list_tools(intent)` multiple times in one task as new prerequisites emerge. The tool/runtime should be designed and prompted for this iterative pattern.

## 2026-09-30 — Centralize execution and credentials

Managed external MCP credentials and live auth/session state belong to Jarvis's runtime. Brain and subagents receive stable discovery/execution capabilities, not raw plugin credentials.

## 2026-09-30 — Plugin connection and enablement are separate

- connected/authenticated: Jarvis has usable authorization/session state;
- enabled: the plugin's tools are available for discovery/execution.

Disabling should not force re-authentication. Disconnect/revoke and removal are distinct operations.

## 2026-09-30 — Global V1 plugin availability

Enabled plugins are global capabilities for normal Jarvis agents/subagents. Per-board/per-agent scopes are deferred. Existing intentionally restricted execution profiles must keep their restrictions unless explicitly redesigned.

## 2026-09-30 — One MCP Control Center

Reuse the existing MCP button/inspector. Add managed-plugin cards and flows there. Do not create a second plugin/settings surface.

## 2026-09-30 — Legacy Drive is a migration case

Current `jarvis-drive` uses a Jarvis-specific stdio server and pre-created OAuth files. Preserve it until a generic managed alternative is proven and a migration/deprecation plan is safe.
