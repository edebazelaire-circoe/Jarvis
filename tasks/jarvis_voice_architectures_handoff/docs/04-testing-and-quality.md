# Testing and Quality

## Test layers

- Contract tests for every `VoiceFrontend` adapter.
- Deterministic Conversation Core tests using fake frontends/backends.
- Provider adapter mapping tests with mocked wire events.
- Trace replay tests derived from the 11 September evidence.
- Opt-in live provider integration tests, never required for fast unit runs.

## Mandatory regression scenarios

1. Simple “OK” can produce no speech.
2. “Attends, je réfléchis” does not trigger filler while thought continues.
3. Long monologue with late correction revises provisional intent; no irreversible partial-turn action.
4. 90-second backend lookup does not block new conversational turns.
5. Backend result after topic shift becomes pending state, not automatic playback.
6. User interruption cancels stale unstarted/remaining chunks.
7. Bus/background noise does not cause repeated disruptive duck/cancel loops on weak detections.
8. Voice output differing from intended text updates heard-state with actual speech.
9. `speech_output_stalled` is detected and recovered without wedging queue state.
10. GPT-Live manual stop closes/settles billable state.
11. GPT-Live orphan/crash is closed or explicitly marked/reaped.
12. Architecture switch preserves active back-brain task state.

## Baseline evidence from source transcript

- 8/18 backend responses replaced by voice improvisation.
- Longest ready-to-speech queue wait: 35.9s.
- Longest observed brain processing delay: 85.7s.
- 71 local speech detections while JARVIS spoke, 63 not confirmed by OpenAI.
- Three `speech_output_stalled` events.

## Metrics

Capture time to first audible response, time to first useful content, end-of-turn latency, backend dispatch latency, conversation-loop blocked time, unnecessary acknowledgements, WAIT decisions, stale cancellation/playback, intended-vs-spoken divergence, interruption candidates/confirmations, false barge-ins, output stalls, active Live seconds, provider usage, cost estimates, and architecture/model/prompt revision identifiers.

## Quality gates

- Zero stale playback in deterministic supersession tests.
- Silent completion works for confirmation/noise cases.
- No adapter bypasses actual-output ledger.
- No backend tool task blocks audio input/event loop.
- GPT-Live has runtime-level stop/watchdog protection.
- Prompt inspector exposes effective JARVIS-controlled prompt for every configured role.
- Mode switching preserves active back-brain task metadata.

## Deterministic incident replay

The offline replay gate is:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_voice_replay_fixture.py tests/integration/test_voice_replay_regressions.py tests/integration/test_voice_replay_safety_regressions.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Fixtures live in `tests/fixtures/voice_replay/`. They use schema
`jarvis.voice_replay` version 1 and drive real policy seams through fake
provider, audio and Core adapters. `ReplayClock` supplies the shared wall and
monotonic clocks; the driver only advances time and dispatches typed actions.
It contains no policy oracle.

Each fixture points to a repository-relative source and separates provenance:

- `reported`: facts stated by the September 11 transcript or trace;
- `derived`: the safety invariant inferred from that evidence and the task;
- `constructed`: synthetic identifiers, timing points or payload tags added to
  make a deterministic test.

The nine current scenarios cover an uncertain thinking pause, the historical
35.9-second stale acknowledgement, an 85.7-second non-blocking backend result,
intended/generated/heard divergence, seven rejected bus-noise detections, a
confirmed interruption without a provider item, provider cancellation rejected
after generation, recovery from a missing terminal output event, and manual
closure with late Core results. Assertions target policy outcomes and real
production diagnostics. Session reports verify stale playback, divergence,
false barge-in, output-stall and close behavior where those metrics apply.

To add a field trace, sanitize it into a new JSON fixture, retain exact source
references, and state every invented value under `constructed`. Add a driver
test whose handlers call production components, then assert state, side effects
and report metrics. Raw provider audio is deliberately excluded; these fixtures
are human reconstructions or sanitized event traces and cannot prove acoustic
quality or live-provider billing behavior.

The accepted scenario matrix and validation evidence are recorded in
`19-replay-regression-summary.md`.
