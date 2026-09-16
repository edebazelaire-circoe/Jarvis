# Jarvis Conversation Observability + Live Timeline

## Project

- Project: Jarvis
- Repository: `edebazelaire-circoe/Jarvis`
- Source snapshot inspected during handoff creation: `main` at `c33207281a5b6a10a6630b8914f19855ea096473` on 2026-09-12.
- Destination: `Jarvis/task/to-do/jarvis-conversation-observability-timeline/`
- This handoff is based on the repository after the routing/self-development work landed and after the latest voice-surface change observed on 2026-09-12.

## Goal

Make conversation history a backend-native, crash-resilient, searchable event record and expose it as a live multi-lane transcript/debug timeline with trace-linked Brain, Mouth and sub-agent activity.

## Locked user intent

- Transcripts are produced from backend/runtime events, never by asking an LLM to rewrite the conversation.
- The canonical conversation record must survive crashes and remain traceable/searchable.
- The transcript view is live and based on a shared time axis, not a post-hoc text summary.
- The primary timeline shows User, Jarvis Mouth/Reflex, Brain, and sub-agent activity with distinct visual lanes.
- User content is shown on the left; Jarvis/Mouth is light blue, Brain is orange, and sub-agents are red duration blocks.
- Brain/Mouth/sub-agent entries link to diagnostic trace evidence; user entries do not need a diagnostic drill-down.
- A readable text transcript and machine-readable export are projections of the canonical event record, not separate truths.

## Start here

The receiving agent is the Project Manager for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself before dispatching any implementation Slice. Slice 00 must perform a blind live-repository audit and reconcile this handoff with the latest code before implementation.

## Cross-handoff coordination

This task should establish its event contract before the voice-arbitration handoff integrates new cancellation/ownership events. The two tasks may proceed in parallel only if their event contracts are explicitly reconciled by the Project Managers.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline` before implementation. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed to this task-creation environment. Implementation Slice metadata therefore uses `task_type: null`. Slice 00 must resolve each Slice to a valid existing Workspace Task Type before dispatch.
