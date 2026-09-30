# Jarvis Board + Session Context Runtime

## Project

- Project: Jarvis
- Repository: `edebazelaire-circoe/Jarvis`
- Source snapshot inspected for planning: `main` at `202333db5c5dea31258125a0ef296314d9b82b34` (2026-09-28).
- Drive destination: `Jarvis/task/to-do/jarvis-board-session-context-runtime/`.

## Goal

Introduce a prototype Board runtime that separates persistent workspace context from human/Jarvis sessions. A Board is the durable workspace and context boundary. A Session is the current human/Jarvis conversation episode and may traverse multiple Boards. Voice connects directly to the Brain for the active Board; there is no global reasoning Brain between Voice and Board Brains.

The prototype must let both the human UI and Jarvis through MCP list, create, inspect, switch, rename/update, and archive Boards, and start a new Session. Existing task/background work may continue on a non-active Board, but only the active Board has voice/speech authority. Existing alerts become global across Boards and identify their Board of origin. Interaction mode is persisted per Board.

## Locked scope for V1

- Add a top-right Control Center Boards control with board selection and new-board creation.
- Add deterministic runtime ownership for current Session, active Board, Board persistence, Brain lifecycle, and Voice-to-Brain binding.
- Persist enough Board state to restore a workspace without replaying old conversations: Board metadata, context snapshot/reference set, scene/workspace state or references, current interaction mode, task/project/artifact references, and Brain conversation metadata needed for rehydration.
- Allow one Session to traverse Boards. Returning to a Board within the same Session restores that Board's conversation binding for that Session.
- Starting a new Session closes the prior Session immutably, keeps the active Board and all Board state unchanged, and starts a fresh interactive Brain conversation hydrated from the active Board state. Background work is not cancelled.
- Switching Boards atomically revokes voice authority from the old Board, preserves/continues background work when required, loads/resumes the target Board Brain, and binds Voice directly to it.
- Reuse the existing alert/background-event surface for cross-Board completion/failure notifications. Non-active Board information reaches the user as Board-attributed notifications rather than contaminating active Board context.
- Expose Board and Session operations through `jarvis-console` MCP with Control Center parity and catalog metadata/tests.
- Migrate existing single-workspace state into one default Board without losing current state.

## Explicit non-goals

- Galaxy map, minimap, zoomed-out cosmos navigation, or any other multi-galaxy visual treatment.
- A global LLM/Brain that sits between Voice and Board Brains.
- Loading every Board context into the active Brain.
- Full semantic Brain-to-Brain querying across Boards. V1 may expose deterministic read-only Board metadata/state through MCP, but deep cross-Board reasoning is deferred.
- Replacing the existing task/agent runtime wholesale.
- Cancelling background tasks merely because the user switches Board or starts a new Session.
- Rebuilding the alerts UI from scratch.

## Start here

The receiving agent is the Project Manager for this handoff. Open `slices/TODO.md`, execute Slice `00-project-manager` itself, and do not dispatch implementation below `READY`. Slice 00 performs a blind live-repository audit before relying on this handoff's architecture conclusions.

## Repository evidence already observed

- `jarvis/runtime/control_center.py` already exposes agent restart behavior and the existing `new_conversation` concept.
- `idees/2026-09-28-nouvelle-session-a-la-voix.md` records the missing voice/MCP path for starting a fresh conversation and explicitly notes that the meaning of session still needed definition; this task resolves that ambiguity.
- `jarvis/runtime/live_frontend_session.py` already separates a Live frontend session ID from Core and holds a `conversation_id`.
- `jarvis/runtime/background_events.py` already provides a `BackgroundEventLedger` and classifies background completion/failure/attention events.
- `jarvis/runtime/interaction_mode_settings.py` currently persists interaction mode globally while Core owns the effective live mode; V1 makes the persisted selection Board-scoped while preserving Core as effective owner.
- `jarvis/runtime/settings_mcp.py` defines `jarvis-console` and states the UI/MCP parity rule: anything the user can do in the Control Center should be possible for Jarvis.
- `jarvis/runtime/mcp_catalog.py` and `mcp_tool_meta.py` are the canonical MCP introspection/metadata path and must be updated rather than bypassed.
- `jarvis/runtime/control_center.html` already has the top bar and notification layering; extend the existing UI conventions rather than inventing a second shell.

## Required implementation skills

Every coding Slice must load `/caveman` and `/coding-guideline` before editing code. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, MCP, or agent runtime changes add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed reliably to this task-creation environment. Recent Jarvis handoffs still use `task_type: null` with resolution at Slice 00. Slice 00 must resolve every implementation Slice to an existing valid Workspace Task Type before dispatch; do not invent or default a type.
