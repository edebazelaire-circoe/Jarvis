# Slice 05 — baseline QA report

| | |
| --- | --- |
| Reviewer | `qa-verification` (+ `debug`), 2026-09-23 |
| Commit under review | `34de032` on `task/jarvis-presentation-interaction-mode` |
| Working tree after QA | **clean** (`git status` empty, HEAD `34de032`) |
| Real microphone opened | **no** — never, in any test or probe |
| Decision | none. QA reports evidence; the PM decides approve/rework. |

---

## 1. What was actually run

### Test suites (all foreground, narrow lists, `.venv/Scripts/python.exe -m pytest … -q -p no:cacheprovider`)

| Command | Result |
| --- | --- |
| `tests/unit/test_presentation_audio_capture.py` | **70 passed** (2.73 s) |
| `test_v2_wake_backends.py test_realtime_audio_lifecycle.py test_voice_duplex.py test_owner_voice.py test_owner_barge_in.py` | **264 passed** |
| `test_speaker_verifier.py test_v2_architecture.py test_interaction_mode_control_plane.py test_presentation_working_set.py` | **281 passed** |
| `tests/integration/test_voice_runtime.py tests/integration/test_voice_production_composition.py` | **7 passed** |
| `test_app.py test_voice_composition.py test_v2_barge_in.py test_v2_continuous_live.py test_live_runtime_safety.py` | **89 passed** |

**711 passed, 0 failed. No regression outside the 26 declared baseline failures**
(none of the 26 suites is in this slice's blast radius, and none was run).

### Mutations re-run independently (6, including the two the implementer reported as first-round survivors)

Each applied to the source with a uniqueness assertion on the anchor, suite re-run, then `git checkout --`.

| # | Mutation | Verdict | First test to fail |
| --- | --- | --- | --- |
| M10 | `self._previous = source[last_index]` → `= None` (resampler forgets the carried sample) | **CAUGHT** (4 failed) | `test_the_resampler_actually_carries_the_previous_block_across_the_seam` |
| M12 | `self.state = CaptureHubState.LOST` removed (hub never leaves OPEN after a loss) | **CAUGHT** (1 failed) | `test_a_microphone_that_stops_delivering_is_declared_lost_once_and_loudly` |
| M4 | `if existing:` → `if False:` (activation skips the pre-open owner check) | **CAUGHT** (1 failed) | `test_presentation_refuses_to_start_when_another_owner_already_holds_the_microphone` |
| M2 | `if len(self._blocks) >= self.max_blocks:` → `if False:` (unbounded subscriber queue) | **CAUGHT** (5 failed) | `test_the_wake_word_still_reaches_the_lane_while_the_ambient_path_is_saturated` |
| M1 | `MAX_CONSECUTIVE_SINK_FAILURES = 3` → `1` (the duplex latch) | **CAUGHT** (1 failed) | `test_an_inline_subscriber_failing_once_neither_detaches_nor_stops_the_others` |
| M14 | `field(repr=False)` → `repr=True` **and** custom `__repr__` deleted | **CAUGHT** (1 failed) | `test_a_command_preroll_never_shows_raw_audio_in_its_repr_or_its_payload` |

The M10 fix is real and independently confirmed: blocked output is **byte-identical** to one-shot
output at 24→16 kHz over 4801 samples for block sizes 7 / 101 / 137 / 480 / 512 / 1200 (maxdiff 0).

---

## 2. Findings, most serious first

### F1 — **blocking** — `PresentationAudioSession.stop()` then `start()` reopens the microphone and reports success while JARVIS is completely un-addressable

`jarvis/runtime/presentation_audio.py:248-261` and `:182-246`.

`stop()` calls `self.lane.close()` (`explicit_address_lane.py:259-262` sets `self._closed = True`
permanently) and `self.wake.close()` (`wakeword_shared_pcm.py:268-271`, same). A subsequent
`start()` reopens the hub, re-registers the owner, and then:

- `lane.start()` → `if self._closed or self._tasks: return` → **returns silently**, no pump tasks;
- `wake.start()` → `if self._closed or self._task is not None: return` → **returns silently**, no subscription.

Observed:

```
cycle 1: trigger delivered -> manual_key f9
cycle 2: start() raised nothing. started=True | owners=1 | device opens=2
  journal: presentation.audio.started  level=info
           {'input_owners': 1, 'wake_word': True, 'wake_available': True,
            'sources': ['manual_key', 'wake_word']}
  cycle 2 MANUAL KEY PRODUCED NOTHING -> StopAsyncIteration
  wake frames processed: 0 | wake detections: 0 | hub blocks captured: 1
  lane stats: live_sources=['manual_key','wake_word'], source_failures={}
  hub subscriptions: []
```

Three things make this worse than a plain bug:

1. `stop()`'s own docstring says *"Idempotent, et **la session reste redémarrable**"* — false.
   `AudioCaptureHub`'s docstring (`capture_hub.py:368-370`) explicitly advertises the
   PRESENTATION → SIMPLE → PRESENTATION toggle as the reason the hub is reopenable. The hub is;
   the session is not.
2. The journal emits `presentation.audio.started` at **info** asserting `wake_available: True` and
   `sources: ['manual_key','wake_word']`. This is the exact inversion of the slice's own stated
   goal ("silence never means both fine and dead"): here a *positive* line means dead.
3. `HV-PRES-AUDIO-01` says "Exercise start/stop", so the human check targets precisely this path.

**The test that would pass against a wrong implementation is
`test_a_presentation_session_stops_and_restarts_without_leaking_an_owner`
(`tests/unit/test_presentation_audio_capture.py:549`).** Its name says "restarts"; its body
constructs a **second** session object and only counts owners. The comment at line 560 shows the
implementer knew a closed lane does not reopen — but the conclusion drawn was "compose a new
session", which was never written into `stop()`'s docstring, the canonical doc, or a guard. The
correct fix is either to make the restart real, or to make `start()` on a stopped session **refuse
loudly** instead of announcing success.

Reachability today: nothing in production reaches it (`jarvis/app.py` passes no
`presentation_audio`; confirmed by grep). This is a latent defect on the seam Slice 11 will wire,
not a live regression.

### F2 — **non-blocking** — the "exactly one owner" invariant is enforced only at activation; nothing re-counts afterwards

`presentation_audio.py:220-233` checks `open_input_stream_count() == 1` once, at `start()`. The
250 ms supervisor that already runs (`capture_hub.py:714-723`) drains notices and checks liveness
but never re-counts owners. Observed:

```
A) PRESENTATION active, owners = 1
B) a turn opened without input_source -> owners = 2 ['audio_capture_hub','realtime_audio']
C) after ~1.2 s of supervision, journal lines emitted: (none)
   hub.stats process_input_streams = 2   <- the hub KNOWS it is 2 and says nothing
```

Reachable if `voice_v2._shared_input_source()` returns `None` while a session is running — which it
does, **with no trace at all**, whenever `interaction_mode.mode is not PRESENTATION`
(`voice_v2.py:685-687`). During a mode transition that is a second physical stream opening in
silence. The counter exists and is already computed inside `hub.stats()`; the supervisor tick is
the natural place to say it. One line away from being an enforced invariant instead of an
activation-time assertion.

### F3 — **non-blocking** — `suspend_for_active_session()` discards admitted triggers, silently and uncounted, contradicting the documented contract

`explicit_address_lane.py:235-256`: `suspend_for_active_session()` → `_clear_pending()` empties the
queue without incrementing `dropped`, without a journal line. Observed: 1 press admitted, 0
delivered, 0 dropped, no journal line; `admitted - delivered - dropped == 1` vanishes.

Same shape one level down: `wakeword_shared_pcm.py:237-241` `suspend()` → `_drain_queue()` discards
queued detections without touching `self.dropped` (observed: 4 queued → 0, `dropped` stays 0).
This is a divergence from `PorcupineWakeWordBackend.suspend()` (`wakeword_porcupine.py:79-90`),
which closes its device but **leaves its queue intact**, so a Porcupine detection survives a suspend
and is re-served after `resume()`.

This contradicts three written claims: the lane header ("un appui n'est jamais perdu, seulement nommé
en retard"), `docs/presentation-audio-capture.md` §3 ("nothing disappears without a word") and §5
("A trigger served late is still delivered — losing a user's press is worse than serving an old
one"). It is *not* a regression — `CompositeWakeWordBackend._clear_pending` (`wakeword_composite.py:47-52`)
does exactly the same and is the house pattern the lane reused faithfully. But the lane wrote a
stronger promise than the code keeps.

**Answer to the D05 question posed to QA:** the `KeyboardWakeWordBackend` semantics are untouched
(the file is not in the commit; `test_the_lane_forwards_suspend_for_active_session_without_reinterpreting_it`
drives the real backend and asserts `_enabled is True`). But the shared backend's suspend **does**
drop a detection that would otherwise have been delivered, and the lane above it drops an admitted
press. Both silently.

### F4 — **non-blocking** — two of the 70 tests open the host's **real output device**

`tests/unit/test_presentation_audio_capture.py:233` and `:1484` construct
`SoundDeviceRealtimeAudio(...)` and `await .start()` **without** monkeypatching `sounddevice`.
`_open()` imports the real module and `open_streams()` calls the real `sd.RawOutputStream`.
Proven by substituting a spy for `sd.RawOutputStream`:

```
REAL sd.RawOutputStream WAS CALLED with {'samplerate': 24000, 'channels': 1, 'dtype': 'int16', 'device': None}
FAILED …::test_presentation_holds_exactly_one_physical_input_owner_and_the_count_says_so
FAILED …::test_presentation_hands_the_bridge_the_shared_capture_instead_of_a_second_microphone
2 failed, 68 passed
```

(`sounddevice` 0.5.6 is installed in `.venv`; the host has a real default output at index 5.)

**No microphone is opened** — the `input_source` path correctly bypasses `sd.RawInputStream`, and
that is exactly what those two tests assert. But the REPORT's §9 claim that "`sounddevice` is
monkeypatched at `sys.modules` … everywhere `SoundDeviceRealtimeAudio` … is exercised" is
inaccurate, the suite is not hermetic, and on this host a live JARVIS Voice process holds the audio
devices. Two lines of `monkeypatch.setitem(sys.modules, "sounddevice", …)` fix it.

### F5 — **non-blocking** — `CommandPreRoll.truncated` is a lifetime latch and is wrong on a fresh ring

`capture_hub.py:229-232` — `PreRollRing.clear()` resets `bytes_held` but **not** `evicted_bytes`;
`presentation_audio.py:289` derives `truncated=ring.evicted_bytes > 0`. Observed after a
stop/start cycle:

```
fresh ring: held=0 evicted=19200 truncated=True   <- should be False
```

So `truncated` means "this ring has ever evicted anything", not "this pre-roll is truncated" — and
after ~1.5 s of any capture it is permanently `True`. It is a public field on a seam Slice 10 will
consume.

### F6 — **non-blocking** — a device loss leaves the session "started" with no way back, and a recovered device is never re-declared alive

`capture_hub.py:725-761` / `presentation_audio.py:165-168`. After a loss: `state=LOST`, the stream
stays registered (owners = 1), `session.started` stays `True`, `device_lost=True`. `start()` then
early-returns on `if self.started`, and `hub.open()` early-returns on `if self._stream is not None`,
so neither recovers. Blocks arriving afterwards are still accepted (`_on_block` only checks
`self._stream is None`), but `check_liveness()` stays `False` forever because the state never
returns to `OPEN`. Only an explicit `stop()` then `start()` recovers — which lands in **F1**.
The loss itself is announced correctly, once, at `error`.

### F7 — **non-blocking** — backpressure is counted but never said

The hub journals `opened` / `subscribed` / `unsubscribed` / `closed` / `sink_failed` / `device_lost`,
but a queued subscriber's drops reach the journal **only** at detach time. Observed: 48 blocks
dropped by an ambient subscriber over a flood, ~3 supervisor ticks, **zero** journal lines. The
supervisor already runs every 250 ms and `hub.stats()` already computes the numbers. Against the
doc's "nothing disappears without a word" (§3), the word is a counter nobody prints.

Also in this family: `self._notices` is `deque(maxlen=MAX_PENDING_NOTICES)` (`capture_hub.py:410`),
so notice overflow itself drops silently and uncounted.

### F8 — **non-blocking** — a failed `lane.start()` / `wake.start()` leaves the microphone open and registered

`presentation_audio.py:234-236` — `await self.lane.start()` and `await self.wake.start()` are not
inside a try/except that gives the device back, unlike the two owner checks above them. Observed
with an injected failure: exception propagates, `started=False`, `opens=1`, **owners=1**,
`hub_state=open`. `stop()` does recover (its guard checks `hub.open_input_streams`), but a caller
that only sees the exception would leave a phantom PRESENTATION owner that then blocks every
subsequent activation via `presentation_second_microphone_owner`. Narrow in practice —
`SharedPcmWakeWordBackend.start()` swallows everything into `_fail`, and `build()` always supplies a
manual source — but this is the one activation path that does not return the device.

### F9 — **observation** — "a slow subscriber stalls nobody" holds for queued subscribers only

`capture_hub.py:649-687`. An **inline** sink runs on the PortAudio thread with no time budget.
Measured: a sink sleeping 50 ms per block made 10 blocks take 0.506 s on the capture thread, and the
sibling queued subscriber received nothing until it finished. This is by design (the interactive
path needs `CaptureProcessor` in that thread) and is pre-existing duplex behaviour — but it is now
*shared*, so a slow `CaptureProcessor` starves the wake detector too. `test_a_slow_subscriber_drops_
its_own_blocks_and_stalls_nobody_else` (line 645) uses **queued** subscribers only, so the REPORT's
§5 row "A slow subscriber stalls nobody" is broader than what is proven.

### F10 — **observation** — D04's saturation test saturates a queue, not the event loop

`test_a_manual_trigger_is_admitted_at_once_while_the_ambient_path_is_saturated` (line 1057) is
honest and well built: the ambient subscriber's queue genuinely overflows (`ambient.dropped > 0` is
asserted *before* any latency conclusion), the ambient consumer is genuinely behind
(`ambient_done < 200`), and the latency is real wall-clock `time.monotonic()` around a real
`await anext(triggers)` — not an artefact of the fake. The trigger path was independently confirmed
to hold no ambient reference (`explicit_address_lane.py` imports only `jarvis.domain.explicit_address`).

What it does **not** prove: independence from a *CPU-bound* ambient consumer. The fake ambient
worker `await asyncio.sleep(0.02)`, releasing the loop every block. Admission is cooperative-
scheduling dependent, and Slice 06's transcription is the realistic loop-hogger. The REPORT says
as much ("what is proved is independence, not performance"), so this is a scope note for Slice 06,
not a defect.

### F11 — **observation** — `SharedPcmWakeWordBackend` after `_fail` leaves a live subscription nobody drains, and the lane still calls it "live"

`wakeword_shared_pcm.py:178-182` — on `wake_engine_failed`, `_consume` returns without closing
`self._subscription`, so the hub keeps offering blocks into a 16-block deque forever (bounded, so
memory is safe; `dropped` climbs). And `ExplicitAddressLane.live_sources` only excludes sources
present in `source_failures`, which needs a raised exception — a wake backend that failed
internally is still reported as a live source in `lane.stats()`. `presentation.audio.started`'s
`wake_available` field is accurate at start() time only.

### F12 — **observation** — Slice 06 has no pointer to the aliasing limit

The limit is written twice and clearly (`jarvis/audio/resampling.py:21-26` and
`docs/presentation-audio-capture.md:194-197`: "not acceptable for transcription. A subscriber that
transcribes must ask for the hub's own rate"), and the doc is linked from `docs/ARCHITECTURE.md:255`
and `docs/interaction-mode.md:192`. But `slices/06-.../SLICE.md` names no document, so Slice 06's
implementer reaches it only by reading ARCHITECTURE.md first. Recommend a one-line pointer in the
Slice 06 handoff.

---

## 3. Categories verified clean

**No raw audio persistence — clean, and thoroughly so.** No file/IO call site exists in any of the
seven new modules (grepped for `open(`, `Path(`, `.write*`, `wave`, `soundfile`, `pickle`,
`json.dump`, `shutil`, `tempfile`, `os.mk*`). PCM lives only in bounded `deque`s and one bounded
`bytearray`. `CommandPreRoll` carries `field(repr=False)` **plus** a custom `__repr__`, and
`to_payload()` returns counters only; M14 proves both halves are load-bearing. `PreRollRing` is
bounded twice (requested duration and `MAX_PREROLL_MS`), cleared on `hub.close()`, and its bound is
measured rather than asserted. Every journal payload in the slice carries counters and codes only.

**The thread boundary — clean.** `_on_block` (`capture_hub.py:622-647`) does deque appends, integer
counters, and exactly one `loop.call_soon_threadsafe`, guarded by `except RuntimeError` for a
closing loop. No `await`, no asyncio primitive, no I/O, no exception escapes to PortAudio; the
`RuntimeError` guard mirrors the existing `realtime_audio` and `wakeword_porcupine` callbacks.
Inline failures are parked in a bounded notice deque and journalled from the loop — the
`CaptureProcessor.take_alignments` technique, correctly reused. Resampling is on the loop only, and
`subscribe()` refuses an inline subscriber that asks for another rate
(`capture_subscription_rate_mismatch`, M15 territory). Caveat: `FakeCaptureDevice.push` calls the
callback **in the test's own loop thread**, so no test exercises a genuine non-asyncio thread — the
guarantee holds by inspection, not by execution.

**D14 / SIMPLE — clean.** The diff against `34de032^` is exactly what was claimed.
`realtime_audio.py`: one optional `input_source` parameter, one `if/else` inside `open_streams()`,
registry calls, and `_shutdown_stream`'s `except Exception: raise` replaced by
`finally: release_input_stream(stream)` — behaviourally identical, since `except: raise` was a no-op.
`stop_input()`, `_close_owned()` and `_shutdown()` have **zero** textual change; verified. The
`CaptureSubscription` handle satisfies every call those paths make (`start()`, `stop(ignore_errors=)`,
`close(ignore_errors=)`); `abort()` is only ever called on the output stream. Independently exercised
`stop_input()` twice on a shared subscription: the subscription detaches, the hub's device stays
open, the registry stays at 1, the hub keeps capturing, and only `hub.close()` returns the device.
`wakeword_porcupine.py`: one `register_input_stream` between construction and `start()`, one
`finally: release_input_stream` in `suspend()` — no behaviour change. 264 pre-existing wake/audio/
duplex tests and 89 further blast-radius tests green.

**Activation refuses before opening — clean.** Verified by probe, not by reading: with a Porcupine
owner registered, `start()` raised `presentation_second_microphone_owner` and the fake device
recorded `opens == 0`. The post-open re-check genuinely gives the device back: with an intruder
registering *during* `hub.open()`, `start()` raised `presentation_input_owner_ambiguous` and the
registry returned to holding only the intruder. Even when the device's `close()` itself raises, the
registry slot is freed (the `finally` at `capture_hub.py:511-512`) — the documented trade-off, whose
honest cost is that PortAudio may still hold the handle; the next activation then surfaces
`capture_device_busy`, which is the right loud failure.

**Double activation — clean.** Three concurrent `start()` calls: `opens == 1`, owners == 1, one
`wake_word` subscription, 2 lane pump tasks (one per source). `AudioCaptureHub._open_lock` plus the
idempotence guards in `lane.start()` and `wake.start()` hold. `start()`/`stop()` twice is a no-op.

**The `id(stream)` registry key cannot undercount.** Analytically: CPython guarantees `id()` is
unique among *simultaneously live* objects, so two live streams can never collapse into one entry.
Empirically confirmed that an address **is** reused after the first object dies — but a recycled id
can only **overwrite a phantom (dead) entry**, which restores the correct count rather than
corrupting it. The error direction is the opposite one: a stream that dies without `release` leaves
a phantom, i.e. an **over**count, which is conservative (it refuses PRESENTATION) rather than
permissive (two live streams). `release_input_stream` is total and never raises, and the registry
deliberately holds no reference to the stream. This part of the design is sound.

**The latch decision — implemented as described.** `MAX_CONSECUTIVE_SINK_FAILURES = 3`, counter
reset on success (`capture_hub.py:686-687`), `detached_reason` readable, each failure said at
`error` from the loop. M1 (reverting to the duplex first-failure latch) is caught. The reasoning
against copying `CaptureProcessor.observer`'s permanent latch is sound and is the right call: a lane
is not an optional observer, and silently killing wake-word for a session would contradict
`docs/03-implementation-strategy.md`. The one qualification is F9 (inline subscribers are not
isolated in *time*) and F7 (drops are counted but never printed).

**Documentation — adequate.** `docs/presentation-audio-capture.md` is a genuine contract, linked
from `docs/ARCHITECTURE.md:255` and `docs/interaction-mode.md:192`. Its §6 failure table matches the
codes in the source. Gaps: it never mentions that a session cannot be restarted (F1), and its §3
"nothing disappears without a word" over-promises against F3 and F7.

---

## 4. Explicitly NOT verified

- **`HV-PRES-AUDIO-01` was not exercised, and cannot be.** No composition root passes
  `presentation_audio` (grep confirms `jarvis/app.py` passes nothing). The REPORT states this
  plainly and does not claim the check. Agreed and confirmed.
- **No real microphone was opened**, by any test or probe, at any point. Consequently no real
  device-busy, device-lost, AEC, or duplex behaviour was observed — all of it is fake-driven.
- **No genuine non-asyncio thread was exercised** (F9's blocking measurement used `time.sleep` on
  the caller's thread, which is the same shape but not PortAudio).
- The 26 declared baseline failures were not run and not touched.
- No trace/journal inspection of a live run (`runtime/trace.jsonl`) was possible: nothing in a
  running JARVIS reaches this code. All journal evidence in this report comes from an in-memory
  recording journal driven by QA probes.
