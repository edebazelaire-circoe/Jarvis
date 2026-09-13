# Task13C — GPT-Live primary runtime evidence

Implementation slice, 2026-09-13. This slice connects the Task12 single-reader
frontend to Task13A durable authority and Task13B recovery. It does not add the
Task16 UI or implement the Task17 architecture switch controller.

## Ownership and provider ordering

`runtime/live_primary_owner.py` owns one Voice-process incarnation. It serializes
all lifecycle CAS calls, renews the Core-authored lease independently, fences a
stale owner, retains one exact terminal receipt during persistence failure and
coalesces stop persistence. `OpenAILiveFrontend` exposes async lifecycle hooks
inside its existing sole reader.

The tested order is payload validation, Core reservation, transport/reader open,
durable start marker, `session.start`, strict `session.started` ID binding,
durable `ACTIVE`, then frontend availability. Reservation or marker failure
sends no provider start. Cancellation at marker/bind retains recoverable facts
and cannot publish a late `ACTIVE`. Audio/context methods reject fenced,
stopping or non-active owners.

Usage snapshots replace the cumulative provider value under the same CAS lock.
The reader validates primary terminal evidence with `LiveTerminalReceipt` and
persists it before its local STOPPED transition. Persistence retries reuse a
frozen active-duration/final-usage payload. If a newer reaper epoch already
finalized the identical receipt, the old primary converges; if the newer owner
is still unresolved, the primary stops retrying mutations and remains fenced.

## Runtime cleanup and idle

`LiveFrontendSession.stop(reason)` is coalesced for startup, active, idle and
uncertain paths. Core persistence is owned but only briefly awaited before the
urgent provider close, so a blocked usage write cannot suppress cleanup. EOF,
timeout, invalid closure or lost acknowledgement remains
`UNKNOWN_REAP_REQUIRED`; `PersistentVoiceRuntime` retains that canonical session
and backs off reconciliation instead of spinning or opening a replacement.

`domain/live_idle.py` defines the public typed local evidence. The bridge reports
capture callbacks classified within 2.5 seconds, current provider/local
near-end speech (`last_near` or its bounded latch), barge-in, and device output
ownership. Raw PCM without the classifier and stale callbacks remain unknown.
Because Live has no `response.done`, a local output remains pending until a
checked native stream drain succeeds; that drain proves physical quiescence and
does not claim provider or transcript finality. If the native drain exceeds the
short device wait, its owned result is reconciled asynchronously; it clears
pending output only when the audio epochs and received-PCM generation are
unchanged and the bridge queue is still empty. The speech scheduler separately
exposes `immediate_continuation_until`, bounded by candidate TTL/output timeout;
a background Job creates no deadline. Duplex uses the configured 5–3600 second
timeout, ignores backend job/progress/usage activity, records `IDLE_CANDIDATE`,
then closes with reason `idle`. Actual local output writes and validated
addressed input reset the clock. Unknown evidence prevents semantic-idle close.

The Voice exit path calls `shutdown` cleanup before releasing audio, wakeword
and the Core client. Fatal bridge failure selects `error`. A `mode_switch()` hook
selects `switch` for Task17 to call before replacement. Core production
composition injects `OpenAILiveSidebandCloser` from the already resolved OpenAI
credential without opening a socket or logging the secret.

## Verification and limits

Controlled provider and real local Core HTTP/SQLite tests cover reserve/marker
failure, exact wire ordering, cancellation during marker and bind, terminal
reason/ID/usage validation, cumulative usage serialization, heartbeat races,
blocked persistence with urgent close, pre/post-commit receipt retry, takeover
convergence, repeated stop, close uncertainty, duplicate-owner blocking,
effective Duplex timeout, idle blockers, backend-job independence, visual-bus
failure and production closer construction without network. Existing Task12
adapter, playback/barge-in and legacy runtime suites remain in the focused gate.
No provider or hardware was contacted.

Primary and sideband sockets cannot establish closure without the documented
terminal event. Device evidence still cannot identify exact heard words, and
GPT-Live primary output has no authoritative transcript-final/alignment event.
Those uncertainties remain explicit and do not promote playback or turn
finality.
