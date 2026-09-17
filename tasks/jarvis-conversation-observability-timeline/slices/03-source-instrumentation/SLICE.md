# Slice 03 — Instrument User, Brain, Mouth, tools and sub-agents at source

## Goal

Emit canonical events exactly where authoritative state changes occur, while preserving existing diagnostic telemetry.

## Context

Jarvis already emits many `voice.*`/`core.*` journal events and agent task traces. This Slice adds functional conversation events, not an LLM summary and not a blind conversion of all trace lines.

## Canonical Concepts

- accepted user transcript
- Brain externally visible messages/speech requests/status events
- Mouth/reflex speech lifecycle
- sub-agent task start/end/error spans
- selected tool spans where useful
- trace correlation

## Scope

### In Scope

- Emit canonical events from authoritative producers.
- Use consistent correlation IDs and timestamps.
- Dual-write diagnostic RuntimeJournal events where already useful.
- Ensure failure paths emit terminal/partial events when possible.

### Out of Scope

- Speech arbitration policy changes.
- Persisting raw model private reasoning.

## Dependencies

01, 02

## Implementation Steps

1. Map current producers and IDs before coding.
2. Instrument user input acceptance before downstream model work.
3. Instrument Brain public output/request lifecycle.
4. Instrument Mouth/reflex queued/started/completed/interrupted/superseded states.
5. Instrument agent task spans and selected tool spans with task/trace IDs.
6. Add failure/crash-oriented integration fixtures.

## Files Likely Touched

- `jarvis/runtime/realtime_audio.py`
- `jarvis/runtime/speech_scheduler.py`
- `jarvis/runtime/agent_tasks.py`
- `jarvis/core/*`
- `jarvis/runtime/journal.py (only adapters/linkage if needed)`
- `tests/integration/*`

## Architecture Constraints

- Instrumentation must not change business decisions or speech timing materially.
- No model call may be added solely to make a transcript.

## Automated Validation

- Producer-level unit tests.
- Integration test reconstructing a multi-actor conversation.
- Agent-trace analysis proving IDs join correctly.

## Acceptance Criteria

- A crash after a user turn still leaves the accepted user event and all already-authoritative downstream events.
- Interrupted/superseded speech is distinguishable from completed speech.
- Sub-agent duration is reconstructable from events.

## Documentation Updates

Update event-emitter reference tables and producer ownership docs.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
