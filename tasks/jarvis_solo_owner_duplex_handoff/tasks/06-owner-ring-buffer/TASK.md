# Task 06 — Add longer owner-verification ring buffer and provider-advisory flow

## Goal

Preserve the beginning of the owner’s sentence despite identity-verification latency, without duplicating audio sent to Realtime.

## Context

Current pre-roll is short and optimized for acoustic near-end confirmation. Owner verification may intentionally take longer.

## Scope
### In Scope
- Add separate configurable owner-verification ring buffer, starting around 2500 ms.
- Replay only frames that provider has not already received.
- Bounded memory and exact ordering.
- Provider `speech_started` becomes a correlation/segmentation signal after local owner authorization.

### Out of Scope
- semantic VAD redesign.

## Dependencies

Task 05.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Separate acoustic pre-roll semantics from owner-verification history if current structure conflates them.
2. Track sent/not-sent frame state robustly.
3. On owner confirmation, flush unsent prefix exactly once then stream live frames.
4. Bound/reset buffer on session lifecycle and format changes.
5. Add timing metadata for owner onset estimate vs confirmation vs local stop.

## Files Likely Touched

- `jarvis/audio/duplex.py`
- bridge/audio tests
- config

## Architecture Constraints

- memory-only audio buffer;
- never persist PCM;
- no duplicate stream frames;
- do not break AEC reference ordering.

## Testing Requirements

- 0.5/1/2+ second verification delays;
- buffer wrap;
- owner starts while non-owner already present;
- no duplicate prefix;
- session reset;
- multiple sample rates if supported.

## Acceptance Criteria

- First owner syllables survive realistic verifier latency.
- No audio duplication reaches provider.

## Documentation Updates

Document memory bound and setting.

## Handoff Notes

Hardware acceptance decides final default duration.
