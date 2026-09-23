# Planning session - reconstructed

This file is a faithful reconstruction of the planning discussion available to the task creator. It is not a verbatim transcript.

## Initial product idea

The user wants a Presentation mode in which Jarvis can accompany a human presentation in the background. Jarvis should listen to the presentation continuously, understand what is being discussed, prepare useful information, search documents/news/data, and be ready to act when explicitly addressed. Ordinary presentation speech must not be mistaken for commands.

Jarvis may proactively prepare or occasionally display something highly relevant, but it must not take control of the presentation or react to every statement. The user specifically wants facts, documents, web pages, charts, and related material to be ready quickly when requested.

## Voice behavior correction

The user clarified that Presentation mode must minimize spoken interaction. A command such as "Jarvis, show me this year's report" should normally just display the report. Filler such as "Yes, I understand, here is the report" is undesirable.

A real knowledge question such as "What were our biggest sales this year?" may produce both a visual result and a spoken synthesis, including useful caveats or context. The goal is not artificially short speech; it is speech only when it adds value.

## Product mode vs voice architecture

The user explicitly corrected any design that treats Presentation as a new Simple / Front Brain / Duplex architecture. Voice architecture describes how the voice/brain system is implemented. Interaction mode describes how Jarvis behaves for the user.

The desired product modes are:

- Simple: ordinary assistant behavior.
- Presentation: implemented in this task.
- Meeting: future work, not to be designed deeply here.

All voice architectures should aim to expose the same product capabilities.

## Background work and session cache

Presentation mode should remain agentic. While the user talks, Jarvis may send sub-agents to research, fact-check, find documents, inspect code, search a website, or prepare data. Useful results should enter a bounded conversation/session cache so an explicit request can display them immediately later.

The brain remains responsible for understanding what is happening, deciding what background work is worthwhile, and knowing when the user is actually addressing Jarvis.

## Fact-check notification behavior

The user wants discreet fact-check signaling in V1. If Jarvis finds a contradiction or an important mismatch with what was just said, it should use a small audible cue and a small floating warning/attention element. It should not interrupt vocally by default.

The presenter can ignore the signal, return to it later, or ask something like "Jarvis, what is it?" / "Do you have something to add?" and then receive the explanation.

Future user personalization may range from "do not disturb me" to "interrupt me vocally on contradictions", but that policy is out of scope for V1.

## Continuous audio and priority concern

The user raised a critical latency concern: if continuous ambient audio is processed through one synchronous backlog, an explicit command may arrive one or two minutes late after heavy ongoing analysis.

The agreed design is therefore not a single synchronous queue. Presentation mode uses one continuous audio capture with parallel consumers. Ambient understanding/research is asynchronous and may lag. Wake word or the existing manual wake key creates an independent, high-priority addressed turn that must never wait behind ambient analysis.

The explicit command path receives both the enriched session working set and a fresh recent transcript tail, so references such as "show me that" can resolve even when background enrichment is behind.

## Repository evidence inspected during planning

- `jarvis/runtime/voice_v2.py` already distinguishes addressed vs ambient activity and has a persistent voice lifecycle.
- `jarvis/runtime/front_brain_sidecar.py` and `jarvis/runtime/front_brain_hints.py` already provide speculative advisory analysis with no execution authority.
- `jarvis/core/back_brain.py` currently requires addressed canonical admission for ordinary back-brain work, so Presentation ambient work needs a distinct admission/policy path rather than weakening that existing security rule.
- `jarvis/runtime/display_mcp.py` and the scene model already let the brain create artifacts/windows and control visibility. Hidden prepared scene objects are a natural staging primitive.
- `jarvis/runtime/background_events.py` and the Control Center already have discreet background notification pills. Presentation fact-check alerts should extend/reuse this system rather than creating an unrelated notification stack.
- `jarvis/adapters/wakeword_keyboard.py`, `wakeword_porcupine.py`, and `wakeword_composite.py` already normalize keyboard and Porcupine triggers, but Porcupine currently owns a separate microphone stream and suspends during active sessions. Presentation mode therefore needs a shared capture topology.
- `jarvis/runtime/realtime_audio.py` currently owns the realtime microphone stream. The new mode must preserve existing Simple behavior while introducing a shared-capture option for Presentation.
- `jarvis/runtime/control_center_barehands_hud.js` is a strong existing UI pattern for a left-side state selector driven by canonical state rather than optimistic local state.
