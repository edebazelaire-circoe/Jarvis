# 00 - Overview

## Goal

Make Jarvis feel continuously present and responsive while retaining a stronger asynchronous brain behind the voice surface.

The user-visible target is:

1. The user speaks naturally.
2. Realtime detects and understands the turn with minimal delay.
3. The surface can produce a very short reflex acknowledgement when appropriate.
4. The authoritative completed turn is sent to Jarvis Core.
5. Core's brain accepts/revises intent and starts or updates work asynchronously.
6. Core emits public speech requests as questions, progress, or results become available.
7. Voice schedules and speaks those requests without fabricating task state.
8. If the user interrupts, audio stops quickly, the brain receives the interruption/new turn, and active work continues unless the brain explicitly cancels or revises it.

## Current architecture that must be preserved

Jarvis already follows a ports/adapters direction. Core is intentionally provider-neutral and long-lived. External provider JSON and audio implementation details should remain outside Core.

The new design should extend these seams, not replace them with a second monolithic agent runtime.

## Target topology

```text
+------------------------- Voice process --------------------------+
|                                                                   |
|  microphone -> SoundDevice -> OpenAI Realtime adapter             |
|                              |                  ^                 |
|                              | events           | speech control  |
|                              v                  |                 |
|                     RealtimeConversationBridge |                 |
|                              |                  |                 |
|                              +-> LocalCoreClient+<- SpeechScheduler
|                                      |                            |
+--------------------------------------|----------------------------+
                                       |
                          loopback authenticated protocol
                                       |
+--------------------------------------v----------------------------+
|                         Jarvis Core process                       |
|                                                                   |
| ConversationService -> BrainOrchestrator -> BrainBackend          |
|         |                   |               (Claude initially)    |
|         |                   +-> JobService / tools                |
|         |                   +-> structured WorkingState           |
|         |                   +-> SpeechRequest events              |
|         +----------------------> CoreEventBus                      |
|                                      |                            |
|                                      +-> /v1/events WebSocket      |
+-------------------------------------------------------------------+
```

## Scope

This handoff includes:

- typed brain/speech contracts;
- Core-owned brain orchestration;
- protocol ingress and event egress;
- Realtime adapter controls required for continuous conversation;
- continuous LIVE lifecycle;
- strict reflex policy;
- migration away from blocking `claude_task` in Voice;
- speech scheduling;
- barge-in/interruption semantics;
- structured progress and working state;
- tests, diagnostics, rollout, and final repository documentation updates.

## Non-goals

- building a full multi-agent scheduler now;
- exposing model chain-of-thought;
- moving the desktop UI to WebRTC now;
- replacing the entire current Core protocol;
- implementing acoustic echo cancellation from scratch;
- removing legacy voice mode before the new path has passed acceptance tests;
- updating Git documentation during this planning/handoff creation step.

## Core design invariant

The lifetime of a brain task is independent of the lifetime of a Realtime voice session.

This invariant is the reason the brain belongs in Core rather than in `PersistentVoiceRuntime` or `RealtimeConversationBridge`.
