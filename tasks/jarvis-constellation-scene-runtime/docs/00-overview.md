# 00 - Overview

## Goal
Build the first production-capable persistent 2D constellation display for JARVIS: runtime facts create a reliable execution skeleton, the main brain composes semantic visual meaning through MCP-style display tools, and the Control Center browser renders the persistent scene.

## Mental model
`Runtime facts -> SceneService/SceneStore <- brain display MCP <- user intent`, then `SceneService -> snapshot/patches -> Control Center renderer`.

## Locked V1 boundaries
- Core normalized work state remains execution truth; Scene is a visual projection.
- New tracked sub-agents appear immediately as stars without an LLM turn.
- Parent/child tasks create constellation links; failures/completion attach minimal runtime signals.
- Low-level file/Git/URL/API/tool actions do not automatically become stars.
- Main brain can enrich a task with grouped semantic artifacts (research, diffs/files, tests/API activity, Trello/roadmap changes, emails, generated docs, etc.).
- No dedicated display AI in V1.
- Scene persists across browser reload and Control Center restart.
- Completed work stays active until user disposition; hide and archive are distinct.
- Archive is user-only in V1 and absent from brain tools.
- Strict 2D with explicit stacking order/layers and intentional overlap.
- AutoResolver handles physical constraints only; it does not decide semantic relevance.
- Structured scene inspection is normal; screenshot is exceptional/on-demand.

## Non-goals
No React/Electron migration solely for this feature; no 3D/parallax/literal space decoration; no node-per-event explosion; no runtime-driven arbitrary semantic composition; no brain archive capability; no server-streamed animation frames.

## Repository compatibility
Design targets the current aiohttp Control Center and existing `AgentTaskTracker`, Core work snapshot/revision model, background trace/event infrastructure, and optional MCP dependency. Preserve the existing local-first architecture and legacy operational panels during rollout.
