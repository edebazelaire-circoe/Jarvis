# 01 — Decision Log

## Locked decisions

### D01 — Preserve Core ownership of truth and work
Realtime remains mouth/ears/reflexes. Core remains authoritative for user intent, long-running work, and brain state.

### D02 — Preserve current AEC3 implementation
The WebRTC AEC3 path introduced on `main` is the baseline. Do not replace it without measured failure.

### D03 — Preserve `NearEndDetector`, reduce its authority
`NearEndDetector` remains a low-cost acoustic candidate detector. It must not mean “authorized user”.

### D04 — No speculative duck on arbitrary speech in Solo Pro
The current behavior that lowers JARVIS volume as soon as generic near-end speech appears is not the target for Solo Pro.

Rationale: continuous office speech would cause repeated ducking and poor conversational stability.

### D05 — Speaker verification is the authority for owner speech
A local, streaming/sliding `SpeakerVerifier` decides whether a candidate contains the enrolled owner.

### D06 — No monolithic “ignored speaker segment”
Non-owner speech is not used to lock out a whole VAD segment. Verification continues on rolling windows so owner speech can be detected while another speaker is active.

### D07 — Owner verification may add latency
Correctness is preferred to an instant false interruption. A sub-second-to-low-seconds identity confirmation is acceptable if the sentence start is preserved.

### D08 — Use a ring buffer to preserve sentence start
Keep enough local audio in RAM to replay the pre-verification prefix after owner confirmation. Target range for initial experiments: approximately 2–3 s, configurable.

### D09 — Provider speech start is advisory in Solo Pro barge-in
Once local owner speech is confirmed, stop local playback without waiting for a provider round-trip. Provider VAD remains useful for turn segmentation and diagnostics.

### D10 — Identity and addressing are separate
After owner verification, the existing addressing classifier may still decide `addressed` vs `uncertain`. Non-owner speech is dropped before that layer in Solo Pro.

### D11 — Non-owner speech is not useful activity
In Solo Pro it must not refresh the active-session timeout, create brain turns, acknowledgements, or work.

### D12 — Provider choice remains benchmark-driven
Do not hardwire Eagle, sherpa-onnx, Vivoka, Sensory, etc. Define a stable port and compare engines on the same captured scenarios.

### D13 — Current semantic VAD work stays
Keep `server_vad` / `semantic_vad` configuration and benchmark the setting; do not reopen this implementation unless measurements show a regression.

### D14 — Current contextual acknowledgement work stays
Keep delayed contextual acknowledgement behavior; acknowledgements must never speak over the user and must remain truth-bounded.

### D15 — UI is not the source of task truth
`AgentTaskTracker` remains a provider-specific observer, but normalized state must flow into Core.

### D16 — Brain and UI share Core work state
The brain must have access to the same normalized task/work information the UI projects: status, start/elapsed information, current activity, model/provider when known, completion/failure, and stable identifiers.

### D17 — Work state changes can wake cognition, not necessarily speech
A failure/blocker/state change should become visible to the brain/event policy. Speech is a separate policy decision; not every state revision is narrated.

## Explicitly open

- Final default `SpeakerVerifier` engine.
- Exact owner-confidence threshold and required evidence window.
- Exact ring-buffer duration after hardware measurement.
- Whether owner voice profiles are encrypted at rest; define after storage format is chosen.
- Which commercial engine, if any, is worth licensing after benchmarks.
- Future multi-user/room-assistant permission model.
