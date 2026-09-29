# Slice 04 - Board Brain lifecycle, switching, and Voice binding

## Goal
Implement foreground/background_running/suspended states, atomic switch_board, speech-authority revoke/grant, target context hydration and mode apply, outgoing background work continuation, safe suspend/resume, tracing and rollback. Voice binds directly to the active Board Brain.

## Context
Jarvis is moving from an implicit single-workspace model to first-class persistent Boards while preserving existing voice, background work, alerts and interaction-mode behavior.

## Canonical Concepts
Board; Session; BoardConversationBinding; deterministic runtime; single speech authority; Board-attributed notifications; jarvis-console parity.

## Scope
### In Scope
Implement foreground/background_running/suspended states, atomic switch_board, speech-authority revoke/grant, target context hydration and mode apply, outgoing background work continuation, safe suspend/resume, tracing and rollback. Voice binds directly to the active Board Brain.
### Out of Scope
Galaxy/minimap visualization; global intermediary reasoning Brain; all-Boards prompt fusion; unrelated runtime rewrites.

## Dependencies
02, 03

## Implementation Steps
Audit current owner files first; implement at canonical boundaries; preserve migration/backward compatibility; add stable errors/reasons, tracing, and automated tests.

## Files Likely Touched
Resolve exact files in Slice 00 freshness audit. Expected areas: Core/Brain ownership, Live/Voice session, control_center.py, runtime managers, tests.

## Architecture Constraints
No global LLM Brain. No dual speech authority. No task cancellation merely from Board/session changes. UI/MCP never bypass runtime invariants.

## Automated Validation
Baseline qa-verification; code-review for code; runtime-validation for behavior; agent-trace-analysis for agent/tool/MCP/runtime changes.

## Acceptance Criteria
The behavior matches the Goal, preserves locked invariants, passes machine QA, and introduces no regression caused by this Slice.

## Documentation Updates
Update canonical lifecycle/runtime docs affected by the Slice.

## Handoff Notes
Coding work loads /caveman and /coding-guideline. Slice 00 performs a targeted freshness check before dispatch.
