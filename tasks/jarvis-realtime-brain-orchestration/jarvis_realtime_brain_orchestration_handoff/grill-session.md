# Reconstructed Grill Session

This is a reconstructed grill session based on the available conversation context and repository inspection. It preserves the locked decisions and important user corrections without pretending to reproduce every word of the original chat.

## Starting problem

The current Jarvis voice experience should become more like a continuous LIVE conversation rather than a strict sequence of user speech, full reasoning, then one complete spoken answer. The desired experience is low-latency and interruptible, while still allowing deep reasoning and long-running work behind the voice surface.

## User intent

The user wants a fast, relatively small Realtime model at the surface. That model should handle speech input/output and very small conversational reflexes. A stronger orchestration brain behind it should own planning, task management, reasoning, the authoritative conversation state, and eventually coordination of multiple sub-agents.

The surface should be able to say things such as a brief acknowledgement immediately, while the brain continues working. The brain should later be able to send complete, well-formed natural-language updates, questions, and results back to the voice surface as new information becomes available.

## Important correction: this is not just STT -> LLM -> TTS

The user explicitly wants the architecture to exploit Realtime event streams and interruption semantics. The implementation must connect to the Realtime event flow rather than treating Realtime as a closed, one-shot voice request.

The desired loop is conceptually:

```text
User audio
   |
   v
Realtime surface <--------------------------+
   |                                        |
   | transcript/events                      | speech requests
   v                                        |
Jarvis Core -> Brain Orchestrator -> jobs ---+
   |                         |
   +-------------------------+
        durable working state
```

## Important correction: the brain is not raw chain-of-thought

The user described an orchestrator whose thought process evolves while work happens. The implementation should not attempt to expose or persist hidden chain-of-thought. Instead, the brain must maintain a structured working state that is safe to persist and useful for orchestration:

- current user intent;
- active work items;
- known public facts/results;
- unresolved questions;
- public progress state;
- completed results;
- current conversation goal;
- revision/version metadata.

The brain can emit public speech requests from this state.

## Important correction: Realtime may speak, but only inside a strict boundary

The user accepted the following boundary:

> Realtime has reflexes; the brain owns truth and intent.

The surface is allowed to do immediate conversational turn-taking, for example short acknowledgements and simple hearing/clarification behavior. It is not allowed to claim that a task started, succeeded, failed, found data, changed a file, or reached a result unless that information came from the brain/Core.

## Interruption requirement

The user must be able to speak while Jarvis is speaking. That should interrupt the audible output quickly. It must not automatically destroy a long-running background task. The new user turn is sent to the brain, which decides whether to revise, cancel, continue, or fork the work.

## Continuous conversation requirement

A completed Realtime response should not automatically end the LIVE voice session. The session remains LIVE across multiple turns until one of the existing lifecycle conditions ends it:

- explicit `Jarvis Mute`;
- meaningful inactivity timeout;
- explicit manual stop/toggle where configured;
- transport/provider failure that cannot be recovered.

Ambient noise, keyboard noise, or unrelated background speech must not count as meaningful activity.

## Background behavior requirement

`Jarvis Mute` means return the voice layer to BACKGROUND. It does not stop Jarvis Core and does not imply cancellation of active jobs. Core must remain able to complete work and emit later events/notifications.

## First implementation scope

Only one orchestrator/brain is required now. The architecture must avoid assumptions that would prevent later fan-out to sub-agents or multiple concurrent work items, but multi-agent scheduling itself is out of scope for this handoff.

## Repository inspection conclusions

The current V2 code already contains several useful seams:

- `ProtocolEnvelope` carries message type, correlation id, device id, and conversation id.
- `CoreEventBus` already publishes asynchronous envelopes.
- `JobService` already runs jobs asynchronously and persists their lifecycle.
- `LocalProtocolServer` already exposes `/v1/events` as a WebSocket.
- `LocalCoreClient` already consumes that event stream.
- `ConversationService` already persists turns and rehydrates recent conversation context.
- `PersistentVoiceRuntime` already separates BACKGROUND/ACTIVE lifecycle from Core lifecycle.

The current blockers are also clear:

- `on_response_done=self.mute` ends the voice session after a response.
- server-VAD commit currently closes microphone input for the active bridge.
- `claude_task` is intercepted in the voice bridge and awaited synchronously.
- `ClaudeGateway.ask()` returns one final result, so no incremental brain progress crosses that boundary.
- Realtime input transcription is mapped only at completion, not as deltas.
- `send_context()` injects brain text as a fake user message, which is not an appropriate speech-output contract.
- WebSocket barge-in does not yet perform local playback stop plus conversation truncation.

## Locked architecture direction

The brain will be Core-owned and long-lived. Voice will submit authoritative completed user turns to Core and subscribe to Core events. Core will publish typed speech requests and work-state events. Voice will schedule these requests and use the Realtime adapter to speak them faithfully.

The first implementation will keep the existing direct Realtime WebSocket topology. OpenAI sideband/WebRTC remains a future transport option rather than a prerequisite.
