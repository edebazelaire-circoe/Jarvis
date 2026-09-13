# Task12D — uncertain stop and irreversible local playback suppression

The Live facade returns its actual `VoiceOperationResult` from `close()`.
`PersistentVoiceRuntime` accepts a typed stop only when both status is
`COMPLETED` and frontend state is `STOPPED`. Any other typed result retains the
session in `_pending_canonical_close`, exposes runtime `ERROR`, and blocks a new
activation. Neither `idle` nor `offline` is emitted by that incomplete close.
Legacy/Realtime facades whose existing close contract returns `None` keep their
existing exception-based completion semantics.

Final repair: a cancelled `LiveFrontendSession.connect()` retains an owned
cleanup task through the adapter's late shielded startup, stop attempt and
transport cleanup before propagating cancellation. Repeated caller cancellation
cannot detach cleanup. `test_cancelled_connect_owns_late_start_and_unconfirmed_stop`
proves late session.start/session.started, session.close and one transport close
with an unconfirmed terminal state remaining UNKNOWN. This is in-process
ownership, not durable crash recovery.

After application-authorized barge-in, Live playback suppression is latched
synchronously before awaiting native device stop. The facade continues to
observe provider transcripts/audio for canonical generated/received evidence,
but emits no further playable audio or output declarations. The bridge also
checks this session latch for already queued events, new output IDs and after
asynchronous pre-play callbacks. Existing native epochs continue fencing writes
that had already entered the audio wrapper. The latch does not claim that a
native write already in progress was never attempted or delivered.

## Resumption condition

There is no supported primary Live response/audio completion boundary that
proves a later audio chunk belongs to a fresh answer rather than an interrupted
tail. Therefore suppression never clears in the same incarnation: a new input,
local output ID, transcript, delegation, quiet/commentary ACK or pause cannot
resume playback. Resumption requires a new frontend incarnation after the old
provider session has confirmed closure. This intentionally sacrifices further
spoken replies in an interrupted Live incarnation. Input observations and Core
backend work continue; no cancellation of a backend Job is introduced.

The current facade caches an uncertain close result and cannot independently
reap or recover that session. Durable ownership, provider recovery, process
exit handling and eventual reconciliation belong to Task13. This slice retains
truth and the in-process reference; it does not claim crash-safe cleanup or
confirmed billing termination. Generated transcript still never becomes heard
text through these guards.

## Observability and validation

- `voice.provider_close_pending`: warning with stable
  `voice_close_unconfirmed` and frontend state; no transcript or credentials.
- `voice.stop_pending`: shutdown remains incomplete with the same code.
- `voice.live.usage`: privacy-safe session ID, seconds, provider source and
  cumulative/final tag. Real RuntimeJournal tests verify provenance and absence
  of transcript/secret text; cumulative observations are not summed.
- Existing `voice.barge_in` records authorized interruption/device stop evidence;
  no new provider cancellation or word-alignment claim is added.
- `tests/unit/test_live_runtime_safety.py` verifies typed stop propagation,
  positive confirmed stop, no false idle/offline/reopen, suppression before a
  held device stop, late old/new-ID tails after another input, and interruption
  during an asynchronous pre-play callback. The actual SoundDevice wrapper and
  bridge run against a controlled output stream; no real microphone/provider.

Command, from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_live_runtime_safety.py tests/unit/test_live_delegation.py tests/unit/test_live_duplex_review.py tests/unit/test_v2_voice_toggle.py tests/unit/test_v2_continuous_live.py tests/unit/test_v2_barge_in.py tests/unit/test_realtime_audio_lifecycle.py tests/integration/test_voice_production_composition.py tests/integration/test_live_duplex_session.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

Result: **117 passed in 3.97 seconds**. Diagnostic assertions use the repository's
injected RuntimeJournal contract; no external LogBroker service is involved.

After the final connection/usage repairs and dedicated smoke addition, parent
gate **76 passed,3 skipped**; exact command in [consolidated evidence](12-implementation-evidence.md).
The `JARVIS_LIVE_GPT_LIVE=1` smoke exists but was not executed. The2763-pass
full-release result predates these fixes and is a baseline only; final release
and acceptance remain pending.
