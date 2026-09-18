# Reconstructed grilling/design session

> **Status:** faithful reconstruction from the live 2026-09-16 conversation. This is not claimed to be a verbatim transcript. It preserves the product decisions and user corrections needed for implementation.

## Starting point

The goal is not a classical backend-driven dashboard. JARVIS must be able to use the screen as a first-class output modality: create/select/move/resize/anchor/hide/close/expand visual objects, show transcripts or web pages, and visually represent background work as a living 2D constellation.

The display surface should behave like an MCP/tool surface from the brain's perspective. The brain calls explicit display operations; it does not emit HTML and does not physically render pixels itself. A renderer/body applies those operations and may use an AutoResolver to keep the scene usable.

## Brain, runtime, and body responsibilities

A dedicated display AI was considered and rejected for V1. The main brain already coordinates the user's intent and background work, so it remains responsible for semantic display decisions and for interpreting voice requests such as “show me X”, “move that”, “hide everything unrelated to CASTOR”, or “expand this task”. The architecture should leave room for a dedicated display agent later without requiring it now.

The runtime is allowed to bypass the brain only for systematic execution facts that must remain reliable and cheap:

- a sub-agent/sub-process is created -> create its star immediately;
- the process topology changes -> create/update parent-child constellation links;
- a tracked process becomes blocked, fails, completes, is cancelled, or is interrupted -> update the node state;
- an execution error/attention/completion signal occurs -> attach a minimal runtime signal/message.

This bypass exists for speed, zero/low token cost, and resilience when the main brain is delayed or unhealthy. Runtime does not get general scene-composition authority.

The browser/body has physical/reflex authority only: pointer hover, drag/resize feedback, clipping/bounds, hit targets, layer rendering, and constrained AutoResolver corrections. It must not decide what is semantically important.

## Constellation model

A real sub-agent is always an execution node (“star”) from the moment it exists. Child sub-agents or other tracked subordinate processes can become linked stars, making the execution topology visually legible.

The user does **not** want every low-level action to become a star. Opening Git, reading a file, making each HTTP request, or running every tiny tool call does not automatically create a spatial object.

Instead, the main brain may enrich a task constellation with grouped semantic artifacts that help the user understand what happened. Examples discussed:

- one research/history artifact summarizing many visited URLs rather than one star per URL;
- one files/diff artifact summarizing a set of modified files;
- Trello/roadmap updates, emails sent, documents created, or API/test activity grouped in the most useful form;
- tests may be one artifact or several if they are genuinely distinct and useful.

Sub-agents should ideally emit useful progress/completion summaries so the main brain can create/update these artifacts without replaying raw traces.

## Why artifacts matter

Background work should remain inspectable after execution. Example: after a meeting, JARVIS may update the roadmap and Trello and send relevant emails. The current “task ran and then disappeared into history” experience is insufficient. The constellation should let the user return later, understand the result, inspect grouped artifacts, ask follow-up questions, and only then dismiss/archive it.

## Persistence and lifecycle correction

The scene is not a disposable browser state. Reloading or closing/reopening the browser must restore the same active constellation, including geometry, representation, visibility, links, stacking, and user constraints. The browser is only a rendering interpretation of persistent runtime state.

A completed task is **not** automatically removed. Completion and user acknowledgement/disposition are distinct.

- `running` / `blocked` / terminal statuses describe execution.
- `visible` / `hidden` describe whether an active scene object is rendered.
- `archived` means removed from the active scene and retained only as historical state/log/reference.
- completed-but-not-reviewed remains a first-class active-scene state.

The brain has no archive tool in V1. It may hide, collapse, move, group, or enrich; archive stays a user action. Right-click/user controls should include archive and, where the runtime genuinely supports them, stop/interrupt task actions.

## Color and visual grammar

The user rejected status-as-primary-color. Base color should primarily identify semantic type/category; execution state should use secondary cues such as halo, ring, pulse, badge, marker, or attached attention node. Example categories were discussed only illustratively: white for agents, green for documentation/artifacts, red for explicit errors/attention. The exact theme/palette remains configurable.

## Layered 2D scene

The constellation is strict 2D but not a single plane. Objects have explicit stacking order/layers (illustrative bands: 50, 100, 120, 150, 220, 300). Relations can sit behind nodes; capsules and windows can overlap intentionally; attention can sit above them.

The AutoResolver should still look for usable free space, but overlap is not globally forbidden. Hard constraints and user pins come first; explicit brain placement comes next; the resolver optimizes only where several valid placements exist.

The brain is allowed to specify concrete placement/size/order through the display tools. The resolver is a safety/composition aid, not a semantic replacement for the brain.

## Brain perception of the scene

Before deciding how to add/rearrange content, the brain needs access to the current scene. The primary mechanism is structured inspection: compact JSON/text of active objects, geometry, representation, layer/order, links, visibility, status, and user constraints. It should also be able to request details by object/query.

An on-demand screenshot tool is useful for exceptional visual checking/debugging (for example verifying an overlap) but should not be the normal control path because it is more expensive and less structured.

## Final V1 authority model

1. **Runtime:** guaranteed execution topology and minimal execution/error signals.
2. **Main brain:** semantic composition, artifact grouping, autonomous “this is useful to show”, and explicit user display commands through MCP-like tools.
3. **Scene service/body:** persistence, validation, transport, constrained spatial resolution, rendering, pointer reflexes.
4. **User:** final authority for archive; direct pointer/context-menu interactions mutate the same scene model as brain commands.
