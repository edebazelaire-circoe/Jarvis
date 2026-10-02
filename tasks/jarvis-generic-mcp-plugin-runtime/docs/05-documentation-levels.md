# Documentation levels

## Current state at handoff creation

| Concept | Current level | Evidence | Required level |
| --- | ---: | --- | ---: |
| Native MCP tool descriptor/catalog | 3 | `docs/mcp/tool-contract.md`, `mcp_catalog.py`, `mcp_tool_meta.py`, parity tests | 3 |
| MCP Control Center inspector | 3 | existing API + `control_center_mcp_inspector.js` + tests | 3 |
| Managed external MCP plugin lifecycle | 0-1 | only `external` category / operator-managed Drive exists | 3 |
| Generic remote MCP auth/connection manager | 0 | no canonical contract found | 3 |
| Credential-vault contract for MCP plugins | 0 | no plugin-specific abstraction found | 3 |
| Model-facing `list_tools(intent)` | 0 by design | current contract explicitly forbids model catalog meta-tools | 3 |
| Managed external tool invocation gateway | 0 | no generic external dispatcher found | 3 |
| Cross-agent/subagent plugin propagation | 0-1 | Claude native MCP wiring exists; Codex path is asymmetric | 3 |
| Drive as generic plugin | 0 | current `jarvis-drive` is special stdio + external OAuth-file setup | 2-3 after migration decision |

## Required canonical documentation

Slice 01 must update or extend the MCP docs so the repository clearly owns:

- plugin identity/lifecycle and states;
- auth strategies and secret boundaries;
- global catalog descriptor fields for dynamic external tools;
- `list_tools(intent)` mixed-detail response and output-budget rules;
- generic external `call_tool` semantics;
- agent/subagent capability inheritance and restricted-profile exception;
- Control Center plugin UX/API contract;
- Drive legacy/migration status.

Prefer extending `docs/mcp/tool-contract.md` plus one focused plugin/runtime document over scattering rules across comments. Exact paths are finalized by Slice 00 after the blind audit.
