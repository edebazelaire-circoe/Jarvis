# Task 01 - Add Typed Brain and Speech Contracts

## Goal

Introduce the minimum provider-neutral domain and port contracts required for asynchronous brain work and speech requests, without changing runtime behavior yet.

## Context

Current V2 already has `ConversationTurn`, `Job`, and `ProtocolEnvelope`, plus a small `RealtimeSession` port. There is no typed brain turn/state/speech contract and the strong agent is still a Voice-specific Claude gateway.

## Scope

### In Scope

- Add typed `SpeechRequest` semantics and kind/priority metadata.
- Add typed input/result/event contracts required by `BrainBackend`.
- Add a safe structured brain state type or a minimal equivalent needed for Task 02.
- Add/extend provider-neutral ports for `BrainBackend` and semantic Realtime output control.
- Define validation invariants and serialization helpers/tests.

### Out of Scope

- Running a brain model.
- Changing Voice lifecycle.
- Adding protocol endpoints.
- Implementing Realtime provider JSON sends.

## Dependencies

Task 00.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline` from `~/ai/skills/`.
2. Inspect `jarvis/domain/v2.py` and `jarvis/ports/v2.py` conventions.
3. Add the smallest typed contracts consistent with `docs/02-architecture-spec.md`.
4. Ensure public state has no hidden reasoning/scratchpad field.
5. Ensure speech requests carry conversation/correlation ids and enough data for priority, supersession, and interruption.
6. Extend `RealtimeSession` only with semantic methods required later; do not add OpenAI-specific parameters.
7. Add unit tests for invalid/valid contract construction and serialization.

## Files Likely Touched

- `jarvis/domain/v2.py`
- `jarvis/ports/v2.py`
- focused domain/port tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Domain/port unit tests.
- Existing V2 domain tests.
- Architecture/import tests if present.

## Acceptance Criteria

- Core can refer to a strong `BrainBackend` without provider imports.
- A `SpeechRequest` can be represented and serialized with provenance, priority, supersession, and correlation metadata.
- Structured brain state contains no raw chain-of-thought field.
- No runtime behavior changes yet.

## Handoff Notes

Keep the contracts intentionally small. If a field is only useful to OpenAI Realtime, it belongs in the adapter, not the domain model.
