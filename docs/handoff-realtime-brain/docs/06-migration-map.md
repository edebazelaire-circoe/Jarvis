# 06 - Current-to-Target Migration Map

## `jarvis/runtime/voice_v2.py`

### Current

- `PersistentVoiceRuntime` opens one Realtime session on activation.
- `on_response_done=self.mute` couples response completion to end of LIVE mode.
- `mute()` correctly closes Voice resources while leaving Core alive.

### Target

- Preserve wake/background ownership and mute semantics.
- In continuous mode, response completion only updates activity/visual state.
- Add/own a Core event subscription task and SpeechScheduler lifetime tied to ACTIVE voice transport.
- Keep brain work lifetime independent from this class.

## `jarvis/runtime/realtime_audio.py`

### Current

- Voice bridge owns audio pumping and provider events.
- It directly intercepts `claude_task` and awaits Claude.
- Auto-turn closes microphone input on `realtime.input_committed`.
- Completed transcript is persisted directly to Core.

### Target

- Remove strong-brain ownership from this bridge.
- Submit authoritative completed turns through the new brain-turn Core API.
- Keep microphone available across turns in continuous mode.
- Handle barge-in signals and local playback stop.
- Emit/consume provider-neutral ids needed for interruption.

## `jarvis/runtime/claude_gateway.py`

### Current

- Voice -> Control Center HTTP request/response.
- One final result after potentially long wait.

### Target

- Reuse logic as or replace with a Core-injected `BrainBackend` adapter.
- Voice should not call it directly.
- Contract supports events/progress even if the initial adapter emits only accepted/final events.

## `jarvis/adapters/openai_realtime.py`

### Current

- WebSocket transport.
- server VAD creates and interrupts responses.
- input transcription configured.
- only completed transcript mapped.
- brain/tool result re-entry uses function result or `send_context()`.

### Target

- Map transcript deltas and item ids.
- Track response/output ids.
- Support faithful brain speech without fake user turns.
- Support semantic cancel/truncate.
- Keep model/voice/transcription settings configurable.
- Apply strict surface-reflex operating rules.

## `jarvis/ports/v2.py`

### Current

- provider-neutral ports include `RealtimeSession`, `JobWorker`, repositories.

### Target

- add brain backend/event sink contracts;
- expand semantic Realtime control contract;
- avoid any OpenAI/Claude/aiohttp types.

## `jarvis/domain/v2.py`

### Current

- conversations, turns, jobs, protocol envelopes, lifecycle state.

### Target

- add typed brain turn/speech/working-state domain models as needed;
- retain existing Job lifecycle where possible;
- add no hidden-reasoning fields.

## `jarvis/core/v2_services.py` / new `jarvis/core/brain_service.py`

### Current

- `CoreEventBus`, `ConversationService`, `JobService` already provide most infrastructure.

### Target

- add `BrainOrchestrator` as a focused service rather than making `v2_services.py` monolithic;
- use ConversationService, JobService, and CoreEventBus via explicit dependencies;
- extend JobService with progress seam only if required by Task 10.

## `jarvis/core/v2_app.py`

### Current

- composition root for long-lived provider-neutral Core.

### Target

- inject `BrainBackend` and create BrainOrchestrator;
- preserve headless/fake startup capability.

## `jarvis/protocol/server.py`

### Current

- loopback authenticated conversation/tool APIs and `/v1/events` WebSocket.

### Target

- add authoritative brain-turn endpoint;
- continue streaming brain events through existing `/v1/events`.

## `jarvis/protocol/client.py`

### Current

- can append turns and subscribe to `/v1/events`.

### Target

- add `submit_brain_turn(...)` method;
- reuse `events()` for SpeechScheduler.

## `tests/unit/test_v2_voice_toggle.py`

### Current

- explicitly asserts response completion returns to BACKGROUND.

### Target

- preserve legacy-mode assertions where relevant;
- add continuous-mode assertions that state remains ACTIVE and multiple turns use one session.

## `jarvis/v2_config.py`

### Target

- add one architecture rollout switch if needed;
- keep model ids configurable;
- optionally separate Realtime transcription model setting.
