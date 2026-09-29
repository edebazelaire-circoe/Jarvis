# Slice 06 - Control Center Boards selector and manager

## Goal
Add a simple top-right Boards control using existing UI conventions: active Board, list/switch/create, minimal rename/archive, pending/error states. No Galaxy/minimap.

## Context
Jarvis is moving from an implicit single-workspace model to first-class persistent Boards while preserving existing voice, background work, alerts and interaction-mode behavior.

## Canonical Concepts
Board; Session; BoardConversationBinding; deterministic runtime; single speech authority; Board-attributed notifications; jarvis-console parity.

## Scope
### In Scope
Add a simple top-right Boards control using existing UI conventions: active Board, list/switch/create, minimal rename/archive, pending/error states. No Galaxy/minimap.
### Out of Scope
Galaxy/minimap visualization; global intermediary reasoning Brain; all-Boards prompt fusion; unrelated runtime rewrites.

## Dependencies
04, 05

## Implementation Steps
Audit current owner files first; implement at canonical boundaries; preserve migration/backward compatibility; add strict schemas/errors and parity/behavior tests.

## Files Likely Touched
settings_mcp.py, mcp_tool_meta.py, mcp_catalog.py, control_center.py, control_center.html / focused control_center_* JS module, tests. Final paths follow Slice 00 audit.

## Architecture Constraints
No global LLM Brain. No low-level model-controlled bind_voice/attach_brain/speech-authority tools. UI/MCP call the same high-level runtime operations.

## Automated Validation
Baseline qa-verification; code-review; runtime-validation for UI/behavior; agent-trace-analysis for MCP/runtime changes.

## Acceptance Criteria
A human can create and switch Boards, identify the active Board, and recover cleanly from failed/rejected operations.

## Documentation Updates
Update MCP tool contract and Control Center docs/help as appropriate.

## Handoff Notes
Coding work loads /caveman and /coding-guideline. Frontend work additionally loads /impeccable and uses Claude routing when supported.
