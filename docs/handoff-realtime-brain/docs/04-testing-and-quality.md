# 04 - Testing and Quality

## Test philosophy

The architecture must be testable without a microphone, without OpenAI, and without Claude. Hardware/provider acceptance is a separate layer, not a replacement for deterministic tests.

## Architecture gates

Add or preserve tests that enforce:

- `jarvis/core` does not import OpenAI transport/audio implementation types;
- brain provider details live behind `BrainBackend`;
- Realtime provider JSON remains inside the adapter/runtime boundary;
- Voice can be muted without stopping Core or cancelling jobs;
- no raw chain-of-thought field is introduced in persisted domain state.

## Contract tests

### Brain turn ingress

Verify:

- completed user turn is persisted exactly once;
- duplicate provider item/correlation ids are idempotent;
- endpoint returns before long fake brain work completes;
- accepted event carries conversation/correlation identifiers;
- background brain work survives Voice disconnect.

### Speech events

Verify:

- `brain.speech.requested` serializes through `/v1/events`;
- stale/superseded requests are not spoken;
- final results replace obsolete progress;
- question priority preempts low-value progress;
- assistant turn provenance is persisted.

### Realtime adapter

Use fake WebSockets to verify exact provider messages for:

- transcript delta mapping;
- completed transcript mapping;
- response/output id mapping;
- faithful brain speech request;
- output cancel;
- conversation truncate with playback duration/cursor;
- provider error normalization.

## Continuous LIVE tests

Replace/update current tests that assume one response returns to BACKGROUND.

Required scenarios:

1. Wake once, user turn, assistant response, state remains ACTIVE.
2. Second user turn occurs in the same Realtime session.
3. `Jarvis Mute` returns to BACKGROUND immediately.
4. Useful inactivity returns to BACKGROUND.
5. Ambient transcript/noise does not reset useful-activity timeout.
6. A running Core job remains running after mute.
7. Re-activation creates/attaches voice transport without losing conversation/work context.

## Interruption tests

With fake audio and fake Realtime session:

- user speech start during playback stops output promptly;
- cancel/truncate is issued with the correct active output identifier;
- interrupted speech request is marked as interrupted;
- new completed user turn is sent to brain;
- active job is not automatically cancelled;
- brain revision can explicitly cancel a job;
- queued stale progress is dropped after revision.

## Concurrency tests

Focus on races that are likely in this architecture:

- mute while brain speech is queued;
- mute while Realtime output is being written;
- user speech starts at the same time a brain result arrives;
- Core event stream reconnects after a short disconnect;
- duplicate progress events;
- brain completes after Voice has gone BACKGROUND;
- Voice reactivates and must not replay expired progress.

## Privacy tests

Existing Jarvis privacy stance should continue:

- no raw audio persisted;
- transcript/prompt body not logged by default;
- brain diagnostics use ids, timing, event types, and sizes rather than message content unless explicitly configured;
- no hidden reasoning is logged or persisted.

## Latency telemetry

Record timings without requiring transcript content:

- `speech_started -> surface_first_audio`;
- `transcript_completed -> brain_turn_accepted`;
- `brain_speech_requested -> first_brain_audio`;
- `user_interrupt_detected -> local_output_stopped`;
- `brain_work_started -> first_public_progress`;
- `brain_work_started -> completed`.

Use correlation ids and speech/work ids so traces can be joined.

## Workstation acceptance

Automated tests cannot prove acoustic behavior. Run manual acceptance on the intended Windows workstation with:

- headphones;
- normal speakers;
- keyboard noise;
- background speech;
- user interruption while Jarvis speaks;
- a long brain job while the user continues talking;
- `Jarvis Mute` while a job is active;
- wake again after a job has completed.

Record whether speaker-to-mic echo retriggers VAD. If it does, keep/favor the documented fallback mode rather than masking the result.

## Regression gate

Before removing legacy mode, run:

- full unit suite with warnings elevated as the repository currently expects;
- release verification script if still present/current;
- new continuous-brain integration tests;
- at least one opt-in live OpenAI smoke test;
- target workstation voice acceptance.
