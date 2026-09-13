# JARVIS Voice Architectures — Implementation Handoff

This bundle converts the 11 September 2026 voice transcript and the subsequent architecture discussion into an implementation-ready task tree.

## Primary goal

Make JARVIS voice conversation reliable, natural, benchmarkable, and switchable between three architectures:

1. **Simple** — one realtime conversational model owns the immediate voice interaction.
2. **Front Brain** — a realtime/reflex conversational model plus a separate fast analysis/controller model (initial candidate: GPT-5.6 Luna).
3. **Duplex** — a full-duplex conversation frontend (initial target: GPT-Live 1) delegates reasoning/tools/tasks to the existing JARVIS backend.

GPT-Live is the principal expected production experiment, but the implementation must preserve Realtime Mini and Realtime Mini + Luna as first-class switchable modes so they can be benchmarked against one another.

## Where to start

Open `tasks/TODO.md`, then execute **Task 00**. The orchestrator must keep the TODO status current and only move to the next slice after validating the current slice.

## Key non-negotiables

- The realtime conversation path must remain responsive while backend work runs.
- Silence is a valid conversational action; do not emit reflex acknowledgements systematically.
- What was **actually spoken** is authoritative conversation state.
- Pending speech is not a FIFO that must always be played; stale speech can be cancelled or replaced.
- Every JARVIS-controlled initial prompt must be inspectable in Settings, with model-specific prompt layers visible when relevant.
- GPT-Live sessions are billable while active: active state, elapsed time, manual stop, auto-close policy, watchdogs, and orphan-session protection are mandatory.
- Provider-specific APIs must sit behind adapters; JARVIS Core must not depend directly on OpenAI Live/Realtime event names.
- Coding agents must use `/caveman` and `/coding-guideline` from `~/ai/skills/`.

## Source material

- `sources/transcript-2026-09-11.md` — exact uploaded voice-session transcript.
- `grill-session.md` — reconstructed architecture/design session covering the discussion after the transcript.
- `docs/10-openai-api-notes.md` — external API facts checked against current OpenAI documentation on 2026-09-11.

## Known current evidence

The source trace records long queued speech delays, backend blocking, voice improvisation replacing backend answers, false barge-ins caused by noise, and stalled speech output. These are not merely UX polish issues; they are architecture regression cases and must become tests.
