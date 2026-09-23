# Presentation audio capture: microphone ownership and explicit-address triggers

Canonical contract for Slice 05 of `jarvis-presentation-interaction-mode`.
Decisions **D04**, **D05**, **D12** and **D14** are locked and this page is
where they become code. Companion pages:
[interaction-mode.md](interaction-mode.md) (the mode itself),
[presentation-working-set.md](presentation-working-set.md) (what the addressed
turn is rehydrated with).

## 1. Why anything had to change

Three separate pieces of this repository want the microphone:

| Owner | Opens | When |
| --- | --- | --- |
| `SoundDeviceRealtimeAudio` (`jarvis/runtime/realtime_audio.py`) | one `sd.RawInputStream` | for the duration of an active turn |
| `PorcupineWakeWordBackend` (`jarvis/adapters/wakeword_porcupine.py`) | **its own** `sd.RawInputStream` | while waiting for the wake word |
| Presentation | continuous capture of the room | always, by definition |

In SIMPLE the first two never overlap: Porcupine closes its device for the
duration of an active session (`suspend_for_active_session`). PRESENTATION
removes that property — nothing suspends when JARVIS listens continuously — so
the same arrangement would put two streams on one device. That is either a
driver refusal or two degraded captures, and
`tasks/.../docs/03-implementation-strategy.md` forbids it outright:

> Presentation activation fails loudly if microphone ownership cannot be
> established; never silently create two competing streams.

## 2. Ownership model

**In PRESENTATION there is exactly one physical input owner: the
`AudioCaptureHub`** (`jarvis/audio/capture_hub.py`). Everything else becomes a
subscriber.

```text
                          +--> inline sink  -> SoundDeviceRealtimeAudio
                          |    (capture thread, CaptureProcessor / AEC)
sd.RawInputStream --> AudioCaptureHub --+
   (one, in the hub)      |    +--> queued  -> SharedPcmWakeWordBackend (16 kHz)
                          |    +--> queued  -> ambient segmentation (Slice 06)
                          |
                          +--> PreRollRing (memory only, bounded)
```

### The count, not the claim

`jarvis/audio/input_ownership.py` is a process-wide registry. Every code path
that opens a physical input stream registers, every close releases, and
`open_input_stream_count()` answers "how many microphones are open right now".
Three registrants today — `realtime_audio`, `audio_capture_hub` and
`wakeword_porcupine` — so the difference between the modes is **counted**:

| Mode | Open input streams |
| --- | ---: |
| SIMPLE, idle with Porcupine armed | 1 |
| SIMPLE, active turn (Porcupine suspended) | 1 |
| SIMPLE, the moment both overlap | 2 (pre-existing, deliberately unchanged) |
| PRESENTATION, idle | 1 (the hub) |
| PRESENTATION, addressed turn in progress | **1** (still the hub) |

`PresentationAudioSession.start()` refuses if any owner is already registered
(`presentation_second_microphone_owner`) and, after opening, refuses again and
gives the device back if the count is not exactly 1
(`presentation_input_owner_ambiguous`).

### D14: what was deliberately *not* refactored

Simple keeps its own microphone ownership, untouched.
`PorcupineWakeWordBackend` still opens its own stream, still closes it for an
active session, and `KeyboardWakeWordBackend.suspend_for_active_session()`
still keeps the key armed so a second press submits the turn. The only change
to those files is the registry call, which observes rather than alters.
`SoundDeviceRealtimeAudio` grew one optional parameter, `input_source`; left
unset — which is SIMPLE — not one line of its behaviour differs.

## 3. Subscription contract and backpressure

Two subscription shapes, and the difference is structural:

- **inline** (`sink=`): the hub calls the subscriber **on the PortAudio
  thread**, on the raw block. This is what the interactive path needs, because
  `CaptureProcessor` performs echo cancellation and the echo guard in that
  thread (`jarvis/audio/duplex.py`) and moving it would break the reference
  alignment. An inline subscriber may not request another sample rate —
  resampling has no business on the audio thread — and the refusal is explicit
  (`capture_subscription_rate_mismatch`).
- **queued** (default): the block lands in a **bounded** per-subscriber deque,
  drained on the asyncio loop by `blocks()`. Resampling, if the subscriber asked
  for another rate, happens there and only there.

**Backpressure policy: bounded, never blocking, always counted.**
The default is `DROP_OLDEST`, the same rule `SoundDeviceRealtimeAudio._put_input`
already applies: a consumer that has fallen behind wants the present, not a
backlog it would then serve as if it were fresh — which is exactly the
staleness D06 exists to prevent. `DROP_NEWEST` is available for a subscriber
whose continuity matters more than its freshness. Every drop increments
`CaptureSubscription.dropped`; nothing disappears without a word.

**Failure isolation, and where it differs from the existing latch.**
`CaptureProcessor.observer` detaches **permanently on the first exception**
(`jarvis/audio/duplex.py`), which is right there: the observer is one optional
speaker check, and losing it degrades a side feature. A hub subscriber is a
*lane*. Detaching the wake detector for good on one transient exception would
kill wake-word for the rest of the session, silently, with no recovery — the
opposite of "wake detector failure must surface clearly and leave manual key
usable". So the hub tolerates `MAX_CONSECUTIVE_SINK_FAILURES` (3) **consecutive**
failures, says each one, resets the counter on a success, and only then detaches
— loudly, with `detached_reason` readable from outside.

Nothing crosses back into PortAudio: failures are queued as bounded notices and
journalled from the loop, the same technique as `CaptureProcessor.take_alignments`.

## 4. Pre-roll

`PreRollRing` keeps the last `DEFAULT_PREROLL_MS` (1500 ms, hard ceiling
`MAX_PREROLL_MS` = 5000 ms) of captured PCM **in memory only**, in a bounded
deque. It exists because D05 changes what a wake word means: in PRESENTATION
JARVIS is already listening, so by the time "jarvis" is recognised the start of
the sentence has already gone past. `PresentationAudioSession.command_preroll()`
snapshots it against a trigger and returns a `CommandPreRoll`, whose `repr` and
`to_payload` carry counters and never a byte of audio — a `repr()` copied into
a log would be exactly the raw-audio persistence this repository forbids
everywhere.

Raw audio is never written to disk. Not by the hub, not by the ring, not by the
subscribers.

## 5. Explicit-address trigger semantics (D05)

Wake word and manual key normalise to **one** type,
`jarvis/domain/explicit_address.py`:

```python
ExplicitAddressTrigger(source, label, monotonic_s, sequence)
ExplicitAddressSource = {WAKE_WORD, MANUAL_KEY}
```

- **`source`** is carried because a wake-detector failure must stay visible
  while the manual key keeps working.
- **`monotonic_s`** comes from `time.monotonic()`, stamped at admission and
  frozen. Never `time.time()`: an NTP correction or a resume from sleep would
  move wall time backwards and the admission latency — the one quantity D04
  obliges us to bound — would go negative at the worst moment.
- **`sequence`** is strictly increasing within a lane, so two triggers sharing
  one clock tick still have a defined order.
- `authorizes_actions` is `False`. A trigger says who is speaking and when,
  never what to do.

`ExplicitAddressLane` (`jarvis/runtime/explicit_address_lane.py`) is the bounded
fan-in, built on the house pattern (`asyncio.Queue(maxsize=4)`, as
`CompositeWakeWordBackend` uses) plus the source that pattern loses. It is a
**drop-in `WakeWordBackend`**: `detections()` yields the label for
`PersistentVoiceRuntime` as it exists today, `triggers()` yields the full type
for Slice 10, and they are **two views of one queue**, never two queues.

**D04 — independence.** The lane holds no reference to anything ambient and
awaits nothing that does. A full lane drops the *oldest* press. A trigger served
late is still delivered — losing a user's press is worse than serving an old one
— but it is counted (`stale_deliveries`) and said, and `is_fresh()` lets the
consumer decide. A source whose pump raises takes its own task down and nothing
else: `source_failures` names it, `live_sources` says who is left.

## 6. Failure behaviour

| Situation | Code | What happens |
| --- | --- | --- |
| Microphone already held at activation | `presentation_second_microphone_owner` | refused **before** opening; no second stream is ever created |
| Device refuses to open (busy) | `capture_device_busy` | `PresentationAudioError`, error journal line carrying PortAudio's own words, nothing left open |
| Device refuses to open (other) | `capture_device_unavailable` | same, named differently rather than collapsed into "busy" |
| More than one owner after opening | `presentation_input_owner_ambiguous` | the hub is closed again; activation fails |
| Stream stops delivering | `capture_device_lost` | said once at `error` after `silence_timeout_s`, `on_device_lost` fires |
| Inline subscriber raises | `capture_sink_failed` | counted, said; detached after 3 consecutive failures |
| Wake engine raises | `wake_engine_failed` | detection stops and says so; the microphone and the manual key are untouched |
| Wake engine cannot be built | `wake_engine_unavailable` | no subscription is left behind, no retry loop |
| Shared capture not started when a turn opens | `presentation_capture_not_started` | the bridge opens its own single stream and the degradation is journalled at `error` — degraded, never silent |

The expected path is journalled too (`audio.capture_hub.opened`,
`.subscribed`, `.closed`, `explicit_address.admitted`,
`presentation.audio.started`), so an empty trace cannot mean both "fine" and
"dead".

## 7. Resampling

The hub captures at the voice stack's input rate (24 kHz for OpenAI Realtime);
Porcupine wants 16 kHz. `jarvis/audio/resampling.py` provides a **stateful**
linear resampler that carries the previous sample and the fractional position
across blocks, so a stream cut into blocks yields byte-for-byte what the whole
stream would have. Neither existing resampler fits: `owner_verifier.resample`
is FFT-based and its own docstring restricts it to whole, non-contiguous
evidence windows; `testlab.audio.fixtures.resample_pcm16` is stateless and lives
in `testlab`, which production does not import.

Stated limit: linear interpolation has no anti-alias filter, so downsampling
folds 8–12 kHz content. That is acceptable for a wake-word engine trained on
band-limited microphone input and **not** acceptable for transcription. A
subscriber that transcribes must ask for the hub's own rate.

## 8. What this contract does not yet do

- The ambient lane (segmentation, transcription) is Slice 06; the hub has the
  subscription shape it needs and nothing more.
- The priority addressed turn, and consuming `triggers()` instead of
  `detections()`, is Slice 10.
- `PersistentVoiceRuntime` accepts a `presentation_audio` session and uses it
  only when the effective mode is PRESENTATION, but no composition root passes
  one yet: production activation belongs to the rollout slice.
