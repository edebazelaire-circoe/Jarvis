# Jarvis Presentation Interaction Mode

## Project

- Project: Jarvis
- Repository: `edebazelaire-circoe/Jarvis`
- Source snapshot inspected during handoff creation: `main` at `ddcdb71e17d7be76236c7dd6ab070af90e8f7d65` on 2026-09-23.
- Local handoff: `tasks/jarvis-presentation-interaction-mode/`
- Drive destination: `Jarvis/task/to-do/jarvis-presentation-interaction-mode/`

## Goal

Add a product-level interaction mode framework, independent from the existing voice architecture choice, and implement the first materially different behavior: Presentation mode.

Presentation mode lets Jarvis continuously understand a live presentation, prepare useful information and delegate background work, while manifesting very little unless explicitly addressed. Visual commands should normally execute silently. Genuine questions may produce a useful spoken answer plus supporting visuals. Ambient contradictions should produce a discreet fact-check notification rather than an unsolicited spoken interruption.

## Locked user intent

- Voice architecture and interaction mode are different axes. Simple / Front Brain / Duplex keep their own architectural meaning and should expose the same product capabilities where possible.
- Add a visible Jarvis mode control in the left-side Control Center UI, analogous in interaction quality to the existing Bare Hands lifecycle selector.
- User-facing mode labels are `SIMPLE`, `PRESENTATION`, and `REUNION`.
- `SIMPLE` means the existing ordinary assistant behavior. It must remain the default and should not regress.
- `PRESENTATION` is implemented by this task.
- `REUNION` is future work. In this V1 it must be visible as a reserved/coming mode but must not invent meeting behavior.
- Presentation mode continuously listens and analyzes while the user presents.
- Ambient speech is context and evidence, not an action request.
- Jarvis may launch background sub-agents to research, fact-check, resolve documents, prepare data, or prepare display artifacts.
- Background work must never block an explicit command or question.
- Wake word and the existing manual wake key are explicit-address triggers, not a request to start ambient listening.
- In Presentation mode, a visual command such as "show me the yearly report" should normally display the result with no filler TTS.
- A genuine knowledge question may use speech when speech adds value, and may also show a chart/table/window.
- Presentation mode should be highly active internally but quiet externally: "work a lot, manifest little".
- Ambient contradictions should create a discreet audible cue plus a small floating warning/attention signal. The user may then ask Jarvis to explain.
- No unsolicited spoken interruption for fact checking in V1.
- Future per-user interruption preferences are explicitly out of scope.
- Maintain a bounded, session-scoped working set/cache for recent topics, facts, sources, prepared resources, and unresolved items. It is not long-term memory.
- Keep a fresh recent transcript tail separate from slower enriched context so deictic commands like "show me that" do not resolve against stale analysis.
- The explicit command lane has absolute priority over speculative work and may preempt/deprioritize it.

## Start here

The receiving agent is the Project Manager for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself before dispatching any implementation Slice.

Slice 00 must perform a blind audit of the current repository before reading the handoff documentation-level conclusions, reconcile any drift, and reach `READY` before implementation dispatch.

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

The current Workspace Task Type vocabulary is not exposed in this task-creation environment. Slice metadata therefore keeps `task_type: null`. Slice 00 must resolve valid existing Workspace Task Types before dispatch, or obtain an explicit project-level waiver; it must never invent Task Type labels.
