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

## Slice 00 contract (authoritative, overrides the generic sections above)

Architecture: `docs/06-resolved-architecture.md`. Readiness: `slices/00-project-manager/READINESS.md` (inherited red tests = not yours).

**This folder is Slice 04a - Board agent pool (Control Center).** The Core switch / speech authority / Voice rebind moved to `slices/04b-switch-speech-authority/`. HV-BOARD-VOICE-001 moved to 04b.

- Create `jarvis/runtime/board_brains.py` `BoardBrainPool` (section B of 06): per-binding agent, foreground/background_running/suspended, 60 s idle auto-suspend after last sub-agent, cap 3 live CLIs (never cancels work), `--resume` from stored session id, Codex handled per section B (never `restart()`).
- `control_center.py`: `agent` property -> pool foreground; `_switch_agent` -> foreground only; per-entry wiring of `TrackerWorkObserver`, `work_ingress.on_resync` (must support several agents), `conversation_events`; `agent_ask` routes by conversation id (409 `brain_not_foreground`); notices watermark on promotion; new internal `POST /api/agent/bindings/activate` (called by Core); `/api/agent/restart new_conversation` delegates to Core `start_new_session` when available.
- `runtime/journal.py`: optional bound context; each pool agent journals `{board_id, jarvis_session_id}`; background agents' notices journaled `spoken:false`.
- Tests with a stubbed CLI: demoted agent keeps running sub-agents; suspend + resume uses `--resume`; cap suspends only idle; no notice replay after promotion; ask routing; existing agent panel / restart / notices tests stay green (`test_control_center_*`, `test_agent_tasks.py`, `test_claude_local*`, `test_codex*`).
