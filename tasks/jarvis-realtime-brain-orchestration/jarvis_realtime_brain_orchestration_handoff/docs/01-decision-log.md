# 01 - Decision Log

## Decision 01 - Core owns the brain

**Status:** locked

**Decision:** The authoritative `BrainOrchestrator` is a long-lived Core service, not a member of the Voice runtime.

**Rationale:** Voice can mute, reconnect, or crash without destroying durable work. Core already owns conversations, jobs, state, and an async event bus.

**Implications:** Voice submits turns over the local protocol and receives brain speech/work events through Core.

**Tests / enforcement:** Core unit tests run with fake brain backends and no microphone/OpenAI dependency.

## Decision 02 - Realtime is a surface, not the authority

**Status:** locked

**Decision:** Realtime handles audio, turn-taking, barge-in signals, and strict reflex conversation. It does not own task truth or operational claims.

**Rationale:** This keeps latency low without allowing a small surface model to hallucinate work state.

**Implications:** Prompts and tests must explicitly prevent unverified task-progress claims.

**Tests / enforcement:** Reflex-policy tests and provenance metadata on assistant turns.

## Decision 03 - One brain first

**Status:** locked

**Decision:** Implement one orchestrator/brain in this project slice.

**Rationale:** Multi-agent execution adds scheduling, ownership, cancellation, and merge complexity that is not required to prove the architecture.

**Implications:** Contracts include correlation/work identifiers but no multi-agent scheduler is implemented.

**Tests / enforcement:** No task should add agent-pool logic unless the task plan is explicitly revised.

## Decision 04 - Reuse `ProtocolEnvelope` and `CoreEventBus`

**Status:** locked

**Decision:** Brain events use the existing provider-neutral `ProtocolEnvelope` and existing Core event bus.

**Rationale:** The repository already has correlation and conversation identifiers plus an event WebSocket.

**Implications:** Do not invent a parallel event framework in Voice.

**Tests / enforcement:** Protocol/event tests verify brain event serialization through `/v1/events`.

## Decision 05 - Reuse `/v1/events` for Core -> Voice

**Status:** locked

**Decision:** Voice subscribes to Core brain events through the current `LocalCoreClient.events()` WebSocket.

**Rationale:** It is already authenticated, loopback-only, versioned, and asynchronous.

**Implications:** New event types may be added, but a second IPC server is not needed.

## Decision 06 - Explicit brain-turn ingress

**Status:** locked

**Decision:** Add a Core API/service entrypoint that atomically persists an authoritative completed user turn and dispatches it to the brain once.

**Rationale:** The current Voice path appends turns separately; adding brain dispatch beside it would create double-write or race risks.

**Implications:** Migration must remove the old duplicate append path for brain-routed turns.

## Decision 07 - Completed transcript is authoritative

**Status:** locked

**Decision:** Input transcript deltas may be observed as tentative context, but irreversible work/tools begin only from a completed addressed user turn.

**Rationale:** Streaming transcription can revise words and must not trigger unsafe duplicate work.

**Implications:** Partial input support is an optimization seam, not an execution trigger.

## Decision 08 - Continuous LIVE session

**Status:** locked

**Decision:** `response.done` no longer implies `mute()` in continuous mode.

**Rationale:** A LIVE conversation must span multiple user/assistant turns.

**Implications:** BACKGROUND is entered only by explicit mute/manual stop, useful inactivity timeout, or unrecoverable session failure.

## Decision 09 - Lifecycle and activity are separate

**Status:** locked

**Decision:** Keep coarse lifecycle states such as BACKGROUND/CONNECTING/ACTIVE/ERROR, while listening/speaking/working are independent activity projections rather than exclusive lifecycle states.

**Rationale:** The system may be listening while brain work is active, or speaking while jobs continue.

## Decision 10 - Useful activity excludes ambient audio

**Status:** locked

**Decision:** Ambient noise and background speech do not reset the LIVE timeout.

**Rationale:** The user previously required inactivity to mean no meaningful order/interaction, not silence in the room.

**Implications:** Only addressed turns and meaningful Jarvis work/speech events count as useful activity.

## Decision 11 - `Jarvis Mute` never cancels Core work by default

**Status:** locked

**Decision:** Mute closes/suspends the Realtime voice surface and returns wake-word handling, while Core jobs continue.

**Rationale:** Mute is a voice-state command, not a task-cancellation command.

## Decision 12 - No raw chain-of-thought persistence

**Status:** locked

**Decision:** Store structured public working state, not hidden reasoning traces.

**Rationale:** The orchestrator needs durable state, but raw hidden reasoning is unnecessary and creates coupling and privacy risk.

## Decision 13 - Brain speaks through typed speech requests

**Status:** locked

**Decision:** Core emits `SpeechRequest` events containing complete public text plus priority/provenance metadata.

**Rationale:** Realtime should render/speak brain output, not reinterpret operational truth.

**Implications:** Replace the use of `send_context()` as a fake user-message injection for brain speech.

## Decision 14 - Strict surface reflex policy

**Status:** locked

**Decision:** Realtime may autonomously produce only short acknowledgements/backchannels and simple hearing clarification. It must not invent progress, results, or success/failure.

**Rationale:** The brain owns truth and intent.

## Decision 15 - User interruption stops speech, not work

**Status:** locked

**Decision:** Barge-in immediately stops audible output and synchronizes the Realtime conversation history, but active Core jobs are not cancelled automatically.

**Rationale:** The user's new turn may merely refine or ask about ongoing work.

## Decision 16 - Brain decides intent revision/cancellation

**Status:** locked

**Decision:** The completed interruption turn is authoritative input to the brain; the brain decides whether work is revised, superseded, cancelled, or retained.

## Decision 17 - WebSocket first; sideband later

**Status:** locked

**Decision:** Keep the current direct OpenAI Realtime WebSocket topology for the first implementation.

**Rationale:** Jarvis is already a local server-side Python client, so OpenAI sideband is not required to create a server-control path now.

**Implications:** Adapter contracts should remain transport-neutral enough to support WebRTC plus sideband later.

## Decision 18 - Model ids remain configuration

**Status:** locked

**Decision:** Do not hard-code the surface model into business logic. `gpt-realtime-2.1-mini` is a recommended low-latency surface configuration, not a domain constant.

**Rationale:** Provider model availability changes faster than architecture.

## Decision 19 - Existing Claude integration becomes a backend adapter

**Status:** locked

**Decision:** The existing local Claude path is initially reused behind a `BrainBackend` port. Voice must stop owning direct `ClaudeGateway` orchestration.

**Rationale:** This preserves current capability while putting orchestration ownership in the correct process.

## Decision 20 - Roll out behind a compatibility mode

**Status:** locked

**Decision:** Keep a legacy voice path or feature switch until continuous async brain mode passes automated and workstation acceptance gates.

**Rationale:** Audio interruption and echo behavior are hardware-sensitive; migration must be reversible.
