# Continuous voice: echo, noise, barge-in and quick replies — 2026-09-11

Reported symptoms, after switching to `continuous_brain`:

1. While JARVIS speaks, he no longer listens: the user's voice should cut him off.
2. Noise handling is poor: JARVIS mistook his own voice for user commands, and
   office noise or nearby conversations were taken as instructions.
3. The quick replies (surface speech that does not go through the brain) are
   repetitive — "Entendu." several times — rather than fluid and relevant.

## Findings

`runtime/trace.jsonl`, session `7ff47ffe…`, 10:20 and 10:35 UTC, shows all three
problems feeding each other.

**Echo loop.** JARVIS says "Entendu." (surface reflex) → the open microphone
picks it up → server VAD opens a segment → transcript "Entendu." / "Attendu." /
"Un instant, un instant." / "Entendu. Oui." → classified `addressed` (≤ 8 words)
→ submitted to the brain as a user turn → server VAD auto-creates a new reflex
"Entendu." → … Six false turns in 12 s at 10:35:24–10:35:34. The brain even
answered one with "Pour être sûr : « Entendu », ça veut dire que je pousse les 5
commits sur GitHub ?" — an echo came close to confirming a `git push`.

**Noise.** "директор" (10:20:23) is a transcription hallucination on office
noise; it was submitted to the brain, which spent a turn on it.

**Stale answers.** The brain answered every false turn; the four answers were
then read back to back for 70 s (`voice.latency.first_brain_audio` 14.8 s,
25.3 s, 33.2 s).

**No barge-in.** `RealtimeConversationBridge._consume` played audio inline:
`await self.audio.play_b64(...)` blocks until PortAudio accepts the block, so the
event loop advanced at playback speed. The provider generates faster than real
time, so when the user spoke, `realtime.speech_started` sat behind seconds of
queued audio; by the time it was read, `response_done` had cleared `_playing`
and no barge-in happened. One single `voice.barge_in` exists in the whole trace.
Fixing only this would have made things worse: with no echo handling, JARVIS's
own echo would have triggered `speech_started` and cut him off.

**Quick replies.** `SERVER_VAD` had `create_response: true`: every VAD segment —
echo and noise included — got an automatic surface response, generated before
the transcript even existed, from a closed list of five phrases.

## Correction

### Audio (jarvis/audio/duplex.py, jarvis/adapters/webrtc_echo.py)

In continuous mode, every microphone block goes through a `CaptureProcessor`
in the PortAudio callback thread:

- **Acoustic echo cancellation**: WebRTC AEC3 through `livekit.rtc.
  AudioProcessingModule` (prebuilt Windows wheel, optional `voice` extra), with
  WebRTC noise suppression and high-pass filter. Every block written to the
  speakers is fed as the far-end reference, in lockstep with capture (one 10 ms
  reference frame per captured frame), so the reference always precedes the
  echo. Without `livekit` the processor runs without it.
- **Near-end detector**: a frame counts as user speech only if it exceeds both
  the noise floor (low percentile, measured while JARVIS is silent) and the
  expected echo (learned coupling) by a margin; confirmation needs 120 ms of
  such frames within 400 ms, including 60 ms in a row, which keyboard clicks do
  not produce. A 3 s warm-up keeps the threshold high while AEC converges.
- **Echo guard**: while JARVIS plays (plus a short tail), the provider receives
  silence instead of the microphone, unless near-end speech is confirmed — then
  the last 400 ms are sent first (so the sentence starts intact) and a
  `near_end` signal goes to the bridge.

Offline simulation (synthetic speech, 150–400 ms echo delay, nonlinear speaker):
0 false triggers over 12 JARVIS-only runs, 24/24 user interruptions detected,
median detection 0.4 s after onset, keyboard clicks rejected. Pinned by
`tests/unit/test_voice_duplex.py::test_the_webrtc_canceller_removes_jarvis_and_keeps_the_user`.

### Bridge (jarvis/runtime/realtime_audio.py)

- `_consume` now runs three tasks: a reader that never waits, a playout task
  that plays audio in order and releases end-of-output events only once the
  audio before them has played, and the main task. Events received after
  unplayed audio overtake it; otherwise stream order is kept exactly. All
  runtime callbacks (`on_mute` included) still run in the main task.
- Two-step barge-in: on `near_end`, JARVIS's volume drops to 30 % immediately;
  the provider VAD's `speech_started` confirms and cuts (local stop, then
  `cancel_output` + `truncate`, as before); without confirmation within 0.8 s
  the volume comes back and the guard closes. A `speech_started` received while
  the guard is closed is ignored (`voice.barge_in_ignored`): it can only be echo.
- Transcript filters (jarvis/runtime/turn_filters.py), continuous mode only:
  echo of what JARVIS said in the last 30 s (only for segments captured during
  or right after his speech), non-Latin script, known subtitle hallucinations,
  lone fillers. Dropped turns are traced as `voice.transcript_dropped`.
- Addressing uses an engagement window (30 s after the wake press, a JARVIS
  answer or an addressed request). Inside it: previous shape rule, plus
  imperative / second-person requests of any length ("Regarde dans mon Drive…").
  Outside it: only sentences naming JARVIS are `addressed`; the rest goes to the
  brain as `uncertain` (Decision 44), without surface acknowledgement.

### Provider (jarvis/adapters/openai_realtime.py)

- Continuous mode sends `create_response: false, interrupt_response: false`: the
  provider segments turns but never answers or cuts on its own.
- `noise_reduction: far_field` and transcription `language: fr` by default.
- `speak_reflex()` asks for a contextual acknowledgement ("Je regarde l'état des
  commits.") with the truth boundary unchanged: no result, progress, success,
  question or delay; recent acknowledgements are listed so they are not reused.

### Scheduler (jarvis/runtime/speech_scheduler.py)

- The acknowledgement is only spoken if the brain has said nothing
  `ack_delay_ms` (1.2 s) after an addressed request of four words or more; a
  brain answer for that turn cancels it; it expires 2.5 s later.
- Speech (brain or acknowledgement) waits while the provider VAD hears the user
  (at most 8 s), instead of starting over them.

### Settings (Control Center, OpenAI Realtime stack)

`echo_cancellation` (on), `noise_reduction` (`far_field`), `transcription_language`
(`fr`), `ack_delay_ms` (1200, 0 = never), `vad_type` (`server_vad`; `semantic_vad`
ends turns on meaning rather than on a fixed 1.5 s silence) and `vad_eagerness`.

### Independent review, same day

A second pass over the concurrency found and fixed seven defects, each now
pinned by a test in `tests/unit/test_voice_duplex.py`:

- a barge-in now cuts every output already received, including one whose first
  block has not played yet, and cancels the provider's *active* generation; the
  cursor of a sentence already heard in full is no longer used;
- a rejected local detection raises the learned coupling to the observed echo
  level, and a new session never starts below the prudent coupling (headset →
  speakers could otherwise make JARVIS cut himself off in a loop); a failing
  canceller switches the detector to its no-AEC margins;
- a single word is never taken for echo ("Oui." right after "… oui ou non ?"),
  and only the part of a sentence actually heard can come back as echo;
- the scheduler asks the bridge whether an output still plays locally before
  declaring it stalled (answers longer than 30 s were overlapped);
- an acknowledgement is dropped as soon as the user speaks again;
- the playback epoch is captured before handing a block to the writer thread,
  so no block plays after a cut;
- the face returns to "listening" after a noise segment or a refused turn;
- legacy mode keeps the exact stream order (no event overtakes audio there),
  and the pre-roll only replays frames that were replaced by silence.

### First workstation run, 12:41 UTC: Voice crashed on a barge-in

`provider.error invalid_value: Audio content of 4450ms is already shorter than
23868ms`, then `process.failed`. Reading a 24 s brain answer, the surface model
first added a preamble of its own ("Ok, je lis le passage mot à mot…"), so the
response held two audio items. The playback cursor kept the first item id but
counted the whole response, and the provider refused the truncation; every
provider error was fatal.

- The cursor now counts from the start of the item actually playing
  (`SoundDeviceRealtimeAudio.set_active_output` records where each item starts).
- The adapter never truncates beyond the audio received for that item.
- A provider error within 5 s of our own cancel/truncate is a degraded barge-in
  (`voice.barge_in_degraded`), not a session failure.
- The verbatim instruction now forbids any introduction: the first spoken word
  must be the first word of the brain's text.

## Verification

- `python -W error::ResourceWarning -m pytest -q`: 886 passed, 4 skipped (the
  single ResourceWarning, an unclosed SQLite connection in
  `test_an_http_error_from_the_control_center_is_a_stable_token`, predates this
  change).
- `python scripts/verify_release.py`: passed.
- New: `tests/unit/test_voice_duplex.py` (65 tests), including the 11 Sept echo
  transcripts and a barge-in while 49 audio blocks are still queued.
- Real-time bench (fake PortAudio devices whose speaker feeds its echo back to
  the microphone with 120 ms delay, real WebRTC canceller, real bridge): user
  cut-in detected 250 ms after onset and JARVIS stopped 300 ms after onset, with
  an exact truncation point; no false trigger over 8 s of JARVIS speech; on a
  second session the converged canceller detects the user 1.5 s into JARVIS's
  sentence.

**Not verified**: a run on the workstation microphone and speakers against the
real OpenAI Realtime service. The detector margins come from simulation; real
laptop speakers may need `echo_cancellation` on and the volume kept moderate.
The journal says which mode is active (`voice.duplex`: `duplex_aec` or
`duplex_guard_only`) and records every decision (`voice.barge_in_pending`,
`voice.barge_in`, `voice.barge_in_rejected`, `voice.barge_in_ignored`,
`voice.transcript_dropped`, `voice.reflex.started`, `voice.reflex.skipped`).

## Rollback

`ack_delay_ms = 0` silences the surface; `echo_cancellation = off` keeps the guard
alone; `JARVIS_VOICE_ARCH=legacy` returns to the half-duplex path, which only
gained noise reduction and the transcription language.
