# Reconstructed Grill Session

> This is a reconstructed grill session based on available conversation context. It preserves the decisions and corrections that materially affect implementation. It is not a verbatim transcript.

## 1. Starting need: fluid voice + asynchronous brain

The user wants JARVIS to feel conversationally fluid while keeping long work out of the realtime voice surface. The desired interaction is:

- user speaks naturally;
- surface can acknowledge quickly when useful;
- strong brain works asynchronously;
- progress/result/failure can later surface orally or visually;
- multiple work streams can remain active;
- `Jarvis Mute` stops voice streaming but never cancels Core work;
- background mode may remain visually/event-active without constantly speaking.

A key architectural principle was established: **Realtime is mouth/ears/reflexes; Core owns truth, intent, work state, and the strong brain.**

## 2. VAD, semantic VAD, diarization, speaker verification

The discussion separated four problems:

- VAD: is there human speech?
- turn detection: has the user finished the thought? `server_vad` uses silence; `semantic_vad` uses semantic completion.
- diarization: distinguish speaker A/B/C.
- speaker verification: determine whether the speaker is the enrolled owner.

Diarization alone is not sufficient for Solo Pro. It can separate speakers without knowing which one is the owner.

## 3. Echo and interruption

The user emphasized that JARVIS must hear interruptions while speaking through laptop speakers. The design concluded that this is primarily an acoustic/audio problem, not a language-model problem.

AEC (Acoustic Echo Cancellation) should use the exact rendered JARVIS audio as far-end reference and remove it from microphone capture. The voice model should not be asked to infer whether a transcript is its own echo.

Interruption should stop local playback first; provider cancellation/truncation follows afterward. Network round-trips must not be on the critical path of physically stopping the speaker.

## 4. Background and Solo Pro semantics

The user wants a personal working mode first:

- wake/background is distinct from active conversation;
- background audio should not be streamed continuously to Realtime;
- wake word can activate a conversation;
- once active, the user may continue without repeating “Jarvis” on every sentence;
- after useful inactivity JARVIS can return to background;
- background conversations, keyboard noise, and other people speaking must not keep the session alive.

Initially, a speculative “duck volume on any near-end voice” idea was proposed. The user rejected it because continuous office conversation would repeatedly attenuate JARVIS and could create bad state interactions.

**Correction locked:** in Solo Pro, do not audibly react to arbitrary near-end speech. Local owner recognition may take a short amount of time; correctness is preferred over an instant but noisy interruption.

## 5. Owner-aware barge-in

Locked target:

- AEC cleans capture.
- Cheap local acoustic detector finds near-end speech candidates.
- Speaker verification runs continuously/sliding on those candidates.
- Only confirmed owner speech is allowed to trigger barge-in in Solo Pro.
- Non-owner speech does not create a durable “ignored segment”; verification continues on rolling windows so the owner can still be detected while another person is speaking.
- Preserve enough pre-roll/ring-buffer audio that the beginning of the owner’s sentence is not lost while identity is being confirmed.
- Provider `speech_started` remains useful for segmentation/diagnostics but is not the final authority for local barge-in in Solo Pro.

## 6. Technology discussion

Picovoice technologies were discussed conceptually:

- Porcupine: wake word.
- Cobra: VAD.
- Eagle: speaker recognition.

The user prioritizes **quality** over licensing convenience, but does not want commercial-sales friction unless there is a meaningful quality benefit. The target architecture therefore must be provider-swappable and benchmark-driven rather than hardwired to Picovoice or one open-source stack.

Candidate baselines discussed included WebRTC AEC, Silero VAD, sherpa-onnx, SpeechBrain, openWakeWord, Vivoka, Sensory, and Picovoice. No final vendor choice was locked.

## 7. Review of latest `main`

Latest reviewed commit: `8fc7a117791f39eba70362cb2acd56ecbc8e44fa`.

The agent had already implemented many desired fixes without receiving the later precise design:

- WebRTC AEC3 through LiveKit.
- Near-end detector and echo guard.
- local pre-roll.
- reader/playout separation so provider events are not blocked by queued audio.
- two-step barge-in: near-end causes duck, provider `speech_started` confirms cut.
- transcript filters.
- engagement window.
- provider no longer auto-responds to each VAD segment in continuous mode.
- far-field noise reduction and French transcription.
- contextual acknowledgement after a delay.
- `server_vad` and `semantic_vad` exposed in Control Center.

The review concluded that most of this should be kept.

## 8. Main delta after comparison

The current `NearEndDetector` distinguishes “JARVIS echo” from “some near-end source”; it does not identify the owner. Therefore its current authority is too high for Solo Pro.

Locked hybrid:

1. Keep AEC3.
2. Keep the current near-end detector as an inexpensive candidate prefilter.
3. Add a typed, swappable local `SpeakerVerifier`.
4. In Solo Pro, remove duck/cut authority from raw near-end events.
5. Only owner-confirmed speech may interrupt JARVIS or be routed as an active user turn.
6. Increase configurable pre-roll/ring-buffer capacity from the current short interruption-oriented window toward roughly 2–3 seconds, subject to measurement.
7. Treat provider `speech_started` as advisory/segmentation evidence after local owner confirmation.
8. Non-owner speech must not reach the brain or refresh useful activity in Solo Pro.
9. Preserve current addressing semantics for **owner speech**: owner speech may still be `addressed` or `uncertain`; identity and addressing are separate decisions.

## 9. Work/task visibility issue

Recent pushes also introduced `AgentTaskTracker` and rich task/subagent visualization. The user explicitly requires that this information not be UI-only.

Locked principle:

```text
provider-specific task streams
        -> normalizer/tracker
        -> Core-owned work state
             -> Brain
             -> UI
             -> speech/notification policy
```

The UI is a projection, never a source of truth. If task progress, elapsed time, failure, or state transitions are visible in the UI but invisible to the brain, the architecture is incomplete.

## 10. Quality strategy

No provider should win by assumption. The implementation should support A/B benchmarking on the same microphone/audio conditions.

Measure at least:

- false owner detections during background office speech;
- missed owner interruptions;
- owner verification latency;
- owner + competing speaker overlap;
- false wakeups;
- AEC self-echo false interruptions;
- CPU / memory / model load time;
- beginning-of-sentence preservation after delayed owner verification;
- end-to-end barge-in stop latency;
- behavior when verifier/AEC are unavailable.

## Final validated direction

The user explicitly validated the hybrid architecture and requested an implementation dossier using Grill to Tasks.
