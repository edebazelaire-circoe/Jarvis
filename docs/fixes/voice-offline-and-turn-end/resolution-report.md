# Voice goes OFFLINE, and the turn never ends by itself — 2026-09-08

Three symptoms reported from one session: F9 started a turn but never ended it,
the answer came back in a bright voice, and the Control Center face then went
black with `voice OFFLINE`.

## Findings

**The turn never ended.** `session.update` sent `turn_detection: None`, which
disables the provider's server VAD. The turn could then only be closed by the
second F9 press that `submit_active_turn` maps to `input_audio_buffer.commit`.
That was the design of the manual toggle, not a defect, but it is not the
behaviour asked of a wake key.

**The timbre.** `V2Settings.load` defaulted `OPENAI_REALTIME_VOICE` to `marin`,
the brighter of the two gpt-realtime voices, and the session instructions carried
a generic "You are Jarvis. Speak naturally and concisely." with no persona.
`config/jarvis.toml` already used `cedar` for the non-Realtime TTS path, so the
two paths disagreed.

**OFFLINE.** Voice did not crash. `runtime/trace.jsonl` records a normal turn at
07:23:18 UTC and further activity through 07:23:32, with no `voice.stop`. But
`runtime/.voice_heartbeat` stopped at 07:23:06 and a stale
`runtime/.voice_heartbeat.tmp` was left behind holding the *next* second's value
(07:23:07). So `VisualSignalBus._atomic_text` wrote the temporary file and then
failed in `tmp.replace(path)`.

That is the Windows sharing rule: Python opens files without
`FILE_SHARE_DELETE`, so while the Control Center's `status` handler — polled once
a second by the page — holds `.voice_heartbeat` open for reading, `os.replace`
onto it raises `PermissionError [WinError 5]`. Two unsynchronised 1 Hz loops on
one file collide eventually.

The exception escaped `_voice_timeout_loop`, whose task nobody awaits until
shutdown gathers it with `return_exceptions=True`, so it died in silence. With no
further heartbeat, `status` reported `voice_online: false` after
`VOICE_HEARTBEAT_MAX_AGE_S`, and `refreshStatus` in `control_center.html` hid the
visualizer iframe and printed `OFFLINE` — over a runtime that was still healthy.
The same stall also stopped `check_timeout`, so the inactivity timeout no longer
fired.

## Correction

- `OpenAIRealtimeSession.connect` takes `auto_turn`, default true, and sends
  server VAD with `create_response` and `interrupt_response`. The bridge treats
  `input_audio_buffer.committed` as the turn boundary and releases the microphone
  there, so the speakers cannot feed the next VAD segment. Under `auto_turn` the
  wake key only ever cancels. `manual` remains available and unchanged.
- The Realtime default timbre is `cedar`, and the session instructions carry an
  explicit Jarvis persona. Both are settable from Control Center settings and
  from `OPENAI_REALTIME_VOICE` / `JARVIS_VOICE_TURN_MODE`.
- `_atomic_text` retries the replace, then writes in place and removes the
  temporary file. `_voice_timeout_loop` catches, keeps publishing, and reports
  once per outage as `voice.heartbeat_degraded` at warning level.

## Validation

168 unit tests pass. New coverage: server VAD defaults and persona in
`session.update`; the three VAD provider events mapped to envelopes; a full
hands-free turn that never calls `finish_input`, stops the input once, and
returns to background with `idle → thinking → listening → thinking → speaking →
idle`; a wake press during an auto turn cancelling instead of submitting; turn
mode parsing and rejection; the bus publishing under a permanently blocked
replace and recovering from a transient one, leaving no `.tmp` behind; and the
heartbeat loop continuing past a `PermissionError` while logging exactly one
warning.

The provider transport and audio devices are test doubles. Real microphone,
speaker echo under server VAD, and the timbre itself remain workstation checks
after a Voice restart.
