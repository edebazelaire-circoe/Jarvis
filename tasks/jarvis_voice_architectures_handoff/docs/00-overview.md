# Overview

## Goal

Evolve JARVIS voice from a mostly serialized “voice surface + heavy brain” pipeline into a conversation platform with explicit architecture modes, a stable frontend contract, strong speech gating, non-blocking backend work, visible prompts, cost safety, and reproducible benchmarks.

## Why this work exists

The 11 September trace demonstrates four concrete problems that must become regression cases:

1. Backend answers can be replaced by voice improvisation.
2. Speech can remain queued until it is contextually stale.
3. Heavy work can monopolize the main brain and delay later user turns.
4. Noise can create large numbers of false interruption signals.

The desired architecture is not “a better canned acknowledgement layer”. It is a system that treats **silence, speech, delegation, cancellation, and background work as explicit concurrent decisions**.

## Mental model

```text
Audio I/O
   │
   ▼
VoiceFrontend adapter
   │ canonical events
   ▼
JARVIS Conversation Core ───────────────► Back Brain / tasks / sub-agents
   │                                           │
   │ speech decisions                          │ typed results/events
   ▼                                           ▼
VoiceFrontend ◄────────────────── result routing / context injection
```

The implementation must support three frontend configurations without changing the back brain:

```text
SIMPLE
  voice model ──► Conversation Core ──► Back Brain

FRONT BRAIN
  voice/reflex model ─┐
                      ├─► Conversation Core ──► Back Brain
  fast analysis model ┘

DUPLEX
  GPT-Live/full-duplex frontend ◄──► Conversation Core ◄──► Back Brain
```

## Scope

- Common `VoiceFrontend` contract and canonical event model.
- Three architecture modes and capability-driven model selectors.
- Realtime Mini baseline retained and improved.
- Optional Front Brain analysis model, initially Luna.
- GPT-Live 1 client-delegation adapter.
- Reflex/WAIT/preamble policy.
- Partial-transcript speculative analysis.
- Speech freshness/cancellation/chunking.
- Semantic VAD and noise/barge-in improvements.
- Prompt registry/editor and effective-prompt inspection.
- GPT-Live active-session safety controls.
- Benchmark metrics and replay scenarios.

## Non-goals

- Rewriting JARVIS's durable task/sub-agent system from scratch.
- Making provider-internal hidden prompts visible.
- Locking Gemini model identifiers without inspecting the existing provider code.
- Choosing a permanent winner between Realtime+Luna and GPT-Live before benchmarks.
- Building irreversible actions directly from partial transcript deltas.

## Product success

A user can switch among the three modes, understand exactly which models/prompts are active, converse without repetitive reflex filler, interrupt naturally, continue talking while backend tasks run, manually stop any billable Live session immediately, and compare modes using the same metrics and scenarios.
