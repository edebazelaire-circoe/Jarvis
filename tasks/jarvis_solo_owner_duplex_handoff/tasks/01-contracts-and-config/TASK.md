# Task 01 — Freeze Solo Owner contracts and configuration

## Goal

Define the semantic mode and typed configuration/contracts needed for owner verification without changing current runtime behavior.

## Context

`legacy` vs `continuous_brain` describes voice architecture. A separate concept is needed for who may constitute user speech. The target first mode is `solo_owner`.

## Scope
### In Scope
- Add an explicit conversation/input authorization mode (`solo_owner` plus current/open behavior).
- Add settings for speaker verification mode (`off`, `shadow`, `enforce`) or equivalent.
- Add bounded configurable owner pre-roll target, initial default around 2500 ms.
- Define validation for missing/invalid Solo Owner requirements.
- Keep settings provider-neutral.

### Out of Scope
- Real speaker recognition.
- Changing barge-in behavior.

## Dependencies

Task 00.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Inspect existing settings/config parsing and `voice_stack.py` conventions.
2. Add domain/config enums/typed values with backward-compatible defaults preserving current behavior.
3. Do not overload `voice_arch` or VAD type.
4. Add parsing/serialization and Control Center API validation contracts, but defer visible UI controls to Task 08 if that keeps the slice smaller.
5. Add tests for valid, invalid, omitted, and incompatible settings.

## Files Likely Touched

- `jarvis/v2_config.py`
- `jarvis/domain/v2.py` or a dedicated audio domain module
- `jarvis/runtime/voice_stack.py`
- settings endpoint tests

## Architecture Constraints

- Semantic mode separate from provider and voice architecture.
- Default must preserve current behavior.
- No vendor names in domain contracts.

## Testing Requirements

- config parse round-trip;
- old settings files remain valid;
- invalid buffer duration/verification mode rejected clearly;
- no behavior change when mode is absent.

## Acceptance Criteria

- `solo_owner` is representable and persisted.
- verification `off/shadow/enforce` is representable.
- pre-roll duration is bounded/configurable.
- existing voice tests remain green.

## Documentation Updates

Update OPERATIONS/settings docs with the new semantic distinction.

## Handoff Notes

Names may be adapted to existing project vocabulary, but preserve the separation of concerns.
