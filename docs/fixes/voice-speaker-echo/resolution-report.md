# Speakers without a headset: residual echo turns, and the crash they caused — 2026-09-18

Session `runtime/trace.jsonl`, 10:47:20 → 10:48:43 UTC (12:47 → 12:48 local),
loudspeakers and an ambient microphone, no headset.

Reported symptoms:

1. A few one- or two-word "user" turns that the user never spoke.
2. Voice exits with `PortAudioError: Error aborting stream: Stream is stopped
   [PaErrorCode -9983]`.

## Findings

**Residual echo becomes a turn.** The sustained-confirmation guard added on
17/09 (`_confirm_sustained_barge_in`) removed most false barge-ins, but a burst
of speaker echo that holds for `barge_in_sustain_s` still opens a segment. What
the transcription model writes on that segment is short and unrelated to what
JARVIS was saying — it is not an echo of his words, so `EchoGuard.is_echo` never
matched it, and `noise_reason` had nothing for it either:

| at (UTC) | transcript | what happened |
| --- | --- | --- |
| 10:47:28.917 | `Mhm.` | admitted, brain turn, JARVIS answered |
| 10:48:34.577 | `La plateforme.` | admitted `addressed`, brain turn, JARVIS answered "Je ne suis pas sûr de te suivre là." |

Earlier sessions of the same shape produced `Merci.`, `Bonjour à tous.`,
`Attendez...` — the courtesy formulas French transcription models emit on
silence or noise, straight out of their subtitle corpus.

**The crash.** A barge-in aborts the output stream and leaves it stopped but
owned (`_output_stopped`); the next write restarts it lazily. At 10:48:33.228 a
barge-in stopped the stream. At 10:48:42.857 a new output opened but had not
written a single block yet, so the stream was still stopped. At 10:48:42.999 the
user cut JARVIS again: `_abort_output` called `stream.abort()` on a stopped
stream, PortAudio refused with `paStreamIsStopped`, and the exception travelled
`stop_output` → `_barge_in` → `_handle_event` → `_consume` → `run` → process
exit. `_shutdown_stream` already tolerated exactly this refusal on the close
path (13/09); the barge-in path did not.

**Why the acoustic layer let it through.** AEC3 was active (`voice.duplex`,
`duplex_aec`, 10:47:13) and the reference fed to it is the post-gain block
actually handed to the device, so the cancellation path is correct. What remains
is the nonlinear residual a loudspeaker leaves in an untreated room — exactly
what `NearEndDetector.coupling_db` exists to track. That coupling is learned in
two places, and only two: continuously while JARVIS is clearly audible and no
frame is near, and on `release(learn=True)` when a candidate is **rejected**.

A candidate that is **confirmed and cut** teaches it nothing. The session shows
the hole:

```
10:48:29.365  barge_in_pending
10:48:30.870  barge_in_rejected  (first rejection on this utterance → learn=False by design, 17/09)
10:48:31.715  barge_in_pending
10:48:32.599  barge_in_confirming
10:48:33.228  barge_in → cut      (nothing learned, ever)
10:48:34.577  transcript "La plateforme."   ← the proof it was echo, arriving 1.3 s too late
```

The coupling therefore never caught up with the room, and the same echo level
reopened the guard sentence after sentence. By the time the proof arrived JARVIS
had fallen silent, the detector's window had been reset, and `release(learn=True)`
had nothing left to learn from.

**No telemetry.** Not one of `mic_db`, `ref_env_db`, `floor_db`, `coupling_db`
was journalled anywhere. On a real workstation the margins could only be guessed
at.

## Fixes

- `SoundDeviceRealtimeAudio._abort_output` skips the abort when the stream is
  already stopped, and tolerates `paStreamIsStopped` if it stops between the
  flag check and the call. The target state is reached either way.
- `SoundDeviceRealtimeAudio.stop_output` no longer lets a driver refusal escape.
  The output is already invalidated and marked unavailable; the caller reads the
  `False` as pending cleanup, exactly as it reads a missed deadline. Losing the
  whole voice session at the moment the user interrupts is worse than a degraded
  stop.
- `turn_filters.noise_reason` takes `near_playback` and gains two reasons that
  only apply there — `playback_hallucination` (a courtesy formula from
  `PLAYBACK_HALLUCINATIONS`) and `residual_echo` (at most `MAX_ECHO_WORDS` words,
  none of them from `SHORT_INTERRUPTION_WORDS`). Outside a playback overlap the
  same sentences stay ordinary user turns. `mentions_jarvis` and a single
  interruption word (`non arrête`, `stop ça`, `continue là`) both override the
  rule.
- `FILLERS` gains `mhm`, `mm`, `mmm`, `hmmm`.
- `NearEndDetector` keeps `latched_excess_db`, the excess observed when it
  latched. It survives the window reset that follows JARVIS falling silent, so a
  late `release(learn=True)` still has the level to catch up with.
- `RealtimeConversationBridge._learn_echo_from_dropped_segment` closes the loop:
  a transcript dropped for `echo`, `residual_echo`, `playback_hallucination` or
  `hallucination` over a playback overlap is proof the segment came from the
  speakers, and the detector learns from it — whether the barge-in was rejected
  or carried out. `filler`, `foreign_script` and `no_letters` are excluded: a
  hesitation or office noise comes from the room, and learning it as echo would
  make JARVIS deaf to the user.
- `NearEndDetector.diagnostics()` → `CaptureProcessor.near_end_diagnostics()` →
  `SoundDeviceRealtimeAudio.near_end_diagnostics()`, journalled under a `near_`
  prefix on `voice.barge_in_pending`, `voice.barge_in_confirming`,
  `voice.barge_in_rejected` and the new `voice.echo_learned`. Scalars read from
  the asyncio loop, no lock taken, no decision depending on them: the capture
  thread never waits on the trace.

## What to read in the trace

`near_margin_db` on `voice.barge_in_pending` is how far the frame cleared the
tighter of the two bounds. Consistently large positives while JARVIS speaks mean
`near_coupling_db` is below what the room actually returns — watch whether
`voice.echo_learned` then raises it, and how fast the continuous learning pulls
it back down. `near_warming_up` says the coupling is still held at its warm-up
floor, where cutting JARVIS off legitimately takes a louder voice.

## Limits

The interruption itself still happens on the burst that triggered it: JARVIS is
ducked and then cut for the ~0.6 s it holds, and the sentence he was reading is
lost. What changes is that the room is now learned from that burst instead of
being forgotten, so the next ones should stop crossing the margin within a
session. How fast it converges in this particular room is a measurement, not a
prediction — the `near_*` fields are there to make it one.

## Tests

- `tests/unit/test_realtime_audio_lifecycle.py` —
  `test_a_second_barge_in_tolerates_the_output_stopped_by_the_first`,
  `test_a_refused_stop_degrades_instead_of_killing_the_voice_session`.
- `tests/unit/test_voice_duplex.py` —
  `test_speaker_echo_is_only_filtered_over_jarvis_voice` (the transcripts above,
  filtered over playback and admitted in silence),
  `test_a_short_hallucination_over_the_speakers_is_not_a_turn`,
  `test_a_short_answer_over_jarvis_voice_is_still_a_turn`,
  `test_the_detector_still_learns_when_the_proof_arrives_after_jarvis_fell_silent`
  (headset coupling, speakers, cut, late proof — the same echo no longer opens
  the guard), `test_a_dropped_echo_teaches_the_detector_even_after_a_confirmed_cut`,
  `test_office_noise_is_never_learned_as_speaker_echo`,
  `test_the_detector_reports_its_levels_without_touching_them`,
  `test_barge_in_traces_carry_the_detector_levels`.
