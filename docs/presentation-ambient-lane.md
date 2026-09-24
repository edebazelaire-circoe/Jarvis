# Presentation ambient lane: continuous speech becomes recent text

Canonical contract for Slice 06 of `jarvis-presentation-interaction-mode`.
Decisions **D03**, **D04**, **D06** and **D08** are locked and this page is
where they become code. Companion pages:
[presentation-audio-capture.md](presentation-audio-capture.md) (who owns the
microphone), [presentation-working-set.md](presentation-working-set.md) (where
the text lands), [interaction-mode.md](interaction-mode.md) (the mode itself).

Implementation: `jarvis/domain/ambient_observation.py` (types and the cheap
analysis, pure), `jarvis/audio/ambient_segmenter.py` (utterance boundaries),
`jarvis/runtime/ambient_lane.py` (the lane).
Conformance: `tests/unit/test_ambient_ingestion_lane.py`.

## 1. The chain, and why every link already existed

```text
AudioCaptureHub.subscribe(sample_rate=None)   Slice 05 — a *queued* subscriber
   -> AmbientSegmenter                        duplex.frame_db + owner_verifier.SpeechGate
   -> TranscriptionBackend                    jarvis/ports/transcription.py, unchanged
   -> PresentationWorkingSetStore.observe()   the fresh tail, FIRST
   -> analyse_ambient_text()                  pure, no model, no network
   -> PresentationWorkingSetStore.apply()     the working set, on its own queue
   -> AmbientTrigger                          Slice 08 / Slice 09 consume these
```

Three of the five links are reused as they stand:

- **the hub subscription.** `AudioCaptureHub.subscribe()`'s own docstring named
  this lane by number. Nothing was added to the hub.
- **the transcription port.** `jarvis.ports.transcription.TranscriptionBackend`
  — `AudioClip` in, `TranscriptionResult` out — already existed and is the only
  provider-neutral speech-to-text seam in the repository. It is **not widened**:
  the single existing adapter (`OpenAITranscriptionBackend`) satisfies the lane
  without one line of change, and so will any second provider. The lane
  **imports it** and annotates its constructor with it; a first version
  declared a local look-alike Protocol returning `Any`, which described the
  seam instead of reusing it and left the port with zero importers.
- **the store.** `PresentationWorkingSetStore.observe()` / `.apply()` /
  `.prune()`, exactly the API Slice 04 shipped. The lane declares a structural
  `PresentationObservationSink` Protocol over those three methods plus
  `snapshot`, because Core and Voice are two processes (see §7), not because
  the store needed anything new.

The two genuinely new things are **utterance segmentation**, which did not
exist in any form (the repository's only VAD is the provider's server-side one,
and its only energy detectors answer a different question), and **the cheap
analysis**, which is a small set of French shape tests.

## 2. Why the Realtime transcript stream is not the ambient source

The repository already turns speech into text a second way: the Realtime
provider transcribes continuously and `SoundDeviceRealtimeAudio` classifies
each transcript, dropping the `AMBIENT` ones. Tapping there would have looked
like less duplication. It is the wrong seam, for three reasons that are
structural rather than stylistic:

- in PRESENTATION the Realtime session is opened **for an addressed turn**, on
  an explicit-address trigger (D05). Between turns there is no provider session
  and therefore no transcript. Ambient speech is by definition the speech that
  happens when nobody is addressing JARVIS;
- a Realtime session held open for the length of a presentation is a metered
  provider connection with a hard session ceiling
  (`PROVIDER_MAX_SESSION_SECONDS`), for audio that mostly needs nothing;
- the handoff's architecture page
  (`tasks/jarvis-presentation-interaction-mode/docs/02-architecture.md`, which
  is where it lives — there is no `docs/02-architecture.md`) draws the ambient
  branch off the hub, in parallel
  with the explicit-address detector, precisely so that ambient backlog cannot
  reach the command path.

The lane's ingress is one method, so a future Realtime-derived ambient
transcript enters the same path rather than creating a second one.

## 3. Segmentation

`AmbientSegmenter` is a two-state machine — silence, speech — plus a fall-off
delay, over 20 ms frames. It reuses `jarvis.audio.duplex.frame_db` for the
level and `jarvis.audio.owner_verifier.SpeechGate` for the adaptive floor; both
are production code, both already answer "is this frame speech", and they share
one dB scale by explicit contract.

| Constant | Value | Why |
| --- | ---: | --- |
| `FRAME_MS` | 20 | the same frame as `owner_verifier.GATE_FRAME_MS`, for the same reason |
| `DEFAULT_MIN_UTTERANCE_MS` | 500 | below this it is a chair, a throat, an "mm" — a provider call that returns nothing |
| `DEFAULT_SILENCE_HANGOVER_MS` | 700 | above the pauses inside a sentence (~200-400 ms), below the pause between two |
| `DEFAULT_MAX_UTTERANCE_MS` | 12000 | the forced cut; 12 s of 24 kHz PCM is 576 KB, and a longer clip makes the tail late |
| `DEFAULT_LEAD_IN_MS` | 200 | kept *before* the first voiced frame so the attack of the first syllable is not eaten |

**The forced cut is the bound that matters.** A speaker who does not breathe
would otherwise grow a buffer with no ceiling, and that buffer is raw audio. At
the cut the segment carries `truncated=True`, and the lane turns the next
transcript into a **revision of the same utterance** rather than a second one —
so one sentence occupies one tail rank, and a deictic "ça" points at a whole
thought. A revision keeps the original `sequence`: a late correction must never
pass itself off as the freshest speech.

**And that promise expires.** The cut promises a continuation; every failure
between the two — transcription raising, timing out, returning empty, a store
refusal, a `drop_oldest`, a continuation the segmenter drops for being under
`min_frames` — would otherwise leave the promise open forever. The next
successful transcript, an hour later, would then be glued onto twelve-second-old
text under the **old** utterance id, with `revision + 1` and a **fresh**
`spoken_at`: stale speech wearing a current timestamp, in the one field a
deictic resolves against. The pending revision therefore carries a generation
and a `stamped_at`, it is validated before every use, it is swept on the idle
tick, and abandoning it is counted (`revisions_abandoned`) and said
(`ambient_revision_abandoned`) with its reason. It is also armed **only after**
the store accepted the text it promises to extend.

**No rate conversion happens anywhere on this path.** The lane subscribes with
`sample_rate=None` and the segmenter hands the hub's own PCM to the provider.
`presentation-audio-capture.md` § 7 states the limit that makes this
obligatory: the hub's resampler is linear interpolation with no anti-aliasing
filter, so 24 → 16 kHz folds 8-12 kHz into the speech band — fine for a
band-limited wake engine, wrong for transcription. Either subscribe at the
native rate or filter properly; this lane takes the first branch, which is also
the one that adds no DSP code to maintain. A provider that wants 16 kHz
receives an `AudioClip` that *states* its rate and converts with its own
filter.

## 4. Queue budgets

**Policy: bounded, never blocking, always counted, `drop_oldest`** — the same
rule and the same reason as `CaptureSubscription`: a consumer that has fallen
behind wants the present, not a backlog it would then serve as if it were
fresh.

| Queue | Bound | Why this number |
| --- | ---: | --- |
| hub subscription (`DEFAULT_CAPTURE_BLOCKS`) | 64 blocks ≈ 3.2 s, 150 KB | the drain task does per-frame energy arithmetic — RMS plus `SpeechGate`'s percentile over a 250-value sliding window, so not *quite* nothing, but two orders of magnitude under a transcription; 3.2 s covers a GC pause without losing a sentence |
| segments (`DEFAULT_SEGMENT_QUEUE`) | 3 | a **memory** bound, and only that: 3 × 576 KB of raw audio at worst. Staleness is owned by `MAX_SEGMENT_AGE_S`, which says it in seconds and applies it on every take; a queue depth cannot express it, since a segment lasts 0.5 to 12 s depending on whether silence or the forced cut closed it |
| analyses (`DEFAULT_ANALYSIS_QUEUE`) | 8 | honestly: **it absorbs nothing today**. The analysis is synchronous and costs microseconds, behind a single transcription worker, so no burst can fill this queue — the test that proves `analysis_dropped_queue` has to cancel the worker to get there. The queue exists because the separation is contracted (SLICE.md: *bounded async analysis queue*, *backpressure diagnostics*) and because it is what guarantees the analysis can **never** push back on the tail, including the day it stops being cheap |
| `DEFAULT_TRANSCRIPTION_TIMEOUT_S` | 20 s | the largest clip is 12 s; a provider silent for 20 s describes a room that has changed subject |
| `MAX_SEGMENT_AGE_S` | 30 s | a segment that waited this long is discarded **and said**, rather than filed behind fresher speech |
| `MAX_CONSECUTIVE_TRANSCRIPTION_FAILURES` | 3 | the hub's number and the hub's reason: one or two are a hiccup, three are a fault that lasts |
| `TRANSCRIPTION_FAILURE_WINDOW_S` | 120 s | **and the hub's window with it.** Without a lull reset the counter says "since forever" rather than "in a row", and three hiccups spread over a quiet afternoon would declare the lane degraded — which is exactly why `capture_hub.py` pairs `SINK_FAILURE_WINDOW_S` with its threshold and says so where it resets. Wider than the hub's 2 s because an inline subscriber gets a block every 50 ms while an ambient segment arrives every few seconds at best |
| `MAX_PENDING_REVISION_AGE_S` | 30 s | a forced cut *promises* a revision; a promise with no deadline is a leak. See § 3 |
| `IDLE_PRUNE_PERIOD_S` | 30 s | the store's age budgets are measured from the newest speech; with no speech nothing would fire them, and Slice 04 assigned that sweep here |

Every drop increments a counter in `AmbientLaneCounters` and is journalled once
per event: `segments_dropped_queue`, `segments_dropped_stale`,
`segments_cancelled`, `analysis_dropped_queue`, `analysis_cancelled`. Nothing
disappears without a word, and `lane.stats()` prints all of it — an invariant
that cannot be read is an invariant that drifts.

**Exactly one transcription worker**, deliberately. The store assigns an
utterance's rank *at the moment of the call*, so two concurrent transcriptions
would make tail order depend on provider latency and a sentence said earlier
could be filed later. Parallelism would be bought with the only thing the tail
guarantees.

## 5. The tail before the analysis (D06)

The guarantee is **not** the order of two lines — the analysis runs in another
task, so `apply()` lands after `observe()` whatever line enqueued it, and a
frank inversion of the source would still "pass" an order-of-calls test. What
makes the inversion *impossible* is a **data dependency**: the enqueue carries
`sequence = self._tail_sequence(utterance_id)`, a rank that does not exist
until the store has assigned it, and it sits behind `if not applied: return`.
The second step needs a value only the first can produce.

`_transcribe_worker` therefore calls `sink.observe()` before anything reaches
the analysis queue, and the analysis lives on its own queue drained by its own
task. So:

- the tail is updated the moment a transcript exists, whatever the analysis is
  doing;
- the working set can be ten utterances behind, and the snapshot *says so* —
  `enrichment_lag_entries` and `enrichment_lag_s` are computed from
  `observed_sequence`, which is the real tail rank the lane reads back from the
  snapshot after each successful append. A fabricated rank would make both
  readings meaningless, which is why the lane reads rather than counts.

## 6. Ambient text is context, never a command (D03 / G7)

This is held by types, not by caller discipline:

- `AmbientUtterance`, `AmbientTrigger` and `AmbientAnalysis` each carry
  `authorizes_actions` as a `ClassVar` fixed at `False` — the same stance as
  `PresentationContextSnapshot` and `VoiceConversationSnapshot`. No instance
  can say otherwise, not even through `dataclasses.replace`;
- `AmbientTriggerKind` is closed and contains only *investigation* natures:
  `checkable_claim`, `external_reference`, `open_question`, `new_topic`. There
  is no "execute", and adding one means editing that file and breaking a test
  that walks the whole enum;
- the lane imports **no** authorization path. Not `BrainTurnInput`, not
  `VoiceTurnAdmissionRequest`, not `AddressingDecision`, not a brain service,
  not a tool. An import-graph guard fails if one ever appears;
- `AddressingDecision{ADDRESSED, AMBIENT, UNCERTAIN}` is **not widened** and the
  two existing refusals of `AMBIENT` — in `BrainTurnInput.__post_init__` and
  `VoiceTurnAdmissionRequest.__post_init__` — are **not relaxed**.
  `BackBrainTaskService`'s addressed-only admission is untouched.

**A caveat on the observability, not on the guarantee.** `looks_imperative` is
a French shape heuristic and the weakest thing in the analysis. Its first
version tested only the *first word of each sentence*, with sentences split on
`.!?…`; a room transcript is often unpunctuated, so the whole utterance was one
sentence and only its first word was examined — *"et donc tu sais ouvre le
fichier"* scored `False`. It now looks for an action stem anywhere, minus the
two contexts that make it something else (a subject in front, "il **ouvre** la
séance"; a determiner, "la **lance** du chevalier"). It will still miss cases.
**D03 does not depend on it** — the closed trigger vocabulary and the
`ClassVar` hold that — but the counter that makes D03 *observable* does, so its
limit belongs here rather than in a commit message.

The analysis *recognises* the imperative and does nothing with it.
`AmbientAnalysis.imperative` and the lane's `imperative_utterances` counter
exist so the guard is observable: a test can show that "supprime la ligne 12"
was seen as a command **and** that nothing came out of it. An imperative
sentence is also not filed as a checkable claim, because it states no fact to
confront with a source — it yields at most a topic.

## 7. Two processes, one seam

`jarvis core` and `jarvis voice` are separate processes. The microphone, the
hub and this lane live in Voice; the working-set store lives in Core. The lane
therefore takes a `PresentationObservationSink`, structurally satisfied by
`PresentationWorkingSetStore` as it stands, so an in-process composition needs
no adapter and a cross-process one needs only a relay.

**One warning for whoever writes that relay, while it is still free.**
`PresentationObservationSink` is declared **synchronous**, and `_analyse` calls
`sink.apply()` up to fourteen times in a row with no `await` between them. A
cross-process relay behind a synchronous Protocol is blocking IO on the Voice
event loop — the same loop that carries the explicit-address lane, which D04
says ambient work may never delay. So the cross-process branch is **not** a
one-line substitution: it needs either an async sink Protocol (and an ambient
worker that awaits it) or a non-blocking hand-off, and choosing it without
choosing that is a D04 violation waiting to be discovered in production.

**No composition root passes a lane yet**: production activation belongs to the rollout slice, for
the same reason Slice 05 left `PresentationAudioSession` unwired — wiring it
now would open the room microphone in production and compete for a device the
operator's live Voice process holds.

## 8. Failure behaviour

| Situation | Code | What happens |
| --- | --- | --- |
| Provider raises | `ambient_transcription_failed` | counted, said at `error` **in the provider's own words**, loop continues |
| Provider silent past the deadline | `ambient_transcription_timeout` | the worker is released, the segment abandoned, counted |
| Three failures inside `TRANSCRIPTION_FAILURE_WINDOW_S` | `ambient_lane_degraded` | `degraded = True`, said **once**, at `error`; the lane keeps trying. Three failures *outside* the window are three hiccups and degrade nothing |
| A transcript arrives after recovery | `ambient_lane_recovered` | said once |
| Empty transcript | `ambient_transcript_empty` | nothing is filed; counted |
| Provider text longer than the tail's bound | (clipped) | clipped rather than lost, and `transcripts_clipped` counts it |
| Segment queue full | `ambient_segment_dropped` | oldest dropped, counted, said |
| Analysis queue full | `ambient_analysis_dropped` | oldest dropped, counted, said |
| Segment older than the age budget | `ambient_segment_stale_age` | discarded and said, not filed behind fresher speech |
| Work cancelled while in flight | `ambient_segment_stale_cancelled` | the returning transcript is refused: speculation is sacrificial (D08) |
| Store refuses (`capacity`/`stale`/`stale_session`/`rejected`/`ignored`) | the store's own code | counted per disposition and said; `duplicate` and `applied` are not losses |
| Store answers a disposition the lane does not know | `ambient_disposition_unknown` | said at `error` rather than silently bucketed |
| A trigger consumer raises | `ambient_consumer_failed` | counted and said; the next consumer and the next utterance are unaffected |
| Anything raises in the transcription worker outside its narrow `try` | `ambient_transcription_worker_failed` | counted (`worker_crashes`), said in the failure's own words, **the loop restarts**. This is the only task that transcribes, and a `sink` is a Protocol over an arbitrary object — a cross-process relay will raise |
| The capture task raises | `ambient_capture_failed` | said at `error`, the lane is marked **deaf** |
| The hub detaches the subscriber (`blocks()` returns) | `ambient_capture_ended` | said at `error`, the lane is marked **deaf**. Without it, "the room is quiet" and "the lane hears nothing" wrote the same thing |
| Segmentation raises | `ambient_segmentation_failed` | said, segmenter reset, capture continues |
| Analysis raises | `ambient_analysis_failed` | said at `error`; the tail already has the speech, only the enrichment is missing |
| The idle sweep raises | `ambient_prune_failed` | said at `error`; the next sweep tries again |
| The idle sweep is refused | the store's own code | counted in `prune_dispositions` and said, like every other store call |
| Releasing the subscription raises at stop | `ambient_unsubscribe_failed` | said at `error`; the stop completes |
| The store says "applied" but the utterance is not in the snapshot | `ambient_sequence_not_found` | counted and said at `error` rather than inventing rank 1, which would make an up-to-date working set report maximal staleness |
| A promised revision never arrives | `ambient_revision_abandoned` | counted and said with its reason; the next speech opens a fresh utterance |
| A segment is cancelled or its generation moved | `ambient_segment_stale_generation` / `ambient_segment_stale_cancelled` | counted and said; speculation is sacrificial (D08) |
| The journal itself raises | — | swallowed with an argument: a broken journal must not take down the lane it observes, and there is no second channel |

**Failure isolation is structural, not hopeful.** The lane holds no reference to
`ExplicitAddressLane`, awaits nothing that belongs to it, and is a *queued* hub
subscriber — an inline one would starve its siblings on the capture thread
(measured in Slice 05: 10 blocks in 0.506 s). A test kills transcription for a
whole session and then presses the manual key; another holds every
transcription for 500 ms, fills the backlog, and **measures** the explicit
admission latency.

The expected path is journalled at `info` too —
`presentation.ambient.{started,segmented,transcribed,analysed,pruned,stopped}`
— so an empty trace cannot mean both "fine" and "deaf". And deafness itself is
a state, not an absence: `stats()` carries `deaf` and `deaf_reason` beside
`degraded`, because the two ways the lane actually stops hearing — the hub
detaching it, and the transcription task dying — used to leave exactly the same
numbers behind as a quiet room.

## 9. Nothing that was said, nowhere in the trace

Raw audio lives in the segmenter's bounded `bytearray`, in the bounded segment
queue, and in an in-memory WAV handed to the provider. It is never written to
disk. `AmbientSegment.__repr__` and `.to_payload()` carry counters only, the
way `CommandPreRoll` does, because a `repr()` copied into a log is enough to
leak PCM into a file.

No journal line from this lane carries transcript text, a topic label, a claim
or a question — only ids, counts, durations and stable codes, with copied
values clipped at 64 characters, the same rule as the working set and the
Control Center. A test plants a distinctive phrase, drives the whole lane, and
searches every emitted line for it; another asserts that the normal path *is*
journalled, so an empty journal cannot pass it.

**One honest exception, outside this lane.** The existing Realtime path already
writes transcript text into a trace line (`voice.transcript_dropped` uses
`text[:300]` as its message, `jarvis/runtime/realtime_audio.py`). That predates
this slice and is not changed here; the rule above is a statement about the
ambient lane, and the test that enforces it is scoped to the ambient lane's
journal.

## 10. What this contract deliberately does not do

- **No alert policy.** A `checkable_claim` trigger is a lead, not a warning.
  Fact-check attention is Slice 09.
- **No speculative execution.** Triggers are handed to a callback and nothing
  more; sub-agent preparation is Slice 08 and now exists at
  [presentation-speculative-preparation.md](presentation-speculative-preparation.md).
  The coupling stays one-way: this lane hands a trigger over and imports
  nothing of it, which is what keeps the closure above at twenty modules.
- **No priority field.** P0-P4 belongs to the speculative path, never here.
- **No action, ever.** That is D03, and §6 is how it is held.
- **No composition-root wiring.** That is the rollout slice — see §7.

## 11. Caveats Slice 08 inherits, stated rather than implied

- **The four confidences (0.6 / 0.5 / 0.5 / 0.3) are posed, not calibrated.**
  There is no measurement behind them in this slice. They order a list; they do
  not estimate anything. Treat them as a rank, never as a probability, and
  recalibrate them against real triggers before gating anything on a threshold.
- **`_references` is coarse.** Any sentence containing one of nineteen nouns
  ("rapport", "étude", "page", …) yields the *whole sentence* as a reference.
  That is enough to notice that something was cited; it is not an extraction,
  and a consumer that needs the citation itself has to do its own work.
- **Topic extraction is determiner-then-noun** and nothing more. Elided
  determiners are handled (`l'écart` yields `écart`), a verb after a determiner
  is not (`la lance` is a topic). A false positive costs one entry in a
  bounded, self-evicting collection, which is the trade this path is allowed to
  make — a model call per utterance is what D08 forbids.
- **The idle sweep never runs while anyone is talking.** `prune()` is reached
  only when no segment arrives for `IDLE_PRUNE_PERIOD_S`, which is correct (the
  store applies its age budgets on every commit) but means a `prunes` counter at
  zero during a lively presentation is normal, not a fault.
