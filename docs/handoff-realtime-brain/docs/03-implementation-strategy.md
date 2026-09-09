# 03 - Implementation Strategy

## Guiding rule

Migrate by moving ownership one seam at a time. Do not attempt to rewrite audio, Core, Claude, protocol, and orchestration in one change.

## Phase A - Contracts before behavior

Tasks 01-03 establish typed domain contracts, Core brain ownership, and the local protocol path. These changes should be testable with fake backends and no real OpenAI/Claude calls.

At the end of Phase A:

- Core can accept a final user turn and return quickly;
- brain work can continue asynchronously;
- Core can emit typed speech requests over the existing event stream;
- Voice does not need to consume them yet.

## Phase B - Make Realtime controllable

Task 04 extends the Realtime adapter with the exact events and controls required by the later runtime behavior:

- transcript deltas and item ids;
- response/output identifiers;
- faithful speech injection;
- cancel/truncate semantics;
- provider-neutral event mapping.

Keep this adapter work isolated and deterministic with fake WebSocket tests.

## Phase C - Continuous LIVE lifecycle

Tasks 05-06 change runtime lifecycle and surface policy:

- response completion no longer mutes continuous sessions;
- multiple turns can occur in one ACTIVE session;
- mute and useful inactivity still return to BACKGROUND;
- reflex output is intentionally constrained.

Do not migrate long-running brain work in the same task; first prove the continuous surface remains stable.

## Phase D - Move brain ownership out of Voice

Task 07 replaces the current Voice-owned blocking `claude_task` path with Core-owned `BrainOrchestrator` + `BrainBackend`.

Initially, the backend can still call the existing Control Center Claude agent. The crucial change is ownership and async behavior, not the provider.

A successful migration means:

- Voice no longer waits inside `_call_claude()`;
- Voice no longer keeps a Realtime tool call open for minutes to represent brain work;
- Core owns the running work and can survive `Jarvis Mute`;
- final brain output appears as a Core event.

## Phase E - Return brain speech continuously

Task 08 adds the Voice `SpeechScheduler` and faithful Realtime rendering.

Task 09 adds interruption and intent revision.

Task 10 adds structured progress and public working-state updates so the brain can emit useful incremental speech rather than only a final answer.

## Phase F - Integration and rollout

Tasks 11-12 add end-to-end scenarios, telemetry, fallback mode, workstation acceptance, and documentation.

Do not remove the legacy mode until acceptance gates are green on the target workstation.

## Feature-switch recommendation

Prefer one coarse rollout switch over many independent booleans, for example:

`JARVIS_VOICE_ARCH=legacy|continuous_brain`

Keep provider model ids in existing environment/config settings. If a separate transcription model setting is added, make it provider configuration, not a Core concept.

## Model rollout recommendation

For the surface, test `gpt-realtime-2.1-mini` as a low-latency configuration while preserving `OPENAI_REALTIME_MODEL` override behavior. Do not encode this model id in domain logic.

If streaming transcription is enabled, make the transcription model independently configurable. The implementation should remain correct if only completed transcripts are available.

## Migration of current code paths

### `PersistentVoiceRuntime`

Change from one response per activation to a session lifecycle owner. Keep wake/mute/Core separation intact.

### `RealtimeConversationBridge`

Reduce responsibility over time. It should bridge audio/events and submit turns; it should not own the strong brain provider.

### `ClaudeGateway`

Move/replace as a `BrainBackend` adapter available to Core. Avoid importing aiohttp or Control Center details into `jarvis/core`.

### `CoreEventBus`

Reuse as the async backbone. If backpressure policy needs improvement for brain speech events, change it deliberately and test it rather than adding another bus.

### `JobService`

Reuse for durable asynchronous work. Add progress emission if needed.

### `LocalProtocolServer` / `LocalCoreClient`

Add brain-turn submission while preserving version/auth patterns. Reuse `/v1/events` for speech/work updates.

### `OpenAIRealtimeSession`

Expand semantic control surface. Do not let OpenAI event payloads leak into Core contracts.

## Documentation strategy

Do not edit repository docs during handoff creation. During the final implementation task, update the Git documentation to describe the implementation that actually landed, not the design that was merely planned.
