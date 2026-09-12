# Task 05 - Introduce Continuous LIVE Lifecycle

## Goal

Allow one ACTIVE Realtime session to span multiple conversational turns while preserving `Jarvis Mute`, useful inactivity, error cleanup, and a reversible legacy mode.

## Context

Current `PersistentVoiceRuntime.activate()` passes `on_response_done=self.mute`, and auto-turn closes microphone input when Realtime commits one turn. Existing tests intentionally assert return to BACKGROUND after one response.

## Scope

### In Scope

- Add a compatibility/architecture mode for legacy vs continuous behavior.
- In continuous mode, decouple response completion from `mute()`.
- Keep/reopen microphone input across multiple VAD turns safely.
- Keep lifecycle ACTIVE until explicit mute/timeout/failure.
- Preserve useful-activity classification so ambient noise does not reset timeout.
- Keep visual projections coherent even when listening and brain work overlap.

### Out of Scope

- Strong brain migration.
- Full barge-in truncate logic (Task 09).
- Multi-agent work.
- Claiming echo cancellation.

## Dependencies

Task 04.

## Implementation Steps

1. Load `/caveman` and `/coding-guideline`.
2. Add one coarse rollout mode, e.g. `JARVIS_VOICE_ARCH=legacy|continuous_brain`, or an equivalent existing-config fit.
3. Change response-done callback wiring so continuous mode returns to listening projection rather than BACKGROUND.
4. Refactor input-pump lifecycle so server VAD can commit more than one user turn per ACTIVE session.
5. Preserve `Jarvis Mute` handling and wakeword suspend/resume semantics.
6. Preserve timeout behavior: addressed interaction is useful; ambient activity is not.
7. Update tests that currently assume one response ends the session; keep legacy-mode coverage where useful.
8. Add two-turn-in-one-session test.

## Files Likely Touched

- `jarvis/runtime/voice_v2.py`
- `jarvis/runtime/realtime_audio.py`
- `jarvis/v2_config.py`
- `tests/unit/test_v2_voice_toggle.py`


## Architecture Constraints

- Preserve provider-neutral Core boundaries; no OpenAI/Claude/aiohttp/audio provider types inside Core business contracts.
- Reuse existing Jarvis V2 services and `ProtocolEnvelope` rather than creating parallel infrastructure.
- Keep Voice lifetime independent from Core job/brain lifetime.
- Do not persist or expose raw chain-of-thought.
- Add comments/docstrings for concurrency and ownership invariants, not obvious line-by-line narration.

## Documentation Updates

Update task-local handoff notes and code-level docstrings/comments required to make ownership and concurrency clear. Do not perform broad repository documentation rewrites before Task 12 unless a public contract changed and would otherwise be misleading.

## Testing Requirements

- One wake -> two complete turns -> still ACTIVE.
- `Jarvis Mute` -> BACKGROUND.
- useful timeout -> BACKGROUND.
- ambient transcript/noise does not reset timeout.
- legacy mode preserves old behavior until retirement.
- audio teardown tests remain race-safe.

## Acceptance Criteria

- Continuous mode no longer equates `response.done` with mute.
- Multiple user turns can use one Realtime session.
- Core remains alive across Voice mute.
- No test claims speaker echo behavior is solved.

## Handoff Notes

The current audio code contains hard-earned PortAudio shutdown safety. Preserve its locking/teardown invariants while changing capture lifetime.
