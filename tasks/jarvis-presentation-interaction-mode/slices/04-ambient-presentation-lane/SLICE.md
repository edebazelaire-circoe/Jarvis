# Slice 04 — Ambient Presentation context lane

## Goal

Feed live presentation speech into Presentation context while structurally preventing ambient speech from becoming an addressed command/turn.

## Context

Completed capture/session work already distinguishes the memory-only PRESENTATION ambient lane from explicit durable recording. This Slice integrates that lane with Presentation semantics.

## Canonical Concepts

Ambient lane, transcript segment, explicit address, authority classification, conversation event, capture privacy boundary.

## Scope

### In Scope

- Consume existing ambient transcript segments while PRESENTATION is active.
- Carry stable IDs/timestamps/freshness and an explicit non-authoritative classification.
- Keep ambient transcript out of canonical addressed conversation turns.
- Stop/ignore Presentation-only ambient interpretation promptly when mode exits.
- Provide deterministic replay/fake hooks for later tests.

### Out of Scope

- Persisting raw ambient PCM as a recording.
- Treating arbitrary room speech as a command.
- Long-term semantic memory.

## Dependencies

- `02-interaction-mode-contract`
- `01-contract-reconciliation`

## Implementation Steps

1. Reuse current ambient capture/transcription path.
2. Add/verify structural authority metadata.
3. Define bounded fresh-segment delivery to Presentation context.
4. Ensure explicit-address routing remains separate and higher priority.
5. Add privacy and authority regression tests.

## Files Likely Touched

Ambient lane, transcription event schema/adapters, Presentation context glue, tests, docs.

## Architecture Constraints

No implicit durable recording; no LLM-only prompt convention as the authority boundary.

## Automated Validation

Replay tests proving ambient monologue cannot dispatch addressed actions and mode exit stops Presentation consumption.

## Acceptance Criteria

Presentation receives fresh ambient context with provenance, while canonical conversation/action authority remains unchanged.

## Documentation Updates

Document ambient authority and privacy semantics.

## Handoff Notes

Coding/runtime Slice: load `/caveman` and `/coding-guideline`; add `agent-trace-analysis` because routing/authority behavior changes.
