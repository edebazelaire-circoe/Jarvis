# Voice ends the conversation after each answer — 2026-09-09

Reported symptom: JARVIS answers, then stops listening. The user must press the
wake key again for every sentence, and cannot cut JARVIS off while he speaks.

## Findings

Not a bug: the `legacy` voice architecture was running, and this is exactly what
it does. `JARVIS_VOICE_ARCH` was unset, and `default_voice_arch()` returns
`legacy` while `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` is non-empty
(`jarvis/v2_config.py`).

Two lines of `legacy` produce the whole symptom:

- `voice_v2.PersistentVoiceRuntime.activate` passes `on_response_done=self.mute`.
  A finished answer therefore closes the session and returns to BACKGROUND.
- `realtime_audio._consume`, on `realtime.input_committed`, calls `_close_input()`
  "so the speakers cannot feed the next VAD segment". The microphone is already
  closed while JARVIS thinks and speaks, so nothing the user says is heard.
  Barge-in is gated behind `if self.continuous and self._playing`, and the wake
  key during an auto turn maps to `mute`, not to an interruption.

`runtime/trace.jsonl` shows the cycle three times in a row at 20:46–20:48 UTC:
`voice.wake → voice.active → audio.start → voice.speech_started →
voice.input_submitted → voice.output_started → voice.assistant →
voice.background + audio.stop`. One wake press, one turn, every time.

Same session, same cause, second consequence: the third turn dispatched
`claude_task` at 20:48:31 and the Realtime websocket died under it at 20:49:43
(`provider.keepalive_failed`, "Cannot write to closing transport"). In `legacy`
the long work lives inside the voice process, so the spoken answer had nowhere
left to go and fell back to `_rescue_undelivered_answer`.

## Correction

`JARVIS_VOICE_ARCH=continuous_brain` in the project `.env`. No code change. The
mode already exists and is what was asked for: one ACTIVE session spans several
turns, the microphone stays open between them, `realtime.speech_started` while
JARVIS plays triggers `_barge_in()` — local stop first, then `cancel_output` and
`truncate` — and a finished answer calls `turn_completed`, which re-arms
listening instead of muting. Only `Jarvis mute`, the wake key, the
useful-inactivity timeout or an unrecoverable failure return to background. It
also moves the long work to Core, which survives the voice session (Decision 11),
so the websocket failure above can no longer swallow an answer.

Preconditions verified on this workstation: OpenAI Realtime stack, automatic turn
mode, and a session object that implements `speak`/`cancel_output`/`truncate`.

Accepted trade-offs, all documented in the README rollout gate:

- The surface receives an **empty** tool catalogue (Decision 34). Calendar and
  reminder creation from voice is gone; the brain's own access is unverified.
- No acoustic echo cancellation exists. The microphone is open while the speakers
  play; headphones are the mitigation, `vad_threshold` the adjustment.
- The default surface model becomes `gpt-realtime-2.1-mini`
  (`DEFAULT_CONTINUOUS_SURFACE_MODEL`), since the surface only acknowledges.
- The 90 s useful-inactivity timeout still applies: silence ends the session.
  Raise "Délai d'activité utile" in Control Center settings to hold it longer.

Rollback is removing the line and restarting Voice.

## Validation

719 unit and integration tests pass in the `jarvis-dst` sandbox with a clean
environment. In the live folder two tests fail for reasons unrelated to this
change: `test_drive` needs the `mcp` package (not installed there), and
`test_health` reads `JARVIS_VISUALIZER_ENABLED=1`, which leaks from the shell
that launched the stack into every child process and overrides the `enabled=false`
the test writes in its own config.

Not validated: this is a configuration change on a path with no workstation
acceptance. Microphone, speakers, headphones, echo, VAD retriggering and audible
barge-in remain unmeasured (`docs/ACCEPTANCE_STATUS.md`,
`docs/handoff-realtime-brain/FINAL-REPORT.md`).
