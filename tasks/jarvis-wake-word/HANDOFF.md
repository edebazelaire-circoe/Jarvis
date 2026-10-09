# Jarvis Wake Word - Implementation Handoff

## Objective

Implement a local voice wake-up path for Jarvis so the assistant can transition from PASSIVE to ACTIVE when the user says "Hey Jarvis", while preserving F9 as a fallback/manual trigger.

The first implementation uses openWakeWord because it is local, open source, immediately testable, and ships a pre-trained `hey_jarvis` model. The architecture must keep the wake-word engine replaceable.

## Locked product decisions

1. "Hey Jarvis" wakes Jarvis from PASSIVE to ACTIVE.
2. F9 remains supported and must use the exact same activation command/path as wake-word detection.
3. Wake-word detection belongs to the runtime/body layer, not to the Brain.
4. In PASSIVE mode, only the minimal local wake-word listener should run. Normal STT/Brain processing should not run continuously just to detect the wake phrase.
5. Returning to PASSIVE can initially be handled through normal active-mode transcription/intents, e.g. "Jarvis, go to sleep" / "stop listening". A second dedicated sleep-word detector is not required for v1.
6. openWakeWord is the v1 provider, hidden behind a provider interface so it can be replaced later.
7. Sensitivity/threshold must be configurable.
8. The implementation must expose wake-word detection as a runtime event with confidence and source metadata.
9. The pre-trained openWakeWord models are non-commercially licensed. This is acceptable for immediate private testing, but the dependency must be documented and isolated so the model can be replaced before commercial distribution.

## Target architecture

```text
Microphone audio
    |
    v
WakeWordService
    |
    +-- WakeWordProvider interface
    |       |
    |       +-- OpenWakeWordProvider (v1)
    |
    +-- emits WAKE_WORD_DETECTED
            {
              keyword: "hey_jarvis",
              confidence: <float>,
              source: "microphone"
            }
    |
    v
Runtime activation command
    |
    +-- source = "wake_word"
    +-- source = "keyboard_f9"
    |
    v
PASSIVE -> ACTIVE
```

The central rule is that F9 and wake-word detection are two input sources for one canonical activation command. They must not maintain separate activation behavior.

## State model

Minimum state contract:

```text
PASSIVE
  - wake-word listener running
  - normal conversational STT/Brain path not continuously active

ACTIVE
  - normal Jarvis listening/transcription/conversation behavior
  - wake-word listener may be paused or ignored, depending on current audio architecture

ACTIVE -> PASSIVE
  - existing/manual sleep action
  - voice intent while ACTIVE, if supported by current command architecture
```

Do not create a second competing state machine if Jarvis already has a canonical runtime/session state model. The implementation agent must first locate and extend the existing source of truth.

## Interfaces

Names are provisional until reconciled with the repository conventions.

```ts
interface WakeWordProvider {
  start(): Promise<void> | void;
  stop(): Promise<void> | void;
  setSensitivity(value: number): void;
  onDetection(handler: (event: WakeWordDetection) => void): Unsubscribe;
  healthCheck(): Promise<WakeWordHealth> | WakeWordHealth;
}

type WakeWordDetection = {
  keyword: string;
  confidence: number;
  source: "microphone";
  detectedAt: number;
};
```

Runtime-facing command/event should be conceptually equivalent to:

```ts
activateJarvis({ source: "wake_word" | "keyboard_f9" });
```

If the repository already uses commands, events, reducers, actors, IPC messages, or state machines, reuse that existing mechanism rather than introducing this exact API.

## openWakeWord v1 provider

Requirements:

- Runs locally.
- Uses the upstream pre-trained `hey_jarvis` model for initial validation.
- Does not send microphone audio to a remote service.
- Receives audio from the existing microphone/audio capture stack where possible.
- Avoids opening a second microphone stream if Jarvis already owns a canonical audio capture pipeline that can fan out frames.
- Normalizes/resamples audio only at the audio boundary required by the provider.
- Applies configurable detection threshold/sensitivity.
- Adds a short debounce/cooldown to avoid multiple activations from one utterance.
- Stops/pauses cleanly during shutdown and microphone device changes.
- Surfaces provider initialization and health failures without crashing the entire Jarvis runtime.

## Licensing constraint

As of the implementation planning date, openWakeWord repository code is Apache-2.0, while the bundled/pre-trained wake-word models are CC BY-NC-SA 4.0. Therefore:

- v1 may use the upstream `hey_jarvis` model for immediate private/non-commercial testing.
- The model/license must be recorded in third-party notices or the repository's dependency/license documentation.
- The model must not be treated as a permanently redistributable commercial asset.
- The provider boundary must make it straightforward to swap the model or engine.
- If Jarvis is prepared for commercial distribution, replace the model with a commercially compatible model or a custom-trained artifact whose training data/model rights are known.

Upstream reference: https://github.com/dscripka/openWakeWord

## Configuration

Add wake-word configuration through the project's existing settings/config mechanism. Do not invent a parallel config store.

Minimum settings:

```text
wakeWord.enabled = true
wakeWord.provider = "openwakeword"
wakeWord.keyword = "hey_jarvis"
wakeWord.sensitivity = <reasonable default>
wakeWord.cooldownMs = <reasonable default>
```

Optional if supported by current architecture:

```text
wakeWord.modelPath
wakeWord.inputDeviceId
wakeWord.debugMetrics
```

## Runtime behavior

### Startup

If wake-word is enabled:

1. Initialize the provider.
2. Attach it to the microphone/audio source.
3. Start detection when Jarvis is PASSIVE.
4. Report provider health through existing diagnostics/logging.

Failure to initialize wake-word detection should degrade gracefully: F9 remains usable and Jarvis should expose a clear diagnostic reason.

### Detection

On a valid `hey_jarvis` detection above threshold:

1. Apply debounce/cooldown.
2. Emit/log the wake-word detection event.
3. Invoke the canonical activation command.
4. Transition PASSIVE -> ACTIVE through the existing runtime state mechanism.
5. Trigger the same UI/audio feedback used by manual activation, unless product behavior already differentiates source metadata intentionally.

### Manual activation

Refactor F9 if necessary so it calls the same activation command rather than directly mutating state/UI.

### Returning to passive

In ACTIVE mode, existing voice transcription can map sleep phrases to the canonical deactivation/sleep command. This is separate from wake-word recognition and should reuse existing intent/command routing when available.

## Observability

Add structured diagnostics sufficient to tune false positives/false negatives without storing raw continuous microphone audio by default.

Recommended events/fields:

```text
wake_word.provider_started
wake_word.provider_failed
wake_word.detected
wake_word.ignored_below_threshold
wake_word.cooldown_ignored
wake_word.provider_stopped

keyword
confidence
threshold
provider
source_device (non-sensitive identifier if already available)
state_before
state_after
```

Do not persist continuous microphone audio unless a dedicated opt-in debug feature already exists and the privacy implications are handled by the project.

## Acceptance criteria

The implementation is complete when all of the following are true:

- Saying "Hey Jarvis" while Jarvis is PASSIVE activates Jarvis locally.
- F9 still activates Jarvis.
- F9 and wake-word use one canonical activation path.
- Jarvis does not require the Brain to run in order to detect the wake word.
- In PASSIVE mode, normal conversational STT is not kept active solely for wake-word recognition.
- Sensitivity is configurable.
- Repeated frames from one utterance do not produce repeated activations.
- Wake-word provider failure leaves F9/manual activation operational.
- The provider can be disabled by configuration.
- The provider is replaceable through an interface/adapter boundary.
- Unit/integration tests cover detection, below-threshold rejection, cooldown, provider failure, F9 parity, and PASSIVE/ACTIVE transition behavior.
- A real microphone validation confirms successful activation and checks practical false positives/false negatives.
- Third-party license documentation explicitly records the non-commercial license of the pre-trained `hey_jarvis` model.

## Non-goals for v1

- Training a production-grade custom wake-word model.
- Cloud wake-word recognition.
- Speaker identification/authentication.
- Always-on full speech transcription while PASSIVE.
- A second dedicated "sleep word" detector.
- Reworking the entire audio subsystem unless repository inspection proves it is required to avoid conflicting microphone ownership.
- Commercial distribution of the upstream `hey_jarvis` model.

## Suggested implementation order

1. Audit current runtime state, F9 activation, microphone ownership, STT lifecycle, configuration, and diagnostics.
2. Define the canonical wake-word/provider contract and activation-source contract.
3. Implement `OpenWakeWordProvider` behind that contract.
4. Integrate provider lifecycle with PASSIVE/ACTIVE runtime state and unify F9 activation.
5. Add active-mode sleep phrases through the existing command/intent path if not already present.
6. Add automated tests, diagnostics, configuration documentation, license notice, and real microphone validation.

## Risk checklist

- Duplicate microphone ownership causes device contention.
- Echo/TTS output triggers "Hey Jarvis" accidentally.
- Threshold is too permissive or too strict in the real room.
- Detection emits several frames and causes repeated activation.
- Audio sample rate/format mismatch silently hurts recall.
- Provider lifecycle leaks microphone/process resources on sleep/wake/restart.
- F9 and voice activation diverge after future refactors.
- The pre-trained model license is accidentally treated as commercially redistributable.

## Future replacement path

Keep the provider interface stable enough that a later engine such as sherpa-onnx, a custom openWakeWord model, or another local KWS engine can be substituted without changing Jarvis runtime semantics.

The long-term invariant is not "Jarvis uses openWakeWord". The invariant is "Jarvis exposes a local wake-word capability that triggers the same canonical activation command as other activation sources."
