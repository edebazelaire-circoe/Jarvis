# Jarvis Presentation Interaction Mode

## Project

- Project: **Jarvis**
- Canonical handoff slug: `jarvis-presentation-interaction-mode`
- Local handoff: `tasks/jarvis-presentation-interaction-mode/`
- Drive destination: `Jarvis/task/to-do/jarvis-presentation-interaction-mode/`
- Repository expected by durable Jarvis task material: `edebazelaire-circoe/Jarvis`

## Goal

Implement **Presentation** as a first-class Jarvis interaction mode for situations where the user is actively presenting to other people.

Presentation mode must make Jarvis **highly active internally and deliberately quiet externally**. While the user presents, Jarvis continuously follows the live ambient transcript, maintains a fresh understanding of the current topic, prepares likely-needed information and visual material, and may delegate non-blocking background research or fact-checking. It must not treat ordinary room speech as commands and must not constantly interrupt the presentation.

When the user explicitly addresses Jarvis, the mode changes behavior immediately:

- visual commands should normally be executed silently;
- genuine questions may receive a concise spoken answer when speech adds value, with supporting visuals when useful;
- explicit addressed work always takes priority over speculative/background preparation;
- a clearly relevant ambient contradiction may produce a discreet attention signal, but never an unsolicited spoken fact-check interruption in V1.

The mental model is:

```text
ambient speech ---------------------> fresh transcript tail
                                         |
                                         v
                                   presentation context
                                         |
                         +---------------+----------------+
                         |                                |
                         v                                v
                 working set / cache             background preparation
                         |                                |
                         +---------------+----------------+
                                         |
user explicitly addresses Jarvis ------> presentation policy / Brain
                                         |
                                         v
                               structured response intent
                                         |
                             +-----------+-----------+
                             |                       |
                             v                       v
                         speech policy          Tool Brain
                                                     |
                                                     v
                                           Scene / Prefab runtime
```

## What this task is — and is not

Presentation mode is an **interaction-policy and context-orchestration layer**. It is not a second voice architecture, not a recording system, not a new scene renderer, and not a second UI tool executor.

It consumes existing Jarvis subsystems and pending foundations:

- the ambient audio/transcription lane provides live room context;
- Session/Context runtime owns durable session continuity and explicit recording/capture;
- the Tool Brain owns low-level UI-tool choice and timing;
- the Scene Window & Prefab Foundation owns reusable visual objects/windows and their runtime lifecycle;
- the conversation event/timeline system owns canonical observability.

This task must integrate those systems rather than fork them.

## Locked product behavior

- `SIMPLE` remains the ordinary/default interaction mode and must not regress.
- `PRESENTATION` is the behavior implemented here.
- `REUNION` may remain visible/reserved if the current product already exposes it, but meeting-specific behavior is explicitly out of scope.
- Presentation mode continuously listens/analyzes through the existing ambient lane while active.
- Ambient room speech is **context/evidence**, not an addressed user turn and not authority to execute actions.
- Wake word and the existing explicit/manual address mechanism remain explicit-address triggers. They do not mean "start ambient listening".
- Jarvis should maintain two freshness tiers: a very fresh transcript tail for deictic requests such as "montre-moi ça", and a slower enriched working set for topics, claims, sources, prepared resources and unresolved items.
- Jarvis may launch background sub-agents/work for research, fact-checking, document resolution, data preparation or visual preparation.
- Background work must never block or delay an explicit addressed command/question. Explicit work may preempt, cancel or deprioritize speculative work.
- Visual commands such as "montre-moi le rapport annuel" should normally manifest the visual result without filler TTS.
- Genuine knowledge questions may use speech when useful and may also request supporting visual material.
- Ambient contradictions may surface as a discreet audible cue plus a small visual attention/fact-check signal. No unsolicited spoken fact-check explanation in V1.
- Presentation mode should "work a lot, manifest little": internal preparation is encouraged; external manifestation requires a clear reason.
- Ambient PCM/transcript privacy semantics already established by the presentation ambient lane must be preserved. Presentation mode must not silently turn ambient listening into explicit recording.
- Do not write ambient room speech into canonical conversation history as if it were an addressed Jarvis turn.

## Current cross-task state observed at handoff creation

As of 2026-10-05, Drive contains these relevant Jarvis handoffs:

- `Jarvis/task/current/jarvis-scene-window-prefab-foundation/` — currently active; owns reusable window/prefab definition, runtime instantiation and agent-facing scene operations.
- `Jarvis/task/to-do/jarvis-tool-brain-ui-orchestrator/` — pending; owns UI decision/timing, dynamic UI-tool choice, action queueing and UI perception.
- `Jarvis/task/done/jarvis-conversation-observability-timeline/` — canonical conversation event record and live diagnostic timeline.
- `Jarvis/task/done/jarvis-board-session-context-runtime/` — Board/Session runtime and interaction-mode persistence semantics.
- `Jarvis/task/done/jarvis-session-context-recording-runtime/` — Session/Context continuity, explicit recording/capture, and explicit separation between ambient PRESENTATION listening and durable recording.

The previously created Presentation task was intentionally deleted by the user. This handoff is a fresh task expressing the requirement directly; it must not assume the deleted task is canonical.

## Cross-handoff coordination rules

- Do not reimplement UI orchestration. Presentation publishes semantic UI/display intentions; Tool Brain decides concrete UI calls and timing on the normal path.
- Do not create a presentation-only scene/window model. Use the Scene/Prefab contracts once available; relevant slices may wait for the required public contract while unrelated presentation logic proceeds.
- Do not redefine Session, Context, Board or recording semantics. Consume current repository contracts after Slice 00 verifies them.
- Do not create a parallel observability log. Emit presentation decisions/events into the canonical event/timeline system.
- If repository reality has already implemented parts of this task, preserve/reconcile them rather than rewriting them for symmetry with this handoff.

## Start here

The receiving agent is the Project Manager and orchestrator for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself. Do not dispatch implementation work until Slice 00 reaches `READY`.

Slice 00 must first perform an independent blind audit of the current repository and the current state of the dependent handoffs before relying on this handoff's architectural conclusions.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline`. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, MCP, presentation policy, or agent runtime changes add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, create an Issue, or escalate.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation never substitutes for machine validation. Before a human microphone/presentation-flow check, exhaust deterministic replays, fakes and automated runtime checks.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed to this task-creation environment. Slice metadata therefore uses `task_type: null`. Slice 00 must resolve every implementation Slice to an existing valid Workspace Task Type before dispatch; never invent a Task Type label.
