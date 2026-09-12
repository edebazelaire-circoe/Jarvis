# 00 — Overview

## Goal

Evolve the current continuous voice path into a robust **Solo Owner** experience without discarding the substantial duplex work already on `main`.

The second track makes detailed agent/subtask state first-class Core data rather than a runtime/UI-only projection.

## Mental model

### Voice

```text
Microphone
   -> AEC / noise cleanup
   -> NearEndDetector (cheap acoustic candidate)
   -> SpeakerVerifier (owner authority)
   -> conversation gate
   -> Realtime stream / turn detection
   -> Core brain
```

When JARVIS is speaking:

```text
owner-confirmed speech
   -> local stop immediately
   -> provider cancel/truncate asynchronously
```

Provider VAD helps delimit turns, but does not decide whether an arbitrary nearby speaker is allowed to interrupt Solo Pro.

### Work state

```text
Claude/Codex/jobs/provider streams
   -> provider-specific observer
   -> normalized work observation
   -> Core WorkStateStore
       -> Brain context
       -> UI projection
       -> speech/notification policy
```

## In scope

- `solo_owner` conversation mode semantics.
- typed speaker-verification port and provider adapters.
- shadow-mode verification before enforcement.
- owner-aware barge-in and owner-aware input gating.
- configurable longer local audio ring buffer.
- diagnostics and acceptance metrics.
- normalized Core-owned detailed work state.
- brain access to current work snapshots.
- UI migration to Core work projection while preserving compatibility during rollout.

## Non-goals

- solving arbitrary-room multi-user authorization now;
- replacing the strong brain architecture;
- rewriting AEC3 from scratch;
- replacing Realtime providers purely for taste;
- forcing a Picovoice/Vivoka/Sensory contract before a benchmark;
- making the UI authoritative;
- allowing Realtime surface tools in `continuous_brain`.

## Quality priority

The user prioritizes measured quality over license convenience. Commercial engines are acceptable if they show a meaningful advantage, but the architecture must allow an open/local baseline to be used immediately.
