# Task13B — GPT-Live sideband recovery evidence

Implementation slice, 2026-09-13. This slice adds recovery transport and the
Core-owned orphan watchdog on top of Task13A. It does not wire primary session
startup, microphone/audio, semantic idle policy, architecture replacement or UI;
those remain Task13C and later work.

## Sideband boundary

`jarvis/ports/live_sideband.py` defines the provider-neutral terminal receipt and
closer seam. `jarvis/adapters/openai_live_sideband.py` attaches only to the
retained opaque provider identity at
`wss://api.openai.com/v1/live/sessions/{id}/attach`, using the same project
Bearer credential. The ID is path-escaped. The adapter creates its sole reader
before sending exactly `{"type":"session.close"}`. It never sends
`session.start`, input audio, a status request, DELETE or HTTP hangup.

Only `session.closed` with the requested session ID, one documented close reason,
and finite nonnegative bounded `usage.seconds` produces `LiveTerminalReceipt`.
Other valid Live events are ignored while waiting. EOF, timeout, attach/send/read
failure, wrong identity, missing fields, malformed JSON, duplicate keys,
non-finite numbers and oversized frames produce no receipt. The aiohttp transport
owns both WebSocket and HTTP session.

The closer calls an injected receipt sink before releasing its transport. The
watchdog sink records the typed receipt in its one-element in-memory slot, then
attempts durable finalization. Transport/reader cleanup runs as a separately
owned bounded task, so a native close that resists cancellation cannot hide an
already accepted receipt or block Core shutdown. Any still-resistant native task
is retained until it actually completes and its exception is consumed.

## Core watchdog

`LiveLifecycleWatchdog` runs independently of Voice/UI and reads the one durable
unresolved record. It never reserves or starts a primary. It uses Task13A's CAS
claim: an explicit uncertain primary is immediately eligible; another primary or
reaper is eligible only after its Core-authored lease deadline. A claim changes
owner kind and epoch. The watchdog renews when the lease reaches half-life and
again immediately before every provider attempt. The configured attempt budget
cannot exceed half the lease, leaving a scheduling and persistence margin.

An expired reservation whose start marker is false is finalized directly from
`UNKNOWN_REAP_REQUIRED` with `START_NOT_SENT`, without provider traffic. A true
marker with no retained provider ID remains unresolved indefinitely because no
documented lookup exists. A known identity is transitioned to `STOPPING`, renewed,
then passed to the sideband closer. Only the matching receipt calls Task13A
`finalize`; every ambiguous provider outcome returns to
`UNKNOWN_REAP_REQUIRED`, renews ownership, and schedules exponential retry
between configured positive minimum and maximum delays.

If SQLite fails before or after committing the terminal record, the exact typed
receipt remains in the watchdog's bounded memory slot. Later cycles reconcile
that receipt against the logical session and retry persistence without another
provider close. A committed-but-lost response is detected from the durable
STOPPED receipt and clears the memory slot idempotently. Diagnostics contain
logical session, lifecycle state, owner kind/epoch, revision, typed close reason,
usage seconds, attempt count and exception class only. They exclude credentials,
provider identity, payloads and exception messages.

Core starts the watchdog after SQLite initialization and stops it before closing
the repository. Shutdown wakes it for one last bounded reconciliation cycle.
The stop path applies one total 250 ms budget by default, then cancels and
detaches a resistant task without a second wait; the retained task prevents a
concurrent recovery attempt and its eventual exception is consumed.

## Verification and limits

Permanent provider-fake tests cover reader-before-close ordering, exact outgoing
commands, matching terminal receipts, wrong ID/reason/usage, EOF, timeout,
HTTP-like failures, malformed/duplicate/non-finite/oversized JSON, transport
cleanup resistance, cancellation, claim races, lease renewal, bounded backoff,
pre-start release, SQLite failure before and after terminal commit, exact receipt
retry without a second close, privacy-safe diagnostics and bounded shutdown.
No real provider was contacted.

`JarvisCoreApplication` accepts an injected `live_sideband_closer` and owns the
watchdog lifecycle. At the Task13B boundary `app.py` did not yet construct that
adapter. Task13C now supplies it from the existing OpenAI credential; the 13B
transport behavior itself remains verified through controlled provider fakes.

Sideband attachment after loss and replay of a missed `session.closed` remain
unverified provider behavior. Attach 404/401/429 and exhausted retries never
prove closure. The in-memory receipt survives SQLite failure only while Core is
alive; a simultaneous process crash before durable commit loses that receipt,
leaves the Task13A record unresolved and requires another supported recovery
attempt. A machine or process that is not running cannot execute this watchdog.
