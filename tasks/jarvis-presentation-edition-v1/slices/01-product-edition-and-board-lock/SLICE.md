# Slice 01 — Product edition and Presentation Board lock

## Goal
Create a canonical `presentation` product edition/capability policy and enforce that only Presentation Boards are available in the distributed V1 at Core, protocol, MCP and UI-facing contract boundaries.

## Context
Today `BoardKind` supports `assistant`, `presentation`, `meeting`; `assistant` is the default in several creation paths and Meeting falls back to Assistant behavior. UI hiding alone is insufficient. Shared code must remain reusable for future editions.

## Canonical Concepts
- `BoardKind` / Board type: `docs/boards.md`, `jarvis/domain/workspace_board.py`.
- Derived interaction mode: `docs/interaction-mode.md`, `jarvis/core/board_service.py`.
- Workspace MCP Board tools: `jarvis/runtime/workspace_mcp.py`.
- Presentation product edition: new canonical contract owned by this Slice.

## Scope
### In Scope
- introduce one canonical product-edition/capability model;
- make installed/distributed default edition `presentation` without changing development/full behavior unless explicitly configured;
- allow only `presentation` Board creation/activation under Presentation Edition;
- default Board creation to `presentation` when product policy omits an explicit kind;
- make Assistant/Meeting unavailable with stable error/status semantics;
- define deterministic handling of stored legacy Assistant/Meeting Boards;
- update MCP schema/tool exposure so the model cannot request unavailable Board kinds;
- provide product availability data for UI use.

### Out of Scope
- do not delete Assistant/Meeting code;
- do not implement Meeting behavior;
- do not redesign the UI yet;
- do not change data-root location yet.

## Dependencies
Hard `depends_on`: `00-project-manager`.

## Implementation Steps
1. Blindly re-open current Board/type/mode contracts and find every creation/activation entrypoint.
2. Add product-edition domain/config contract with a single source of truth for available Board kinds/capabilities.
3. Wire Core Board service/domain admission to that contract; use stable typed refusals for unavailable kinds.
4. Ensure startup/session restore cannot silently activate a Board kind forbidden by the active edition. Define fallback: last available Presentation Board, otherwise onboarding/no-board state or explicitly created Presentation Board according to current session architecture.
5. Update Control Center relay/status payloads as needed so UI can display availability without duplicating rules.
6. Update `jarvis-workspace` MCP schemas/tool descriptions to remove impossible kind choices under Presentation Edition. Prefer no `board_kind` argument when only one value is valid.
7. Add negative tests at Core/API/MCP for `assistant` and `meeting` attempts.
8. Keep development/full edition regression tests proving existing multi-kind behavior remains intact outside Presentation Edition.
9. Document product-edition semantics and upgrade behavior for legacy Boards.

## Files Likely Touched
- new product-edition domain/config module(s);
- `jarvis/domain/workspace_board.py`;
- `jarvis/core/board_service.py`;
- Board/session protocol routes;
- `jarvis/runtime/workspace_mcp.py`;
- `jarvis/runtime/control_center_boards.js` or its data contract only;
- related tests and `docs/boards.md` / new product-edition doc.

## Architecture Constraints
- one policy source; no independent UI-only availability table;
- Board kind remains immutable after creation;
- interaction mode continues to derive from Board kind;
- stored unavailable Boards are preserved, not rewritten/deleted;
- keep full/dev edition behavior available for ongoing Jarvis development.

## Automated Validation
- unit tests for edition policy;
- Board creation/activation/restore tests in both full and Presentation editions;
- protocol tests for stable refusals;
- MCP list/schema/call tests proving unavailable kinds are not exposed/accepted;
- regression tests for existing Presentation behavior.

## Acceptance Criteria
- in Presentation Edition there is no supported Core/API/MCP path to create or activate Assistant/Meeting;
- a direct forged request still fails even if UI is bypassed;
- Presentation Board creation works with a product-appropriate default;
- legacy unavailable Boards remain intact and cannot become active through normal product flows;
- full/dev mode still supports the existing Board vocabulary.

## Documentation Updates
Raise product-edition semantics to Level 3 with dedicated contract, policy implementation and conformance tests.

## Handoff Notes
Coding Slice: require `/caveman` and `/coding-guideline`. Runtime behavior requires `qa-verification`, `code-review`, `runtime-validation`. If MCP tool exposure or agent routing changes, also run `agent-trace-analysis` with a real product-edition trace.
