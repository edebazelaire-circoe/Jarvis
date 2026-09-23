# Slice 05 - Implementation report

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Scope | The shared-capture seam and the explicit-address lane. **No ambient transcription** (Slice 06), **no priority addressed turn** (Slice 10), **no composition-root wiring** (section 7). |
| Canonical doc | `docs/presentation-audio-capture.md` (new), linked from `docs/ARCHITECTURE.md` and `docs/interaction-mode.md` |
| New suite | `tests/unit/test_presentation_audio_capture.py` - **70 passed** |
| Mutations | 16 run, **16 caught**. Two survived the first round and both were real gaps (section 8) |

---

## 1. The ownership model, and exactly where the single stream lives

The microphone is single-consumer today and three things want it. This slice
does not fix that globally. It makes **PRESENTATION** single-owner and leaves
SIMPLE exactly as it was - the option SLICE.md and
`docs/03-implementation-strategy.md` both offer, and which D14 makes the safer
one.

```text
                          +--> inline sink  -> SoundDeviceRealtimeAudio
                          |    (capture thread, CaptureProcessor / AEC / guard)
sd.RawInputStream --> AudioCaptureHub --+
 ^ the ONE stream         |    +--> queued  -> SharedPcmWakeWordBackend  (16 kHz)
 jarvis/audio/            |    +--> queued  -> ambient segmentation (Slice 06)
   capture_hub.py         |
   AudioCaptureHub.open() +--> PreRollRing  (memory only, bounded)
```

**The single stream is created in exactly one place**: `AudioCaptureHub.open()`
-> `sounddevice_input_stream(...)` -> `sd.RawInputStream(...)`, in
`jarvis/audio/capture_hub.py`. The factory is injected, so the suite never
touches a real device.

Everything else stops opening one.

- `SoundDeviceRealtimeAudio` gained **one optional parameter**, `input_source`.
  When present, `open_streams()` calls it with the *same* PortAudio-shaped
  callback instead of constructing `sd.RawInputStream`. The handle it returns is
  a `CaptureSubscription`, which answers `start()` / `stop(ignore_errors=)` /
  `close(ignore_errors=)` - so `stop_input()`, `_close_owned()`, `_shutdown()`
  and `_shutdown_stream()` needed **zero** new branches. The echo guard, the
  send queue, the playback cursor and the whole close protocol are untouched.
- `SharedPcmWakeWordBackend` (`jarvis/adapters/wakeword_shared_pcm.py`) replaces
  Porcupine's own stream with a hub subscription. `opens_input_stream` is a
  property returning `False`, and a test counts it.

### The invariant is counted, not asserted in prose

`jarvis/audio/input_ownership.py` is a process-wide registry of live physical
input streams. Three registrants, deliberately including the one we are *not*
changing:

| Registrant | Owner label |
| --- | --- |
| `SoundDeviceRealtimeAudio` (no `input_source`) | `realtime_audio` |
| `AudioCaptureHub` | `audio_capture_hub` |
| `PorcupineWakeWordBackend` | `wakeword_porcupine` |

`open_input_stream_count()` answers "how many microphones are open right now".
Registering Porcupine is the point: SIMPLE's two owners become a **measured
fact** rather than an unstated one, so
`test_simple_keeps_its_own_input_stream_and_its_two_owners` asserts 2 and
`test_presentation_holds_exactly_one_physical_input_owner_and_the_count_says_so`
asserts 1 *while an interactive turn is open*.

The registry also **enforces**, not only observes.
`PresentationAudioSession.start()` refuses before opening if any owner exists
(`presentation_second_microphone_owner`, and `device.opens == 0` is asserted),
and refuses again after opening - giving the device back - if the count is not
exactly 1 (`presentation_input_owner_ambiguous`). Both are
`PresentationAudioError`, both leave zero owners, both write an `error` line.

Release is **total** and now sits in a `finally`: even a `close()` that raises
frees the registry slot. Argued trade-off, written at the call site - a phantom
owner would block PRESENTATION forever, while a device genuinely still held
announces itself at the next open as `capture_device_busy`.

---

## 2. Backpressure policy, and why

Two subscription shapes, and the difference is structural rather than a flag.

- **inline** (`sink=`): called on the PortAudio thread, on the raw block. The
  interactive path needs this because `CaptureProcessor` does echo cancellation
  and the echo guard *in that thread* (`jarvis/audio/duplex.py`) and the
  reference alignment depends on it. An inline subscriber may **not** ask for
  another sample rate - resampling has no business on the audio thread - and the
  refusal is a typed `capture_subscription_rate_mismatch`, not a silent ignore.
- **queued** (default): bounded per-subscriber `deque`, drained on the loop by
  `blocks()`. Resampling, if requested, happens there and only there.

**Policy: bounded, never blocking, always counted.** Default `DROP_OLDEST` - the
same rule `SoundDeviceRealtimeAudio._put_input` already applies. A consumer that
has fallen behind wants the *present*; a backlog served later as if it were
fresh is the staleness D06 exists to prevent. `DROP_NEWEST` exists for a
subscriber whose continuity matters more than its freshness.
`MAX_SUBSCRIBER_BLOCKS` (128) is a hard ceiling clamped inside `subscribe()`;
`DEFAULT_SUBSCRIBER_BLOCKS` is 32 (1.6 s at 50 ms blocks). Every drop increments
`CaptureSubscription.dropped`.

### The latch decision, made deliberately

`CaptureProcessor.observer` **detaches permanently on the first exception**.
That is right *there*: the observer is one optional speaker check, and losing it
degrades a side feature without touching the microphone.

**I did not keep that behaviour per-subscriber, and here is why.** A hub
subscriber is a *lane* - the interactive path, or the wake detector. Detaching
the wake detector for good on one transient exception would kill the wake word
for the rest of the session, silently, with no recovery path, which directly
contradicts `docs/03-implementation-strategy.md`: "Wake detector failure must
surface clearly and leave manual key usable." So the hub tolerates
`MAX_CONSECUTIVE_SINK_FAILURES` = 3 **consecutive** failures, says each one at
`error`, resets the counter on any success, and only then detaches - with
`detached_reason` readable from outside. Two tests pin both halves, and mutation
M1 (detach on the first failure, i.e. the duplex behaviour) is caught.

Nothing crosses back into PortAudio: failures are queued as bounded notices
(`MAX_PENDING_NOTICES` = 64) and journalled from the loop by the supervisor -
the same technique `CaptureProcessor.take_alignments` already uses, because the
audio thread must not open a file.

---

## 3. The explicit-address lane (D04, D05)

`jarvis/domain/explicit_address.py` - pure, standard library only:

```python
ExplicitAddressTrigger(source, label, monotonic_s, sequence)
ExplicitAddressSource = {WAKE_WORD, MANUAL_KEY}
authorizes_actions: ClassVar = False
```

- `monotonic_s` comes from `time.monotonic()`, stamped **at admission** and
  frozen. Never wall time: an NTP correction or a resume from sleep moves wall
  time backwards, and the admission latency - the one quantity D04 obliges us to
  bound - would go negative at the worst possible moment. `age_s()` clamps at
  0.0, so even a mismatched clock cannot make a stale trigger look fresh.
- `sequence` is strictly increasing per lane, so two triggers inside one clock
  tick still have a defined order (the monotonic clock's resolution is coarse on
  Windows).
- `authorizes_actions = False`: a trigger says who and when, never what to do.

`ExplicitAddressLane` (`jarvis/runtime/explicit_address_lane.py`) is the bounded
fan-in, built on the house pattern studied first - `CompositeWakeWordBackend`'s
`asyncio.Queue(maxsize=4)` - plus the one thing that pattern loses and D05
requires: **the source**.

It is a **drop-in `WakeWordBackend`**. `detections()` yields the label for
`PersistentVoiceRuntime` exactly as it consumes it today; `triggers()` yields the
full type for Slice 10. They are **two views of one queue**, never two queues,
and a test asserts the queue is empty after `detections()` has served one. This
is what lets the lane replace `CompositeWakeWordBackend` in PRESENTATION without
rewriting `run()` - which would have been a change to SIMPLE.

`suspend_for_active_session()` **delegates without reinterpreting**:
`KeyboardWakeWordBackend` deliberately keeps the key armed so a second press
submits the turn, and
`test_the_lane_forwards_suspend_for_active_session_without_reinterpreting_it`
drives the real `KeyboardWakeWordBackend` and asserts `_enabled is True`.

**Independence (D04).** The lane holds no reference to anything ambient and
awaits nothing that does. A full lane drops the **oldest** press - a press stuck
behind three others no longer designates the sentence being spoken - and names
the discarded one in the journal. A trigger served late is **still delivered**
(losing a user's press is worse than serving an old one) but counted in
`stale_deliveries` and said at `warning`; `is_fresh()` lets the consumer decide.
A source whose pump raises takes down **its own task only**: `source_failures`
names it, `live_sources` says who is left, and the manual key keeps working.

---

## 4. Pre-roll

`PreRollRing` keeps the last `DEFAULT_PREROLL_MS` = 1500 ms of PCM, hard ceiling
`MAX_PREROLL_MS` = 5000 ms clamped in the constructor with `clamped` exposed. It
exists because D05 changes what a wake word means: in PRESENTATION JARVIS is
already listening, so by the time "jarvis" is recognised the start of the
sentence has gone past. `bytes_held`, `capacity_bytes` and `evicted_bytes` are
public so a test measures the bound instead of believing it.

`CommandPreRoll` carries the snapshot with `pcm` at `field(repr=False)` **and** a
custom `__repr__`, because a `repr()` copied into a log line is exactly how raw
audio would reach a file. `to_payload()` returns counters only. Both are pinned
by a test, and mutation M14 (remove the repr guard) is caught.

`test_a_long_presentation_capture_writes_no_file_anywhere` runs 30 s of capture
under a `tmp_path` cwd and asserts `list(tmp_path.rglob("*")) == []`.

---

## 5. How each binding constraint is discharged

| Constraint | Mechanism | Test that proves it |
| --- | --- | --- |
| Exactly one physical input owner in PRESENTATION | `AudioCaptureHub` is the only opener; `input_ownership` counts; `start()` enforces `== 1` | `test_presentation_holds_exactly_one_physical_input_owner_and_the_count_says_so` (counts 1 with an interactive turn open), `test_the_interactive_path_with_a_shared_source_opens_no_sounddevice_stream` |
| Activation fails loudly; never two competing streams | Pre-open conflict refusal plus post-open count check, both `PresentationAudioError` | `test_presentation_refuses_to_start_when_another_owner_already_holds_the_microphone` (asserts `device.opens == 0`), `test_a_second_owner_appearing_during_the_open_cancels_the_activation` |
| D14 - SIMPLE untouched | `input_source` defaults to `None`; `_shared_input_source()` returns `None` unless the effective mode is PRESENTATION; the Porcupine standalone path is kept | `test_simple_keeps_its_own_input_stream_and_its_two_owners` (asserts 2), `test_simple_never_receives_a_shared_input_source_even_when_one_exists`, plus 150 pre-existing wake/audio/duplex tests green |
| D04 - trigger admitted without waiting for ambient | Lane is a separate bounded queue with no ambient reference | `test_a_manual_trigger_is_admitted_at_once_while_the_ambient_path_is_saturated` (asserts the ambient path is *really* saturated first, then measures the latency), `test_the_wake_word_still_reaches_the_lane_while_the_ambient_path_is_saturated` |
| D05 - one typed trigger, source plus monotonic time | `ExplicitAddressTrigger`, stamped at admission, frozen | `test_both_sources_normalize_to_one_type_carrying_source_and_monotonic_time`, `test_a_trigger_refuses_a_wall_clock_or_an_unbounded_label`, `test_a_trigger_is_frozen_so_its_admission_time_cannot_be_rewritten` |
| Manual key semantics preserved | The lane delegates `suspend_for_active_session` | `test_the_lane_forwards_suspend_for_active_session_without_reinterpreting_it` (drives the real `KeyboardWakeWordBackend`) |
| Wake detector fed from shared PCM | `SharedPcmWakeWordBackend` subscribes at the engine's rate | `test_the_wake_detector_reads_shared_pcm_instead_of_a_second_device` (asserts `device.opens == 1`, subscription rate 16000 against hub 24000, and 512-sample frames reaching the engine) |
| No raw audio persistence anywhere | Bounded deques; no file API in any of these modules; repr and payload guards | `test_a_long_presentation_capture_writes_no_file_anywhere`, `test_the_preroll_ring_never_holds_more_than_its_capacity`, `test_a_command_preroll_never_shows_raw_audio_in_its_repr_or_its_payload` |
| Bounded subscriber queues with a defined policy | `max_blocks` clamped to `MAX_SUBSCRIBER_BLOCKS`; `DROP_OLDEST` / `DROP_NEWEST` | `test_a_slow_subscriber_drops_its_own_blocks_and_stalls_nobody_else`, `test_drop_newest_keeps_the_backlog_while_drop_oldest_keeps_the_present`, `test_a_subscriber_queue_can_never_be_asked_for_more_than_the_hard_ceiling` |
| A slow subscriber stalls nobody | Non-blocking deque fan-out; inline failures isolated | `test_a_slow_subscriber_drops_its_own_blocks_and_stalls_nobody_else` (the fast subscriber receives all 40 blocks), `test_an_inline_subscriber_failing_once_neither_detaches_nor_stops_the_others` |
| Audio-thread boundary respected | `_on_block` does deque appends plus one `call_soon_threadsafe`; notices drained on the loop; resampling on the loop only | `test_an_inline_subscriber_failing_once_...` asserts the failure is *not* journalled until `_drain_notices()` runs |
| Device-busy surfaces loudly | `_is_device_busy` reads PortAudio's own code (-9985), the same technique as `_is_stream_already_stopped` | `test_a_busy_microphone_refuses_presentation_loudly_and_leaves_nothing_open`, `test_an_unknown_open_failure_is_named_as_unavailable_not_as_busy` |
| Device-lost surfaces loudly | `check_liveness()` watchdog plus `on_device_lost` | `test_a_microphone_that_stops_delivering_is_declared_lost_once_and_loudly`, `test_a_listener_that_explodes_on_device_loss_does_not_hide_the_loss` |
| Safe shutdown and restart | Idempotent `open()` / `close()`; closing a subscription never closes the device | `test_a_presentation_session_stops_and_restarts_without_leaking_an_owner`, `test_starting_and_stopping_twice_is_a_no_op_rather_than_a_second_stream`, `test_closing_a_subscription_never_closes_the_physical_stream`, `test_a_block_arriving_after_close_reaches_nobody_and_raises_nothing` |
| Expected path logged at info | `audio.capture_hub.opened` / `.subscribed` / `.closed`, `explicit_address.admitted`, `presentation.audio.started` | `test_the_hub_logs_the_expected_path_so_silence_never_means_both_fine_and_dead` |

### "X can never happen" turned into test cases

Every header sentence of that shape got a test at the edge where it would break
- the Slice 04 rule, applied up front rather than after review:

| Header claim | Test |
| --- | --- |
| closing a subscription never closes the physical stream | `test_closing_a_subscription_never_closes_the_physical_stream` |
| an inline subscriber cannot request another rate | `test_an_inline_subscriber_cannot_ask_for_another_sample_rate` |
| `blocks()` is not for inline subscribers | `test_calling_blocks_on_an_inline_subscription_is_refused_rather_than_silent` |
| no exception ever reaches the PortAudio thread | `test_a_block_arriving_after_close_reaches_nobody_and_raises_nothing`, `test_an_inline_subscriber_failing_once_...` |
| release is total | `test_releasing_a_stream_the_registry_never_saw_is_a_silent_no_op` |
| a phantom owner can never remain | `test_a_failed_porcupine_teardown_still_releases_its_place_in_the_count`, `test_a_failed_output_open_leaves_no_phantom_input_owner_behind`, `test_an_input_stream_whose_close_fails_still_frees_its_place_in_the_count` |
| an age can never be negative | `test_a_triggers_age_can_never_be_negative_even_with_a_clock_that_walks_backwards` |
| blocked resampling equals one-shot | `test_resampling_stays_continuous_even_when_blocks_do_not_divide_the_ratio` (4 block sizes) |
| a press is never lost, only named late | `test_a_trigger_served_late_is_delivered_and_named_rather_than_dropped` |
| an empty label is not a refusal | `test_an_empty_label_falls_back_to_the_source_rather_than_being_refused` |
| the hub refuses work after close | `test_a_hub_closed_then_reopened_serves_again_and_refuses_subscriptions_in_between` |

---

## 6. Reuse, and what was deliberately not reused

**Reused**

- `CompositeWakeWordBackend`'s bounded fan-in shape (`asyncio.Queue(maxsize=4)`,
  `_clear_pending`, cancel-then-gather on close) - studied first, as instructed,
  and carried into both `ExplicitAddressLane` and `SharedPcmWakeWordBackend`.
- `SoundDeviceRealtimeAudio._put_input`'s drop-oldest rule, as the hub's default
  policy, rather than inventing a second answer to the same question.
- `CaptureProcessor.take_alignments`' "produce on the audio thread, journal from
  the loop" technique, for the hub's notices.
- `_is_stream_already_stopped`'s technique - read PortAudio's numeric code, never
  the translated message - for `_is_device_busy`.
- `sd.RawInputStream`'s own `start()` / `stop()` / `close()` shape for
  `CaptureSubscription`, which is what let the interactive path change by one
  parameter instead of by a new class.
- `SoundDeviceRealtimeAudio._open`'s "open PortAudio off the loop with
  `asyncio.to_thread`" and its "stop before close, never free while the callback
  runs" discipline (the 8 September 0xC0000005 lesson).
- Slice 01's `XxxError(code, message)` convention - stable English codes, French
  human messages - and `jarvis/domain/_checks.check_token` for the label.
- The `MAX_*` module-constant convention with the rationale in the header, from
  `brain_context` / `work_state` / `presentation_working_set`.
- `jarvis/ports/v2.py`'s `WakeWordBackend` Protocol, unchanged, implemented by
  both `SharedPcmWakeWordBackend` and `ExplicitAddressLane`.

**Deliberately not reused**

- **`jarvis.audio.owner_verifier.resample`.** Its own docstring restricts it:
  "appele sur une fenetre de preuve entiere, pas trame par trame [...] aucun
  filtre ne traine d'etat entre deux fenetres non contigues". Applied block by
  block to a continuous stream it joins independently transformed windows, and
  the seam discontinuity is a click at 50 Hz - precisely in the band a wake-word
  engine looks at. `jarvis/audio/resampling.py` carries state across blocks
  instead, and a test proves blocked output is byte-identical to one-shot.
- **`jarvis.testlab.audio.fixtures.resample_pcm16`.** Same maths, but stateless,
  and in `testlab`, which production does not import.
- **`CaptureProcessor.observer`'s permanent latch** - argued at length in
  section 2.
- **A global refactor of microphone ownership.** SLICE.md offers
  "prefer Presentation-only shared ownership first if a global rewrite is risky"
  and the brief instructs taking it. SIMPLE keeps Porcupine's standalone stream,
  `SoundDeviceRealtimeAudio`'s own stream, and every wake and manual semantic.
  The only edits to those two files are registry calls, which observe rather
  than alter.
- **`jarvis/ports/`.** SLICE.md's "Files Likely Touched" mentions "new capture
  hub/ports". No port was added: `InputStreamFactory` and the wake-engine shape
  are audio-device details that live next to their single user, while the
  cross-package contract that already exists (`WakeWordBackend`) is reused
  unchanged. Stated here rather than silently resolved.

---

## 7. What I did NOT do, and why

**No composition-root wiring.** `PersistentVoiceRuntime` accepts
`presentation_audio=` and uses it only when the effective mode is PRESENTATION,
but `jarvis/app.py` passes nothing. This is deliberate, and it is the one place
where this slice stops short of the letter of SLICE.md.

The reasoning: there is no ambient consumer until Slice 06, so wiring it now
would open the room microphone in production and do nothing with the audio,
while adding a new competitor for a device that a live JARVIS Voice process is
holding on this very host. Slices 01 and 04 shipped their seams the same way
("no producer, no consumer"), and Slice 11 owns rollout. The adapter is
nevertheless proven end to end in tests: a real `AudioCaptureHub` feeds a real
`SoundDeviceRealtimeAudio` through `input_source`, PCM arrives in the send
queue, and the stream count stays at 1.

**The consequence, stated plainly: `HV-PRES-AUDIO-01` cannot be exercised on a
real workstation from this slice alone.** Nothing in a running JARVIS reaches
this code yet. The human check needs either Slice 11's wiring, or a deliberate
one-line composition change made for the occasion. I am not marking the check
done, and I am not claiming it is reachable.

**No anti-aliasing filter in the resampler.** Linear interpolation folds
8-12 kHz content when downsampling 24 -> 16 kHz. Acceptable for a wake-word
engine trained on band-limited microphone input; **not** acceptable for
transcription. Written into both the module header and
`docs/presentation-audio-capture.md`: a subscriber that transcribes must ask for
the hub's own rate. Slice 06 should read that line.

**Wake-word parity is behavioural, not literal.**
`PorcupineWakeWordBackend.suspend_for_active_session()` closes its device;
`SharedPcmWakeWordBackend` cannot and must not, since the device serves the
other lanes. It stops detecting instead - the same observable behaviour minus
the device churn - and a test pins that the microphone stays open across a
suspend/resume cycle.

**Inline failures are visible with up to 250 ms of delay**
(`SUPERVISION_PERIOD_S`), because they cannot be journalled from the audio
thread. The state (`failures`, `detached_reason`) is immediately readable; only
the journal line waits for the next supervisor tick.

---

## 8. Mutation runs

16 mutations, applied one at a time to the source, suite re-run, reverted.
Harness in the session scratchpad; each anchor is asserted unique before
application.

| # | Mutation | Verdict | Caught by |
| --- | --- | --- | --- |
| M1 | inline sink detaches on the **first** failure (the duplex latch) | CAUGHT | `..._failing_once_neither_detaches...`, `..._failing_three_times_in_a_row...` |
| M2 | subscriber queue loses its bound | CAUGHT | 5 tests, including the slow-subscriber and the D04 saturation test |
| M3 | pre-roll ring stops evicting | CAUGHT | `..._never_holds_more_than_its_capacity`, `..._command_preroll_is_bounded...` |
| M4 | activation skips the pre-open owner check | CAUGHT | `..._refuses_to_start_when_another_owner_already_holds...` |
| M5 | activation skips the post-open count check | CAUGHT | `..._second_owner_appearing_during_the_open_cancels...` |
| M6 | the interactive path ignores `input_source` | CAUGHT | 3 tests, including the one-owner count |
| M7 | latency measured at delivery instead of admission | CAUGHT | `..._trigger_served_late_is_delivered_and_named...` |
| M8 | a full lane drops the newest press | CAUGHT | `..._full_lane_drops_the_oldest_press_and_says_which_one` |
| M9 | a failing source is no longer isolated | CAUGHT | `..._source_that_explodes_does_not_take_the_other_source_with_it` |
| M10 | the resampler forgets the previous block | **SURVIVED, then CAUGHT** | see below |
| M11 | wake detector subscribes at the hub rate | CAUGHT | `..._reads_shared_pcm_instead_of_a_second_device` |
| M12 | the hub stays OPEN after a loss, re-announcing it forever | **SURVIVED, then CAUGHT** | see below |
| M13 | registry release raises on an unknown stream | CAUGHT | 5 tests |
| M14 | `CommandPreRoll` loses its repr guard and leaks PCM | CAUGHT | `..._never_shows_raw_audio_in_its_repr_or_its_payload` |
| M15 | an inline subscriber may silently ask for another rate | CAUGHT | `..._cannot_ask_for_another_sample_rate` |
| M16 | the hub no longer refuses subscriptions after close | CAUGHT | `..._closed_then_reopened_serves_again_and_refuses...` |

**The two survivors were real, and both changed the code rather than only the
tests** - which is the point of doing this before review instead of after.

- **M10.** The continuity test used 480-byte blocks. At 24 -> 16 kHz the step is
  1.5 samples and 240 is a multiple of it, so the carried position landed on
  exactly `0.0` every time and the carried sample was **never consulted**. The
  test proved nothing about the thing the module exists for. Fixed with
  `test_resampling_stays_continuous_even_when_blocks_do_not_divide_the_ratio`,
  parametrised over 101 / 137 / 7 / 480 samples, plus
  `test_the_resampler_actually_carries_the_previous_block_across_the_seam`,
  which reads the carried state and the interpolated seam value directly.
- **M12.** `_lost_announced` turned out to be **dead code**: `check_liveness()`
  returns early unless the state is `OPEN`, and the state moves to `LOST` on the
  same path, so the flag protected nothing. Flipping it changed no behaviour - an
  equivalent mutant, hiding a redundancy. The flag is deleted (Slice 03's "delete
  what mitigates nothing"), and the mutation was rewritten to remove the **state
  transition** instead, which is what actually carries the guarantee. That
  version is caught.

---

## 9. Exact pytest commands and counts

All run FOREGROUND, on narrow lists, per the host's memory constraint.

```
.venv/Scripts/python.exe -m pytest tests/unit/test_presentation_audio_capture.py -q -p no:cacheprovider
  -> 70 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_presentation_audio_capture.py \
    tests/unit/test_v2_wake_backends.py tests/unit/test_realtime_audio_lifecycle.py \
    tests/unit/test_voice_duplex.py tests/unit/test_owner_voice.py \
    tests/unit/test_owner_barge_in.py -q -p no:cacheprovider
  -> 334 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_speaker_verifier.py \
    tests/unit/test_interaction_mode_control_plane.py tests/unit/test_presentation_working_set.py \
    tests/unit/test_v2_architecture.py tests/integration/test_voice_runtime.py \
    tests/integration/test_voice_production_composition.py -q -p no:cacheprovider
  -> 288 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_app.py tests/unit/test_barge_in_sustain.py \
    tests/unit/test_barge_in_while_thinking.py tests/unit/test_device_playback_completion.py \
    tests/unit/test_environment.py tests/unit/test_live_idle_policy.py \
    tests/unit/test_live_runtime_safety.py -q -p no:cacheprovider
  -> 90 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_owner_input_gate.py tests/unit/test_owner_replay.py \
    tests/unit/test_solo_owner_acceptance.py tests/unit/test_v2_barge_in.py \
    tests/unit/test_v2_continuous_live.py tests/unit/test_v2_voice_toggle.py \
    tests/unit/test_v2_voice_activity.py -q -p no:cacheprovider
  -> 199 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_v2_playback_cursor.py \
    tests/unit/test_v2_speech_scheduler.py tests/unit/test_v2_latency_telemetry.py \
    tests/unit/test_voice_composition.py tests/unit/test_voice_to_claude.py \
    tests/unit/test_surface_reflex_policy.py tests/unit/test_speech_scheduler_review_races.py \
    -q -p no:cacheprovider
  -> 144 passed

.venv/Scripts/python.exe -m pytest tests/unit/test_conversation_events.py \
    tests/unit/test_conversation_event_forwarder.py tests/unit/test_conversation_event_voice_bridge.py \
    tests/unit/test_control_center_quality.py tests/unit/test_live_idle_composition_review.py \
    tests/unit/test_testlab_rollout_gate.py tests/unit/test_v2_brain_migration.py -q -p no:cacheprovider
  -> 328 passed
```

The last four batches are every unit suite that imports `realtime_audio`,
`wakeword_porcupine` or `voice_v2` - that is, the full blast radius of the three
modified source files. Zero failures anywhere. The 26 declared baseline failures
were not run and not touched; none of them is in this blast radius.

**No test opens a real microphone.** The hub's stream factory is injected, and
`sounddevice` is monkeypatched at `sys.modules` (the existing house pattern from
`test_realtime_audio_lifecycle.py`) everywhere `SoundDeviceRealtimeAudio` or
`PorcupineWakeWordBackend` is exercised. `pvporcupine` is never imported.

---

## 10. Files touched

**New**

| File | Why |
| --- | --- |
| `jarvis/domain/explicit_address.py` | D05's one typed trigger, pure |
| `jarvis/audio/input_ownership.py` | the process-wide count that makes "exactly one" measurable |
| `jarvis/audio/capture_hub.py` | the single physical owner and its bounded fan-out |
| `jarvis/audio/resampling.py` | stateful PCM16 resampling, for a subscriber at another rate |
| `jarvis/adapters/wakeword_shared_pcm.py` | wake detection from shared PCM, zero devices |
| `jarvis/runtime/explicit_address_lane.py` | the bounded, source-preserving fan-in; drop-in `WakeWordBackend` |
| `jarvis/runtime/presentation_audio.py` | the activation site that establishes ownership or fails loudly |
| `docs/presentation-audio-capture.md` | the canonical contract SLICE.md asks for |
| `tests/unit/test_presentation_audio_capture.py` | 70 tests |

**Modified**

| File | Change |
| --- | --- |
| `jarvis/runtime/realtime_audio.py` | `input_source` parameter (default `None`); registry register and release; the `_shutdown_stream` release moved into a `finally`. Nothing else. |
| `jarvis/adapters/wakeword_porcupine.py` | registry register and release, plus a docstring saying why its second stream is kept. **No behaviour change.** |
| `jarvis/runtime/voice_v2.py` | `presentation_audio` parameter (default `None`); `_shared_input_source()`; one line in `activate()`. Inert unless a session is supplied *and* the effective mode is PRESENTATION. |
| `docs/ARCHITECTURE.md`, `docs/interaction-mode.md` | one paragraph each, linking the new contract |

---

## 11. Where SLICE.md and the repository disagreed

Stated, not silently resolved.

1. **Test locations.** The brief lists `test_voice_runtime.py` and
   `test_voice_production_composition.py` among the suites to re-run; both live
   in `tests/integration/`, not `tests/unit/`. Run from there (7 tests together,
   all green).
2. **"new capture hub/ports".** No `jarvis/ports/` module was added - section 6.
3. **`PorcupineWakeWordBackend` and PRESENTATION.** SLICE.md step 5 says "Add
   Porcupine feed adapter; retain Simple standalone adapter if needed". The
   shared adapter is not a *feed into* Porcupine's existing class but a separate
   `WakeWordBackend` that drives a Porcupine **engine** from hub PCM. Feeding the
   existing class was not possible without rewriting it, which would have put
   SIMPLE at risk for no gain.
4. **`suspend_for_active_session` parity** is behavioural, not literal -
   section 7.
5. **Acceptance criterion "non-Presentation tests green"** is met across the
   whole blast radius; the 26 pre-existing failures named in the brief remain
   untouched and unaddressed, as instructed.
