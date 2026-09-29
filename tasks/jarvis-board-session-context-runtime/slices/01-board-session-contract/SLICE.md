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
