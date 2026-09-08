# Empty Realtime input — 2026-09-07

## Evidence and scope

The Control Center trace query shows a successful test with input device 3 at
10:16:43 UTC (peak -36.3 dBFS). Voice started at 10:15:37, before that selection
was saved, and opened the default input at 10:16:57.381. Manual submission was
requested at 10:16:57.418, only 37 ms later. OpenAI rejected a 0 ms buffer.

The saved device selection requires a Voice restart by the existing contract.
Repair early manual submission, preserve callbacks queued before input stops,
and keep the runtime available for another F9 turn. Do not change device selection
semantics or add a resampling/fallback path.

## Observability / test contract

Use the repository's existing RuntimeJournal and Control Center trace/error query
handlers. LogBroker is absent (`observability.cli` raises ModuleNotFoundError).

- `audio.start`: selected device IDs, as before.
- `voice.input_submitted`: conversation ID, captured/sent bytes and sent duration;
  emitted only after an eligible commit and response request are sent.
- `voice.input_skipped` (warning): `audio_input_too_short` or
  `audio_input_not_ready`, conversation ID and available audio metrics; no commit
  or response request, then `voice.background` and a retry hint.
- Genuine send/provider failures retain existing error handling and codes.
- No audio payloads, credentials, transcripts, temporary probes, or new logging
  subsystem are introduced by this fix.

Validate empty/short/exactly 100 ms input, accumulation and reset after a commit,
failed sends, queued callbacks at shutdown, early submission, and a successful
turn after a skipped turn. Query journal evidence through Control Center handlers.
Real microphone/OpenAI acceptance remains a workstation check after Voice restarts.
