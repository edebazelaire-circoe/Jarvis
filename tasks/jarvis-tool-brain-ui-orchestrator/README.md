# Jarvis Tool Brain — UI Decision Orchestrator

## Project

- Project: **Jarvis**
- Canonical handoff slug: `jarvis-tool-brain-ui-orchestrator`
- Local handoff: `tasks/jarvis-tool-brain-ui-orchestrator/`
- Drive destination: `Jarvis/task/to-do/jarvis-tool-brain-ui-orchestrator/`
- Repository expected by durable Jarvis task material: `edebazelaire-circoe/Jarvis`

## Goal

Introduce a dedicated **Tool Brain** that owns Jarvis UI-tool decisions and timing so the main Jarvis Brain can focus on reasoning, context loading, speech, and non-UI tools.

The target mental model is:

```text
User transcript + Jarvis intent + Jarvis speech progress + UI/world state
                              |
                              v
                     Perception / snapshot
                              |
                              v
                         TOOL BRAIN
                    decide + schedule UI actions
                              |
                              v
                     Action queue / validator
                              |
                              v
                 Scene / Board / Browser UI tools
```

Jarvis knows that the Tool Brain exists and knows the UI capability surface, but in the normal path it does not execute UI tools itself. It publishes structured UI-relevant intentions and speech progress. The Tool Brain interprets those signals together with the current user-visible state and autonomously decides which UI tools to call, when to call them, and which queued actions to cancel or replace.

## Locked user intent

- V1 delegates **UI tools only** to the Tool Brain. Jarvis retains non-UI tools such as research, analysis, database access, and other content-producing operations.
- Jarvis must be explicitly aware of the Tool Brain and of the UI capabilities available to the Jarvis system, so it never claims an action is unavailable merely because another brain executes it.
- Jarvis declares **intent**, not low-level UI commands. Tool Brain remains the decision owner for display actions.
- Tool Brain receives a time-aligned stream containing user transcript, what Jarvis has already said, what Jarvis is saying now, and future response chunks when the response is already generated.
- Tool Brain uses **hybrid wakeups**: immediate event-driven decisions for important events plus a short periodic tick as a safety net.
- Tool Brain owns a queue of UI tool calls and may execute now, delay, schedule against speech/events, reprioritize, replace, or cancel queued actions.
- Runtime state is authoritative. An action whose preconditions are stale or invalid is rejected cleanly; fresh state is produced and Tool Brain is woken immediately to replan.
- Tool Brain has near-total autonomy over reversible UI actions. Destructive or irreversible operations receive mechanical guardrails.
- Every manipulable UI/world object has a stable runtime ID for as long as that object exists.
- Tool parameters should be **choice-constrained from current state wherever possible**. The model chooses from valid IDs/enums supplied by the runtime instead of inventing identifiers or arbitrary parameter tokens.
- Tool descriptions must expose meaningful parameter descriptions, dynamic valid choices, human-readable labels, current state, compatibility constraints, and enough metadata to make a good choice.
- Tool Brain receives a compact, relevant perception snapshot by default and can call targeted read/inspection tools for deeper information about a specific ID.
- The perception snapshot represents what the user is actually seeing: active Board, visible scene objects, stars, points, capsules, windows, agent/task/process state, currently open browser/window surfaces, and other relevant user-visible state.
- Board switching is a Tool Brain UI capability.
- Browser-surface operations such as opening/focusing a URL, opening a page/window, scrolling, going back/forward, and zooming may be delegated as **presentation/navigation actions**. Research and information-seeking remain Jarvis responsibilities in V1.
- The existing live transcription/observability view must be **extended, not recreated**, to show Tool Brain decisions/tool calls/queue activity on the shared timeline.
- Specific Tool Brain model choice, fine-tuning, and training are intentionally not locked in this task. The architecture must permit swapping or training a faster specialized decision model later.

## Durable project evidence used

The task creator could inspect the Jarvis Drive task history but could not access the live GitHub repository through the connector. The following durable handoffs are directly relevant and must be reconciled in Slice 00:

- `Jarvis/task/to-do/jarvis-scene-window-prefab-foundation/` — defines scene ownership, reusable window/prefab direction, stable prefab/instance identity and a declarative scene contract.
- `Jarvis/task/done/jarvis-mcp-semantic-batch-inspector/` — establishes semantic MCP operations, MCP catalog/introspection metadata, selection semantics, and the principle that model-facing tool calls should be semantically dense.
- `Jarvis/task/done/jarvis-conversation-observability-timeline/` — establishes the existing canonical conversation event log and live multi-lane transcript/debug timeline that this task must extend.
- `Jarvis/task/done/jarvis-board-session-context-runtime/` — establishes Board/Session runtime concepts and UI/MCP parity for Board operations.
- `Jarvis/task/to-do/jarvis-session-context-recording-runtime/` — provides current Session/Context/capture contracts and additional evidence about canonical activity events and Brain catch-up patterns.

## Cross-handoff coordination

This task must not create second copies of contracts that other Jarvis tasks already own.

- Reuse the existing scene/runtime ownership model; coordinate with the pending scene-window-prefab foundation when it changes scene APIs.
- Reuse existing MCP catalog/introspection mechanisms instead of inventing a separate Tool Brain-only tool registry.
- Reuse the canonical conversation event/timeline system for Tool Brain observability.
- Reuse Board runtime identity and switching semantics instead of redefining Board/Session.

## Start here

The receiving agent is the Project Manager for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself. Do not dispatch implementation work until Slice 00 reaches `READY`.

Slice 00 must perform an independent blind audit of the current repository before relying on this handoff's documentation-level conclusions. Repository reality wins over planning assumptions.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline`. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Planning blocker

The current Workspace Task Type vocabulary was not exposed reliably in the task-creation environment. Slice metadata therefore uses `task_type: null`. Slice 00 must resolve every implementation Slice to an existing valid Workspace Task Type before dispatch; never invent Task Type labels.
