# Speech arbitration contract

## Purpose

Voice output has one business lifecycle even though evidence comes from several places: the speech scheduler, provider generations, local playback, Reflex output and user barge-in. The scheduler remains the runtime owner of that lifecycle. `jarvis.domain.speech_arbitration` defines the pure transition contract used to keep those paths consistent.

The most important boundary is deliberate: **stopping audible speech does not cancel Brain work**. A user barge-in terminates the current speech presentation with `user_barge_in`; the Brain turn/work remains independent and may continue producing a later answer.

## Stable identities

Each audible reservation has an `output_id`. Brain speech also carries `speech_id`; all owners may carry `correlation_id`. `SpeechOutputOwner` distinguishes Brain speech, surface Reflex output and direct conversation generation. Reusing an `output_id` with different identity is an error rather than a silent merge.

## Lifecycle

Allowed non-terminal progression is:

- `reserved -> generating`
- `generating -> playing`

Terminal transitions are explicit and require a stable business reason:

| Terminal state | Reasons |
| --- | --- |
| `completed` | `output_completed` |
| `interrupted` | `user_barge_in` |
| `cancelled` | `brain_superseded`, `reflex_preempted`, `voice_background`, `expired`, `start_cancelled` |
| `failed` | `start_failed`, `provider_error`, `output_stalled` |

A reservation can also be cancelled or fail before generation starts. Generation can complete without a `playing` transition when a backend does not expose a distinct first-playback callback.

Terminal states are immutable. Repeating the exact same terminal callback is idempotent; a contradictory terminal callback fails loudly. This prevents a late provider `completed` event from rewriting a prior `user_barge_in` into a successful completion.

## Provider evidence

Provider status is evidence, not lifecycle authority. `observe_provider_status()` records the raw status but never chooses a terminal business reason. Runtime code must classify the event through the scheduler's current ownership context before committing a terminal transition.

This separation matters for races such as:

1. local playback is cut immediately by user barge-in;
2. the provider receives cancellation asynchronously;
3. the provider may report `completed`, `cancelled`, or an already-finished cancellation error;
4. the lifecycle remains `interrupted / user_barge_in` because that is the business truth the user experienced.

## Brain-work separation

`SpeechLifecycle.affects_brain_work` is always `False`, and trace fields emit `brain_work_cancelled=false`. The speech arbiter has no API that can cancel Brain work. Cancellation of durable/background work belongs to the work/task owner, never to an audio or provider callback.

## Ownership boundary

- **SpeechScheduler**: commits lifecycle truth and business reasons.
- **Realtime bridge**: observes provider events, local playback and barge-in, then reports evidence to the scheduler.
- **Audio device**: proves local write/stop/playback cursor facts; it does not decide business lifecycle.
- **Provider**: reports generation status; it does not redefine terminal reason.
- **Core/Brain work owner**: owns durable work independently of speech presentation.

## Test requirements

`tests/unit/test_speech_arbitration.py` covers transition validity, terminal reason requirements, output identity reuse, user barge-in/Brain separation, provider-status neutrality, duplicate terminal callbacks and contradictory late callbacks. Any new terminal reason must extend both the reason/state map and tests before runtime integration.
