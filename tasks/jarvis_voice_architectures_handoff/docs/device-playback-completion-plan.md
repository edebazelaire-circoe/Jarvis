# Device playback completion — Task07 implementation plan

Read-only analysis, 2026-09-12. Scope: the real `SoundDeviceRealtimeAudio` path and its lifecycle/playback/barge-in tests. No code or tests changed. Task05's PARTIAL/UNKNOWN behavior remains correct until this mechanism is implemented and called by the normal canonical playback path.

## Finding and smallest credible mechanism

The current Python playout queue only waits for `RawOutputStream.write` to return. That operation submits samples to PortAudio; it does not establish that the device buffer is empty. `written_output_ms - stream.latency` is an estimate, not a final-delivery certificate. A zero/missing latency in existing fakes must not confer real-device completion.

Use a **checked output-only drain** at a genuine terminal output fence: `RawOutputStream.stop(ignore_errors=False)` in an owned worker, under the existing `_output_lock`. The installed sounddevice implementation delegates this to `Pa_StopStream`; successful return waits for pending audio buffers. Its default `ignore_errors=True` must not be used for evidence. Keep the independent RawInputStream running. [Installed implementation](C:/Projects/jarvis/jarvis/.venv/Lib/site-packages/sounddevice.py:1132).

The least racy restart policy is to leave output stopped after a successful natural drain and start it lazily, under the same native lock, before the next valid write. Track this state explicitly; do not query PortAudio through a property outside its lock. This avoids an old drain restarting output after Stop. If implementation retains eager restart, it needs an additional pre-start stream/epoch/closing check and the same tests. Start failure is a device availability failure, never proof of successful future playback.

`write_available` reports writable capacity, not consumed frames. Sleeping for latency, inspecting `active/stopped`, or filling the buffer with silence cannot independently certify the intended output was delivered. `finished_callback` alone also fires after abort. A callback-output redesign with `CallbackStop` plus a finish callback can support a different architecture, but is substantially larger than the existing blocking-output change. It is not needed to establish the initial checked-stop boundary. [Writable capacity](C:/Projects/jarvis/jarvis/.venv/Lib/site-packages/sounddevice.py:1270), [callback semantics](C:/Projects/jarvis/jarvis/.venv/Lib/site-packages/sounddevice.py:1816).

## Where the real path must call it

At the final ordered marker for a completed generated output, after all its `play_b64` writes have returned and before releasing that output to the scheduler/heard ledger, the **playout worker** invokes the drain operation. The provider reader and urgent control consumer remain available while it waits. Do not await device drain inside `_handle_event` on the sole urgent-event consumer, or speech/Stop events would queue behind it.

The existing `_play_out` ordered-marker handoff is the insertion point; Task05 may reshape that path, so apply the same ordering to its canonical consumer. The production factory must use this operation, and an integration test must observe actual calls through that factory/consumer. A method tested only in isolation is insufficient.

Only a known final generation boundary permits draining. Realtime `response.done.status=completed` can provide that boundary after its audio items have been received. An audio `.done` on a cancelled/incomplete response is insufficient. GPT-Live has no authoritative per-response end: a gap or temporarily empty Python queue cannot be promoted to a provider-final output by this work.

Use response-level drain where possible to avoid stopping/restarting the device between preamble/content parts. Snapshot all involved output/item identities before the fence; do not use only the last item cursor to confirm a multi-item response. No later-output write may overtake the fence.

## Evidence and ownership contract

Freeze an immutable drain token on the asyncio loop before scheduling native work:

- Audio-instance/session identity, output identity, provider item set as applicable.
- `_output_epoch` and `_playback_epoch`.
- Written-frame/byte extent after the final write fence.
- Stream object identity plus an operation ID for diagnostics and duplicate suppression.

The worker checks stream identity, closing flag and epochs before entering `stop`. It performs the native call with `_output_lock` held. It never takes `_cursor_lock` while holding that lock. Once the native section ends, validate the token again under the cursor/state lock before publishing. Stop/close/timeout intent invalidates eligibility immediately, before waiting on native locks.

Completion requires all of: successful checked drain, unchanged eligible token, a completed matching generation boundary, no missing/dropped/failed writes for this output, and no interruption/mute that makes full delivery uncertain. Zero audio never qualifies. Drain confirms submitted samples completed at the device API boundary; it does not prove human perception or exact word timing. Preserve that provenance.

Publish a frozen completion result for the matching output instead of setting global output latency to zero. Keep monotonic written and confirmed extents separately. Interruption cursors may still use conservative partial estimates; never derive a text prefix from milliseconds. Delayed transcript final can be reconciled with the stored output-specific device proof, and must not inherit proof from a newer output.

## Native locking and races

| Race | Required result |
|---|---|
| Stop before drain worker starts | Playback epoch already changed; worker skips drain, no completion. |
| Stop during native drain | Epoch invalidated immediately; abort waits for `_output_lock`; returning drain cannot confirm or restart stale output. |
| New output declared during drain | Old proof cannot credit new counters. New writes wait behind the owned fence/native operation. |
| Close during drain | `_closing` invalidates first; stream is not freed while `Pa_StopStream` runs. Drain must not restart it afterward. |
| Drain caller cancelled | Worker continues to exist and retains stream ownership. Cancellation is not native cancellation or completion. |
| `stop(ignore_errors=False)` raises | Delivery stays UNKNOWN/PARTIAL; report failure and perform serialized cleanup. |
| Restart fails | No subsequent write succeeds silently; runtime reports unavailable output and retains correct old evidence. |
| Duplicate/late terminal marker | Reuse/deduplicate frozen result; never drain the new output or create a second heard turn. |

The existing comments rightly protect against Windows `0xC0000005`: freeing/aborting a stream concurrently with a native write can terminate the process. Apply the same invariant to stop/start/drain. `_output_lock` covers all native output operations; `_cursor_lock` covers counters only, never nested. Preserve epoch capture before `asyncio.to_thread`, not inside the eventual worker. [Audio lock contract](C:/Projects/jarvis/jarvis/jarvis/runtime/realtime_audio.py:168).

There is also an existing accounting gap between native write return and `_credit_written`. Normal drain must be fenced after the entire awaited write operation, including credit, not merely after acquiring the native lock. Otherwise the drained-byte snapshot could miss the last credited block.

## Bounds and responsiveness: explicit native limitation

`Pa_StopStream` exposes no safely cancellable timeout here. For a normal driver, drain waits for its remaining output buffering; measure this separately from the existing 100 ms write-block budget and next-output start time. Do not promise that every driver call returns within that budget. A stuck native stop cannot safely be interrupted by racing `abort`, `close`, or reopening a stream on the same device.

Bound the **application wait/control response**, not the impossible native guarantee. Use a runtime-owned operation task/future and a non-destructive deadline (`shield` or `asyncio.wait` pattern). Deadline expiry sets an observable drain/cleanup-pending UNKNOWN state and returns control to UI. Keep the worker and old stream owned; quarantine output from new writes/recreation until the outstanding native operation resolves. A timeout must invalidate late completion promotion even if the device eventually drains. Separate input can continue until the user explicitly asks for full shutdown.

Stop/UI must acknowledge the request promptly and expose pending/uncertain cleanup. It must not claim the speaker physically stopped, fully delivered, or safely closed while native work remains blocked. A later serialized cleanup result resolves device ownership. Repeated Stop joins the existing cleanup operation. Full shutdown must preserve pending native ownership rather than lose it when the bridge task is cancelled. A thread-pool worker may also delay interpreter exit; no thread-kill workaround is safe within this slice.

## Required tests with a controlled device buffer

Create a test-only output stream with explicit `queued_frames`, `played_frames`, active/stopped state and manually advanced device clock. `write` enqueues; `stop(ignore_errors=False)` blocks on a threading condition until queued audio has actually been consumed; `abort` discards; `start` enables writing. Record overlap of **every** native operation, not only write/close. Use thread Events/Conditions for deterministic ordering, and finite assertion deadlines to avoid hung tests.

1. **Natural real wrapper path:** feed audio and provider completion through the canonical runtime, with buffer nonempty. Assert no COMPLETE/heard promotion while only write/fence completed. Advance device consumption, release checked stop, then require one matching completion and full actual generated transcript; intended text remains separate.
2. **Buffer shorter than latency:** queued 100 ms with 200 ms reported latency remains unconfirmed before drain, becomes confirmed only when the fake device consumes it. Changing `write_available` or waiting wall time alone does nothing.
3. **Capture survives:** deliver input callback chunks while drain blocks; pump still receives/sends them, no input stop/abort/close occurs. A separate asyncio ticker and urgent event remain responsive.
4. **Stop during drain:** freeze native stop, request Stop, assert epoch invalidated promptly and application deadline returns UNKNOWN; no concurrent abort/close/start. Release the driver, allow serialized abort/cleanup, assert stale completion never publishes and discarded bytes never become heard.
5. **Close/cancellation during drain:** cancel caller/bridge and request close. Assert native pointer remains alive, owned worker remains tracked, no new stream opens, and eventual close follows the native return. Repeated Stop/close creates no competing worker.
6. **Epoch switch:** change output/session identity while the old drain is blocked. After release, old byte counters/proof must not affect the new ledger/output; new PCM cannot overtake the fence.
7. **Failures:** checked stop exception, write exception, native start failure and permanent blocked-driver deadline each preserve explicit failure/unknown state. Verify `ignore_errors=False` was supplied, not merely that a fake stop method ran.
8. **Ordering:** multi-item response, duplicate completion, late transcript, late audio after interruption and completed-generation-but-never-played output. Only exact proven output/item sets qualify, with no duplicate history.
9. **Regression suite:** existing lifecycle, playback-cursor, barge-in, owner-barge-in and duplex tests; update fakes deliberately where checked native signatures/state matter. Existing fakes with zero latency and no queue are not sufficient evidence of device drain.

Focused paths: `tests/unit/test_realtime_audio_lifecycle.py`, `test_v2_playback_cursor.py`, `test_v2_barge_in.py`, `test_owner_barge_in.py`, `test_voice_duplex.py`, and Task05's canonical runtime tests.

## Task07 acceptance evidence

Report runtime trace events for drain requested/completed/stale/failed/timed-out, output identity and epochs, bytes submitted/confirmed, native elapsed time and cleanup-pending status. Avoid raw audio/transcript duplication. Supply one integrated successful natural path and injected blocked-driver/Stop path. Hardware smoke separately measures output-tail drain, restart latency and true barge-in; fake-device results establish ordering/safety policy, not acoustic quality or a universal driver latency bound.
