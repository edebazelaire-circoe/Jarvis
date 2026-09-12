# 02 — Target Architecture Spec

## 1. Audio pipeline

### 1.1 Existing components to keep

- `SoundDeviceRealtimeAudio`
- `CaptureProcessor`
- `WebRtcEchoCanceller`
- `NearEndDetector`
- existing output reference feed and local `stop_output()`
- provider cancellation/truncation and playback cursor accounting
- `turn_filters`
- semantic/server VAD configuration

### 1.2 New typed boundary

Introduce a provider-neutral port similar to:

```python
class SpeakerVerifier(Protocol):
    def reset(self) -> None: ...
    def process(self, pcm: bytes, sample_rate: int) -> SpeakerVerification: ...
    def close(self) -> None: ...
```

The exact synchronous/async shape should match the capture-thread constraints. Do not perform network I/O from the PortAudio callback.

Typed result should carry at least:

- `owner_score: float | None`
- `owner_detected: bool`
- `evidence_ms: int`
- `profile_id: str | None`
- `engine: str`
- optional stable diagnostic reason/status

Never expose raw embeddings in normal telemetry.

### 1.3 Shadow mode first

Before enforcement, run the verifier without changing audio routing. Emit bounded diagnostics:

- candidate detected;
- owner score;
- time to owner confirmation;
- candidate rejected;
- overlap scenario if inferable;
- engine/model identifier.

No transcript/audio content in metrics.

### 1.4 Solo Owner gate

In `solo_owner` mode:

- arbitrary near-end detection does **not** duck or cut JARVIS;
- while JARVIS speaks, capture continues locally and speaker verification keeps running;
- on owner confirmation, immediately stop local output and mark barge-in;
- open/replay buffered owner audio to provider;
- provider `speech_started` can correlate/confirm but cannot be required to stop local output;
- if verifier rejects/non-owner, continue playback unchanged;
- when JARVIS is silent, non-owner speech is not forwarded as a conversational turn.

### 1.5 Ring buffer

The existing short pre-roll was tuned for fast near-end confirmation. Add a separately named owner-verification ring buffer, configurable and bounded.

Recommended starting default for experiments: 2500 ms.

Constraints:

- memory-only;
- no persistence;
- reset on session activation/deactivation;
- no duplicate frames when the gate opens;
- preserve exact stream order;
- tests for buffer wrap and sample-rate changes.

## 2. Conversation modes

Introduce an explicit semantic mode rather than overloading architecture flags:

- `open_room` / existing behavior (name provisional if current product vocabulary differs)
- `solo_owner`

Do not conflate this with `legacy` vs `continuous_brain`; one describes conversation authorization, the other voice architecture.

For `solo_owner`:

- wake mechanism remains independent (`WakeWordBackend` already exists);
- owner recognition applies to active voice input;
- wake word may later have its own secure-owner policy, but this handoff does not require it;
- owner speech may be `addressed` or `uncertain` according to existing engagement/addressing rules.

## 3. Degraded behavior

Quality-first requirement:

- if configured AEC is unavailable, expose a visible degraded state;
- if `solo_owner` is configured but no usable owner profile/verifier is available, do not silently pretend owner filtering exists;
- choose an explicit policy: refuse Solo Owner activation or fall back to an explicitly labelled open-room behavior. Recommended: refuse Solo Owner and offer a clear diagnostic.

## 4. Work-state architecture

### 4.1 Existing issue

`AgentTaskTracker` reconstructs detailed CLI task state for runtime/UI. `BrainWorkingState` currently exposes mostly work IDs and conversational public facts. The detailed task projection is not yet a Core-owned shared truth.

### 4.2 New normalized domain object

Add a provider-neutral work observation/snapshot type. Suggested fields:

- `work_id` / stable external task id
- `provider`
- `kind`
- `status`
- `started_at` / `ended_at`
- `activity`
- `summary`
- `model` when known
- `parent_work_id` when known
- `progress_fraction` when meaningful
- `tool_uses` / tokens only if useful and bounded
- `error_class` / public failure summary
- `revision`

Keep provider raw event traces outside Core public state.

### 4.3 Core WorkStateStore

Core owns the normalized state and revisions. Provider-specific trackers feed observations into it through a port/service.

Consumers:

- Brain receives current work snapshot or can query it through a Core-owned context service.
- UI reads Core projection.
- speech/notification policy subscribes to Core work-state events.

### 4.4 Brain context

Do not force huge task traces into every `BrainWorkingState` event. Prefer a bounded normalized `WorkSnapshot`/`BrainContext` assembled by Core at brain-turn execution, or a typed Core query port. Preserve the invariant that the backend receives public/operational facts only, never hidden chain-of-thought.

### 4.5 Event-driven state changes

When work fails/completes/blocks outside a user turn:

- Core updates work state;
- emits a normalized event;
- a policy may wake the brain to interpret user relevance;
- speech is optional and governed by priority/salience.

Do not make the Control Center poll become the source of those transitions.
