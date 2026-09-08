# Empty Realtime input — resolution report

Implemented and validated on 2026-09-08 for the failure reported on 2026-09-07.

## Findings

Control Center trace queries confirmed that input device 3 recorded successfully
at 10:16:43 UTC, with a peak of -36.3 dBFS. Voice was already running before the
selection was saved. Its `audio.start` event still used the default input (`null`).
The next F9 requested submission 37 ms after audio opened. The provider reported
an empty buffer; the logs did not previously measure captured or transmitted bytes.
The selected device is still saved as `3`; Voice loads it on restart.

## Correction

- The Realtime adapter counts PCM bytes only after successful append sends and
  permits commits only from 4,800 bytes (100 ms at its configured 24 kHz mono PCM16).
  Empty appends and undersized commits send no commit/response request. The byte
  count resets after a successful commit send.
- Input shutdown drains callbacks already scheduled by PortAudio before placing
  the end marker in the queue, preserving final audio blocks.
- An early/short submission returns Voice to background with a retry hint. It
  does not terminate the runtime; a new F9 turn can proceed normally.
- Existing journal events now expose captured/sent bytes and duration, without
  recording audio payloads. Skips use `audio_input_not_ready` or
  `audio_input_too_short` at warning level.

The manual append/commit/response sequence remains consistent with the official
[Realtime conversation guide](https://developers.openai.com/api/docs/guides/realtime-conversations).
The 100 ms minimum is taken from the provider error in the incident.

## Validation

44 targeted tests passed across `test_v2_voice_toggle`, `test_v2_voice_activity`,
`test_audio_devices`, `test_audio_capture`, `test_app`, and
`test_control_center_mvp`. Coverage includes empty input, 50 ms, just below/exactly
100 ms, accumulation, reset, failed sends, full input queues, final callbacks,
submission before startup, and a successful F9 turn after a rejected short turn.
The provider transport and hardware are test doubles; adapter, queue, bridge,
runtime, journal and Control Center query handlers execute their real code.

Control Center trace/error queries against the generated test journals confirmed:

- 0 ms and 50 ms: `voice.input_skipped`, then `voice.background`;
- next 100 ms turn: `voice.input_submitted` with 4,800 captured/sent bytes;
- both scenarios: error query returned `[]`, runtime remained available.

`git diff --check` passed. As in the prior environment fix, pytest ran with a
process-local `os.mkdir` adjustment for Windows mode-0700 temporary directories,
fresh basetemp `runtime/pytest-empty-input-1`, and caching disabled. Application
behavior and test assertions were not bypassed.

LogBroker is not installed, so `observability.cli` cannot run. The repository's
existing journal query handlers were used instead. No temporary probes, logging
subsystems, production mocks, fallback behavior, or device hot reload were added.

## Remaining workstation check

No live microphone/OpenAI conversation was run. Windows denied process inventory
access, so no running process was restarted. Restart Voice/Jarvis to load the
saved device and this patch, press F9, wait for `LISTENING`, speak, then press F9.
Check that `audio.start` reports input device 3 and `voice.input_submitted` reports
a nonzero duration, followed by the audible response. A rapid empty turn should
return to background without `input_audio_buffer_commit_empty` or `voice.failure`.
