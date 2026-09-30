# Reconstructed design session

This is a faithful reconstruction of the planning conversation, not a verbatim transcript.

## Session vs Board

The user rejected using "session" as the persistent project/workspace concept. A Session is the human/Jarvis conversation episode: starting Jarvis or explicitly asking for a clean conversation starts a new Session. Sessions become immutable history after they end. One Session may visit several Boards, and the same Board may be visited across many Sessions.

A Board behaves more like a ChatGPT Project: it is the durable workspace/context boundary. It owns or references the state necessary to resume work, including projects, tasks, artifacts, decisions/context summary, scene/workspace state, and interaction mode. Switching Boards should unload the previous Board context from the active reasoning context and load the target Board context.

## Voice and Brain topology

The user explicitly rejected a global intermediary Jarvis Brain plus one Brain per Board. Jarvis Voice should connect directly to the Brain for the active Board. A deterministic Jarvis runtime may manage sessions, boards, routing, persistence, MCP, and notifications, but it must not be another reasoning Brain.

Only one Board is foreground at a time and only that Board has voice/speech authority. When the user switches away, the previous Board Brain may keep running if it still has tasks or agents in progress. It remains queryable by runtime mechanisms but cannot barge in or take the voice channel. Idle Boards may be suspended and rehydrated later.

## Notifications and absence

Background work may finish while the user is on another Board or absent between Sessions. Jarvis already has an alerts/notification system for task progress/completion. V1 should extend/reuse it, attach Board identity to events, and keep notifications globally visible from any Board. Information from a non-active Board should arrive as a Board-attributed notification rather than being injected into the active Board context. The user may navigate to that Board from the alert flow.

## Prototype scope

The user explicitly deferred the Galaxy map/minimap visual concept. V1 should add a simple Board management control in the existing top-right Control Center buttons: list/select Boards, create a Board, and perform minimal management. Jarvis must have equivalent MCP operations.

The Board must persist interaction mode (presentation, meeting, assistant/default, etc.) so returning to a Board restores the mode it was using.

## Session reset semantics

A new Session must provide the equivalent of starting a clean ChatGPT conversation without deleting the current Board state. The previous Session is not reopened or mutated. Background tasks are not cancelled. The active Board is retained, but its interactive Brain conversation for the new Session is fresh and hydrated from persistent Board state. When a Session revisits a Board, it should recover that Board's conversation binding for the same Session rather than merging unrelated Board histories.
