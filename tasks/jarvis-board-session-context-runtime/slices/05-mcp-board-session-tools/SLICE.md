# Slice 05 - MCP Board and Session tools with catalog parity

## Goal
Expose high-level Board operations list/get/get-active/create/update/archive/switch plus get_current_session and start_new_session through jarvis-console. Update shared metadata/catalog and real FastMCP parity tests.

## Context
Jarvis is moving from an implicit single-workspace model to first-class persistent Boards while preserving existing voice, background work, alerts and interaction-mode behavior.

## Canonical Concepts
Board; Session; BoardConversationBinding; deterministic runtime; single speech authority; Board-attributed notifications; jarvis-console parity.

## Scope
### In Scope
Expose high-level Board operations list/get/get-active/create/update/archive/switch plus get_current_session and start_new_session through jarvis-console. Update shared metadata/catalog and real FastMCP parity tests.
### Out of Scope
Galaxy/minimap visualization; global intermediary reasoning Brain; all-Boards prompt fusion; unrelated runtime rewrites.

## Dependencies
04

## Implementation Steps
Audit current owner files first; implement at canonical boundaries; preserve migration/backward compatibility; add strict schemas/errors and parity/behavior tests.

## Files Likely Touched
settings_mcp.py, mcp_tool_meta.py, mcp_catalog.py, control_center.py, control_center.html / focused control_center_* JS module, tests. Final paths follow Slice 00 audit.

## Architecture Constraints
No global LLM Brain. No low-level model-controlled bind_voice/attach_brain/speech-authority tools. UI/MCP call the same high-level runtime operations.

## Automated Validation
Baseline qa-verification; code-review; runtime-validation for UI/behavior; agent-trace-analysis for MCP/runtime changes.

## Acceptance Criteria
Jarvis can perform every V1 Board/session action exposed by the Control Center, and real FastMCP list_tools matches the shared catalog.

## Documentation Updates
Update MCP tool contract and Control Center docs/help as appropriate.

## Handoff Notes
Coding work loads /caveman and /coding-guideline. Frontend work additionally loads /impeccable and uses Claude routing when supported.

## Slice 00 contract (authoritative, overrides the generic sections above)

Architecture: `docs/06-resolved-architecture.md`. Readiness: `slices/00-project-manager/READINESS.md` (inherited red tests = not yours).

- Depends on 04b (not 04). Tools in `jarvis/runtime/settings_mcp.py` (`jarvis-console`): `board_list`, `board_get`, `board_get_active`, `board_create`, `board_update`, `board_archive`, `board_switch`, `session_current`, `session_new`. They call the same CC `/api/boards*` / `/api/sessions*` routes as the UI. `board_switch` / `session_new` send `origin=brain` and return `{status:"scheduled"}` when deferred (section D of 06).
- `mcp_tool_meta.py` CONSOLE entries in registration order; structured results in `mcp_results.py` if `docs/mcp/tool-contract.md` §10.2 requires; `_SERVER_INSTRUCTIONS` updated; `docs/mcp/tool-contract.md` + `docs/boards.md` updated.
- Tests: `test_settings_mcp.py`, `test_mcp_catalog.py` (real FastMCP list_tools == catalog), behavior tests against a fake CC; agent-trace-analysis with a real brain turn that lists/creates/switches Boards.
