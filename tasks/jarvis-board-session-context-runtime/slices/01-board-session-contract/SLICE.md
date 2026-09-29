# Slice 01 - Canonical Board and Session contract

## Goal
Define pure domain contracts for Board, Session, BoardConversationBinding, lifecycle states, stable IDs/errors, closed-Session immutability, one speech-authority Board, and default-Board migration semantics. No persistence/UI/MCP.

## Context
Jarvis is moving from an implicit single-workspace model to first-class persistent Boards while preserving existing voice, background work, alerts and interaction-mode behavior.

## Canonical Concepts
Board; Session; BoardConversationBinding; deterministic runtime; single speech authority; Board-attributed notifications; jarvis-console parity.

## Scope
### In Scope
Define pure domain contracts for Board, Session, BoardConversationBinding, lifecycle states, stable IDs/errors, closed-Session immutability, one speech-authority Board, and default-Board migration semantics. No persistence/UI/MCP.
### Out of Scope
Galaxy/minimap visualization; global intermediary reasoning Brain; all-Boards prompt fusion; unrelated runtime rewrites.

## Dependencies
00

## Implementation Steps
Audit current owner files first; implement at canonical boundaries; preserve migration/backward compatibility; add stable errors/reasons and automated tests before exposing behavior.

## Files Likely Touched
Resolve exact files in Slice 00 freshness audit. Expected areas: domain contracts, persistence/runtime managers, Control Center, Core/Voice ownership, background events, MCP catalog/metadata, tests.

## Architecture Constraints
No global LLM Brain. No dual speech authority. No task cancellation merely from Board/session changes. UI/MCP never bypass runtime invariants.

## Automated Validation
Baseline qa-verification; code-review for code; runtime-validation for behavior; agent-trace-analysis for agent/tool/MCP/runtime changes.

## Acceptance Criteria
The behavior matches the Goal, preserves locked invariants, passes machine QA, and introduces no regression caused by this Slice.

## Documentation Updates
Update canonical Board/Session/MCP/Control Center docs affected by the Slice.

## Handoff Notes
Coding work loads /caveman and /coding-guideline. Slice 00 performs a targeted freshness check before dispatch.

## Slice 00 contract (authoritative, overrides the generic sections above)

Architecture: `docs/06-resolved-architecture.md`. Readiness: `slices/00-project-manager/READINESS.md` (inherited red tests = not yours).

- Create `jarvis/domain/workspace_board.py`: frozen dataclasses `Board`, `JarvisSession`, `BoardConversationBinding`; enums `BoardStatus` (active/archived), `SessionStatus` (open/closed), `BrainLifecycle` (foreground/background_running/suspended); stable error type with codes (`board_not_found`, `board_archived`, `board_is_active`, `session_closed`, `binding_conflict`, `invalid_title`, ...); pure transition helpers (close session -> immutable; `visit(board)`; exactly one foreground binding per session; default Board id `"default"`; id prefixes `jsess_`, `board_`).
- Create `jarvis/ports/workspace_board.py`: `BoardRepository` protocol and `BoardBrainHost` protocol (`activate(binding) -> agent_session_id`, `demote(binding)`), no implementation.
- Create `docs/boards.md` (canonical doc: glossary Board vs Barehands board vs Session vs Core conversation vs CLI session; invariants; lifecycle). Add the ownership rows to `docs/ARCHITECTURE.md`.
- Tests: `tests/unit/test_workspace_board_contract.py` (immutability, one foreground, A/B/A visit semantics, stable error codes, serialization round-trip).
- No persistence, routes, UI, MCP.
