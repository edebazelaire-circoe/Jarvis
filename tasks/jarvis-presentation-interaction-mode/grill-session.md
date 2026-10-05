# Reconstructed planning session

This file is reconstructed from the project conversation because an exact verbatim export of the full discussion was not available to the task creator. It preserves only decisions and intent actually established in the conversation and related durable Jarvis handoffs.

## User intent recovered

The user separated two concerns:

1. a lower-level rework of windows/prefabs so Jarvis can create, reuse, modify and save reusable UI objects;
2. a higher-level Presentation interaction mode that consumes that foundation.

The user explicitly chose to keep Presentation as a separate task after the reusable window/prefab foundation, rather than mixing both into one implementation task.

The intended Presentation behavior had already been explored in the project: Jarvis should continuously follow a live presentation, remain highly active internally, prepare information and visual material in the background, but manifest very little unless the user explicitly addresses it or a discreet attention event is justified.

The user later deleted the previous Presentation task and asked for a fresh task that expresses the need clearly.

## Product behavior already established in project discussion

- Presentation is an interaction mode, separate from the underlying voice architecture.
- SIMPLE remains the default ordinary behavior.
- PRESENTATION continuously consumes ambient speech as contextual evidence.
- Ambient speech is not itself a command to Jarvis.
- Explicit address (wake word/manual address) is the authority boundary for commands/questions.
- Explicit work has absolute priority over speculative/background work.
- Jarvis may delegate background research, fact-checking, document lookup and visual preparation while the user continues presenting.
- Visual commands should normally execute without unnecessary filler speech.
- Real questions may receive speech when useful, plus supporting visuals where appropriate.
- A fresh transcript tail must remain available independently of slower semantic enrichment so phrases such as "montre-moi ça" resolve against what was just said.
- Presentation keeps a bounded session-scoped working set of current topics, facts, source references, prepared resources and unresolved points; it is not long-term memory.
- Ambient contradictions may create a discreet audible cue and small visual warning/attention signal, but V1 does not interrupt with unsolicited spoken fact-check explanations.
- The design principle is: **work a lot, manifest little**.

## Architectural reconciliation discovered during task creation

The newer Jarvis architecture adds two critical boundaries that the Presentation task must now respect:

- `jarvis-tool-brain-ui-orchestrator`: UI execution/timing belongs to Tool Brain. Presentation should emit semantic display/attention intentions instead of directly deciding low-level window/scene calls.
- `jarvis-scene-window-prefab-foundation`: reusable windows/prefabs and scene lifecycle belong to the scene/prefab foundation. Presentation consumes these objects for prepared/on-demand visuals and must not create a second presentation-specific renderer.

Durable completed Jarvis tasks also establish canonical conversation observability, Board/Session semantics and explicit recording/capture. Presentation must integrate with those contracts instead of redefining them.
