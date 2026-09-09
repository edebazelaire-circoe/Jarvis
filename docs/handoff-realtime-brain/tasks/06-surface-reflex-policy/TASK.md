# Task 06 - Enforce Strict Realtime Reflex Policy

## Goal

Constrain the fast Realtime surface so it can keep conversation fluid without becoming a second source of operational truth.

## Context

The target rule is: Realtime has reflexes; the brain owns truth and intent. The existing prompt currently asks Realtime to call `claude_task` for substantive machine/project work and then narrate the final result.

## Scope

### In Scope

- Rewrite surface operating rules for async-brain mode.
- Define allowed acknowledgement/hearing-repair behavior.
- Forbid unverified progress/result/success claims.
- Add provenance metadata for surface-generated assistant turns.
- Keep surface model configurable; optionally set/test `gpt-realtime-2.1-mini` as recommended config rather than a business constant.
- Add policy-oriented tests where practical.

### Out of Scope

- Moving Claude to Core (next task).
- Brain speech scheduling.
- General persona redesign.

## Dependencies

Tasks 04 and 05.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Separate stable persona from operating rules if useful.
3. Add an async-brain surface rule set that permits only brief reflexes until brain speech is supplied.
4. Ensure task/tool progress claims are prohibited unless injected from brain output.
5. Mark persisted surface assistant transcripts with `source=surface.reflex` or equivalent provenance.
6. Keep legacy prompt behavior available only in legacy architecture mode during rollout.
7. Add deterministic tests for instruction construction and provenance.

## Files Likely Touched

- `jarvis/adapters/openai_realtime.py`
- `jarvis/runtime/realtime_audio.py`
- `jarvis/v2_config.py`
- prompt/config tests


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- Prompt construction test contains strict truth/progress boundary.
- Legacy vs continuous-brain rule sets are intentionally distinct.
- Surface assistant transcript persistence includes provenance.
- Model override remains configurable.

## Acceptance Criteria

- Realtime can acknowledge immediately without being authorized to invent task state.
- Operational truth is reserved for brain-provided speech.
- No hard-coded provider model enters Core/domain code.

## Handoff Notes

If free-form surface acknowledgements are not reliably bounded, replace them with deterministic short acknowledgements rather than weakening the truth boundary.
