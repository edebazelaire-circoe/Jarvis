# Task13 review

2026-09-13. The durable lifecycle foundation, sideband recovery and primary
runtime integration have passed independent review and the parent release gate;
**Task13 is accepted**. Task14 is now the first open dependent slice.

## Accepted behavior

- Core owns one durable unresolved Live session across processes. Reservation,
  start marker, provider-ID bind, heartbeat, lifecycle transitions, cumulative
  usage and terminal finalization use owner epochs and CAS revisions.
- Only `START_NOT_SENT` or a matching documented `session.closed` receipt with
  finite final `usage.seconds` releases the global slot. EOF, timeout, socket
  close and UI state remain `UNKNOWN_REAP_REQUIRED`.
- The Core watchdog claims expired/uncertain ownership and uses only the
  documented known-ID sideband attach path. It installs the reader before the
  sole `session.close`, retries ambiguous outcomes with bounded backoff and
  never starts a replacement primary.
- Primary startup orders validation, durable reserve, reader, durable send
  marker, `session.start`, provider-ID bind and durable `ACTIVE`. Stop is
  latched and coalesced; SQLite latency cannot delay the urgent provider close.
- Exact terminal receipts survive pre/post-commit failures and stale-primary
  takeover. An old primary retains its unique receipt until identical durable
  `STOPPED` evidence exists.
- Duplex idle uses its finite 5–3600 second setting, recent classified local
  input, active near-end speech, checked native output drain and a bounded
  continuation deadline. Unknown sensors or device state fail closed. Jobs,
  progress, heartbeat and usage do not keep a billed session alive.
- Shutdown, fatal frontend failure and the Task17 switch hook carry distinct
  close reasons. Production composes the sideband closer without opening a
  provider connection or logging the credential.

## Review repairs

Independent tests exposed and closed cancellation races at the mark/bind
barriers, blocked-usage suppression of urgent close, frozen-receipt drift,
stale-owner receipt loss, failed-connect heartbeat leakage, a hot UNKNOWN loop,
false microphone certainty, unbounded continuation, permanent output-pending
without Live finality, late native-drain reconciliation and an initial
Realtime double-drain caused by an overly broad capability check.

The final dedicated reviewer gate passed **171 tests** with warnings as errors.
The parent lifecycle/composition gate passed **232 tests** before the two final
drain regressions; the final cross-provider drain reproduction passed **5
tests**. Counts overlap and are not summed.

## Release evidence and limits

Final parent release: **2937 passed, 5 skipped in 327.32 seconds**; release
verification passed. `git diff --check` is clean apart from existing line-ending
conversion notices. No real provider, paid Live session or audio hardware was
used. The three provider integrations remain explicitly opt-in.

Successful sideband attachment after primary loss and replay of an already
emitted terminal event remain unverified. A receipt held only in process memory
can still be lost during a simultaneous process crash and SQLite outage, while
the durable record remains unresolved. Live supplies no authoritative transcript
finality, output alignment or heard-word proof; the runtime preserves those
unknowns.
