# Slice 06 — Dedicated jarvis-workspace MCP server

## Goal
Create the dedicated `jarvis-workspace` native MCP server, migrate existing Board/Session tools out of `jarvis-console`, and expose the new memory/artifact/history capabilities with catalog parity and real-agent proof.

## Context
Current main registers nine Board/Session tools on `jarvis-console`. The user accepted a dedicated workspace server so settings and workspace management stop competing in one surface.

## Canonical Concepts
`docs/mcp/tool-contract.md`, shared MCP metadata, native server launch configuration, Board/Session APIs.

## Scope
### In Scope
- New `jarvis-workspace` server and launch target/config.
- Preserve existing Board semantic intents/names where sensible.
- Add Session history, Board memory, artifact/provenance and relationship inspection tools.
- Strict schemas, output bounds, read/write/destructive annotations, idempotence/atomicity metadata.
- MCP catalog category/tab and inspector support from shared metadata.
- Context-budget measurement/gate.
- Migration/removal of Board tools from `jarvis-console` without duplicate advertised aliases.
- Advertise workspace tools to main Brain.
- Ensure intended delegated Claude inspection agents can access the server/tools; prove in real trace.

### Out of Scope
- Raw SQL.
- Raw unrestricted filesystem MCP.
- Automatic agent delegation policy changes unrelated to making tools reachable.

## Dependencies
Slices 04-05.

## Implementation Steps
1. Audit current server/config generation and delegated-agent tool inheritance.
2. Design compact tool surface around user intents.
3. Register metadata as the single source of catalog truth.
4. Implement wrappers over shared APIs, never separate business logic.
5. Move existing Board/Session tools from console.
6. Add unit/parity/context-budget tests.
7. Run real Brain and delegated-agent traces.

## Files Likely Touched
`jarvis/runtime/settings_mcp.py`, `console_boards.py` or successors, new workspace MCP module, `mcp_tool_meta.py`, `claude_local.py`/agent launch configuration, catalog tests/docs.

## Architecture Constraints
- UI and MCP share backend semantics.
- No duplicate model-visible Board tools across native servers after migration.
- Historical read tools never call switch.
- Tool output is bounded and model-friendly.

## Automated Validation
`qa-verification` + `code-review` + `runtime-validation` + `agent-trace-analysis` with real main-Brain and delegated-agent evidence. Catalog parity and context-budget gates are mandatory.

## Acceptance Criteria
Jarvis can list/create/update/switch Boards, inspect Sessions, read/search/mutate Board memory, and inspect artifact provenance through `jarvis-workspace`; a sub-agent can inspect an old Board without changing foreground state; `jarvis-console` no longer duplicates these intents.

## Documentation Updates
Update `docs/mcp/tool-contract.md`, operations docs and native-server inventory.

## Handoff Notes
Do not add a generic `execute_workspace_command` escape hatch merely to reduce tool count; preserve typed semantic operations.
