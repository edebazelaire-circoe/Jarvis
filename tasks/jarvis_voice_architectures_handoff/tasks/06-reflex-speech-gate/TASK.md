# Task 06 — Implement reflex speech gate and WAIT/preamble policy

## Goal

Replace automatic reflex acknowledgements with a deliberate low-latency decision that can legitimately remain silent.

## Context

The observed reflex phrases were repetitive and sometimes nonsensical. The desired behavior is not a better canned acknowledgement list; it is a gate deciding whether anything should be said while deeper work proceeds.

For this coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.

## Scope
### In Scope
- Introduce explicit gate actions `WAIT`, `BACKCHANNEL`, `SPEAK`, `PREAMBLE`, `DELEGATE` or equivalent.
- Make `WAIT` a successful normal outcome.
- Avoid acknowledgement for short confirmations, corrections, declines, user thinking aloud, likely background speech/noise, and direct answers expected immediately.
- Allow one short natural preamble only when noticeable work/delegation would otherwise create awkward silence.
- Prevent reflex layer from asserting facts/results it has not verified.
- Ensure backend/front result supersedes a pending reflex phrase when it arrives first.

### Out of Scope
- Full semantic chunk scheduler.
- VAD tuning.
- Luna sidecar.

## Dependencies
- Task 05 Realtime adapter and Task 04 state.

## Implementation Steps
- 1. Extract current acknowledgement triggers and prompts.
- 2. Implement a testable gate policy independent of audio provider.
- 3. Add a no-op/wait path that emits no speech item.
- 4. Constrain backchannels to very short non-claiming conversational signals.
- 5. Suppress preamble if useful content becomes ready before preamble starts.
- 6. Instrument gate decision, reason, and latency.

## Files Likely Touched
- Reflex/preamble policy module
- Voice prompt/config layers
- Conversation controller
- Policy tests

## Architecture Constraints
- Silence is preferable to filler.
- Do not create a fixed phrase on every user turn.
- No reflex statement may claim an action completed unless Core state confirms it.

## Testing Requirements
- User says `OK` -> normally WAIT.
- User says `non c est bon` -> no acknowledgement unless context requires one.
- User says `attends je reflechis` -> WAIT, not `take your time`.
- Fast direct answer arrives -> no preamble.
- Long backend lookup -> at most one short natural preamble.
- Likely noise/side conversation -> WAIT.

## Acceptance Criteria
- Automatic acknowledgement rate drops substantially in replay fixtures without increasing dead-air failures on genuinely long work.
- No test produces generic `I understand your request` behavior by default.

## Documentation Updates
- Update docs/05-reflex-optimization.md with implemented gate rules and tunables.

## Handoff Notes

Provider-native no-op/wait tools may be used when available, but the JARVIS-level gate remains provider-neutral.
