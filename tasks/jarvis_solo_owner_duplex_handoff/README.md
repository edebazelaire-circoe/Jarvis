# JARVIS — Solo Owner Duplex + Core Work State Handoff

This folder is an implementation-ready handoff reconstructed from the design/grilling session of 2026-09-11 and the latest `main` branch review.

## Objective

Keep the strong duplex/audio work already merged on `main`, then add the two missing architectural pieces agreed during the session:

1. **Owner-aware audio gating**: in Solo Pro mode, speech/noise from other people must not interrupt JARVIS, become a user turn, refresh useful activity, or reach the brain. `NearEndDetector` remains a cheap acoustic prefilter; a local `SpeakerVerifier` becomes the authority for owner speech.
2. **Core-owned work visibility**: detailed agent/subtask state must not exist only in runtime/UI projections. Provider-specific trackers normalize observations into Core-owned work state so the brain and UI share the same source of truth.

The handoff deliberately does **not** replace the current AEC, turn-taking, semantic VAD, or contextual acknowledgement work unless tests prove it necessary.

## Baseline reviewed

Repository: `edebazelaire-circoe/Jarvis`

Latest reviewed `main` commit: `8fc7a117791f39eba70362cb2acd56ecbc8e44fa`

Key existing implementation to preserve:

- `jarvis/audio/duplex.py`: AEC-aware capture, near-end detection, echo guard, pre-roll.
- `jarvis/adapters/webrtc_echo.py`: WebRTC AEC3 through LiveKit.
- `jarvis/runtime/realtime_audio.py`: decoupled provider reader/playout/main loop, barge-in, local output stop, provider cancel/truncate.
- `jarvis/runtime/voice_stack.py`: `server_vad` / `semantic_vad`, noise reduction, AEC toggle, acknowledgement delay.
- `jarvis/runtime/turn_filters.py`: transcript/echo/noise defenses.
- `jarvis/runtime/agent_tasks.py`: detailed provider-specific subtask observation for UI/runtime.
- `jarvis/core/brain_service.py` + `BrainWorkingState`: Core-owned conversational/work truth, currently without the detailed runtime task projection.

## Start here

A fresh coding agent should open `tasks/TODO.md`, then execute **Task 00** first. Task 00 is the orchestration contract for the whole implementation.

All coding tasks require the skills:

- `/caveman`
- `/coding-guideline`

They are expected under `~/ai/skills/`.
