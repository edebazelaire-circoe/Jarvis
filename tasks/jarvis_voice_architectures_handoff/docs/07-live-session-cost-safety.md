# GPT-Live session cost and safety controls

GPT-Live is billed by active session time. The durable lifecycle is therefore
Core authority, independent of Voice, audio devices and the Control Center.

## Durable lifecycle

The states are `STARTING -> ACTIVE -> IDLE_CANDIDATE -> STOPPING -> STOPPED`.
`ACTIVE` may return from `IDLE_CANDIDATE` if validated activity resumes before
the close request. Any transport loss, EOF, timeout, process crash, invalid
terminal event or unconfirmed close enters `UNKNOWN_REAP_REQUIRED`. Only two
proofs release the global Live slot:

- `START_NOT_SENT`, when Core's durable send marker is false; or
- a matching `session.closed` receipt with a documented reason and finite,
  nonnegative final `usage.seconds`.

Socket EOF, an HTTP error, a close request, an empty audio queue and UI state do
not prove `STOPPED`.

Each record stores the logical and provider session identities, primary/reaper
owner incarnation and epoch, heartbeat/deadline, timestamps, active and provider
usage seconds, close reason/evidence, last operation and CAS revision. SQLite
admits one global nonterminal lease. An expired or uncertain lease blocks a new
primary until a uniquely claimed reaper produces terminal evidence.

## Primary startup and stop

Voice validates the exact bounded startup payload, reserves Core ownership,
opens the primary transport and its only reader, commits
`start_may_have_been_sent`, then sends `session.start`. A strict
`session.started` identity is bound durably and Core reaches `ACTIVE` before the
frontend or microphone can accept data. Heartbeat, bind, usage, idle and terminal
CAS operations share one serialized owner. A stale owner is fenced and can no
longer send audio or context.

Stop is coalesced. Voice first latches stop and owns the Core transition, but a
slow or failed SQLite/HTTP mutation cannot delay the urgent `session.close`.
The reader validates and persists `session.closed` before exposing local
`STOPPED`. Cumulative usage replaces the prior provider counter; it is never
summed. Terminal local elapsed time is frozen for exact retry after a committed
write whose response was lost. Application exit uses `shutdown`, validated idle
uses `idle`, fatal frontend failure uses `error`, and the future mode-switch
orchestrator can call the existing `switch` cleanup hook.

## Semantic idle

`DuplexVoiceConfig.idle_timeout_s` is the effective timeout, with a strict finite
range of 5–3600 seconds and provisional default 60. Legacy timeout zero never
disables Duplex idle supervision.

The clock resets on validated addressed user activity and on a real local audio
device write. At expiry, close is eligible only when the public typed
`LiveIdleEvidence` says microphone and device state are known, the user is not
speaking, and no output/device work is pending, and when the speech controller
has no bounded immediate continuation. Microphone evidence requires a
`CaptureProcessor` classification callback observed within 2.5 seconds;
`near_end_observed` includes both the latest classified near-end frame and its
speech latch. Raw, unclassified PCM and a stalled callback become unknown.
Provider output remains pending until its local audio buffer receives a checked
native drain; this proves device quiescence without inventing provider response
finality. A drain that finishes after the bounded foreground wait is reconciled
by an owned task and applies only to unchanged audio epochs, received-byte
generation and an empty bridge queue. Immediate continuation exposes an event-loop deadline bounded by its
candidate TTL and output timeout. Unknown capture/device state fails closed.
Backend jobs, generic progress, heartbeat and usage do not reset or defer the
Duplex timeout. A durable `IDLE_CANDIDATE` transition precedes the provider
close request.

Visual heartbeat publication is best effort and runs independently from idle
supervision, so a locked VisualSignalBus file cannot keep a billable session
alive.

## Recovery and shutdown

Core constructs the OpenAI sideband closer only when the existing OpenAI
credential is available; construction makes no provider request. The watchdog
does no work at Core start or on status/config reads unless a durable unresolved
record exists. For a known ID it attaches at the documented sideband URL,
installs its reader, sends exactly `session.close`, and applies the same strict
terminal receipt contract. Ambiguous outcomes remain unknown and retry with a
bounded backoff while preserving reaper fencing.

Core stops the watchdog before closing SQLite. Voice shuts down its session and
audio ownership before closing its Core client. Both paths are bounded and
retain uncertain state for later reconciliation rather than displaying a false
OFF state.

No fixed monetary price is embedded. Diagnostics use typed states, reasons,
durations, revisions and exception classes without credentials, provider
payloads, transcript content or provider session IDs.

## Control Center indicator and Stop

The Control Center polls Core's current nonterminal lifecycle record. Starting,
active, idle-candidate, stopping and reap-required records all keep a persistent
red/orange banner above the global face, outside Settings. The timer combines
Core's durable `active_seconds` floor with its authoritative `activated_at`;
before activation it reports session time from `created_at`. A failed Core read
retains the last unresolved record and marks it stale. If no prior record is
available, Core unavailability still renders an `ÉTAT INCONNU` warning because
absence of a readable record is not proof that no billable session exists.

The Stop button writes an atomic, session-bound request on the local runtime
bus. Voice consumes each request ID at most once and calls its existing
idempotent `mute(USER)` path. Its accepted/failed receipt describes only command
handling. The banner disappears only after a successful Core read reports no
nonterminal session; a button click, Voice receipt, stale heartbeat or browser
timer never claims `STOPPED`. Reap-required and failed commands expose retry.
When the Voice process is offline and the session identity is unavailable, the
banner remains visible and directs attention to Core instead of offering a
stop command that cannot be routed truthfully.

Voice publishes only scalar, short-lived UI context: logical session ID, model
ID, runtime state and idle timeout/countdown. Core lifecycle fields remain the
authority. The idle countdown appears only for the matching Duplex session and
says when the timeout is waiting for a semantically safe close point.

Provider usage is shown separately when Core has received it. Cost remains
hidden unless `control-center-settings.json` contains this exact optional
metadata object:

```json
{
  "live_pricing": {
    "schema_version": 1,
    "model_id": "gpt-live-1",
    "currency": "USD",
    "price_per_minute": 0.0,
    "source": "provider price sheet reference",
    "effective_at": "2026-09-01T00:00:00+00:00"
  }
}
```

All six fields are required, `effective_at` must carry a timezone, the price
must be finite and nonnegative, and `model_id` must match the running Voice
session. Invalid, partial or mismatched metadata produces no amount. An amount
is always labelled `estimation`, with its source; provider usage is its preferred
basis and elapsed Core time is the fallback.

## Provider limits

Successful sideband reattachment after loss of the primary socket and replay of
a missed terminal event remain unverified. Attach 404/401/429 does not prove
closure. A terminal receipt held only in process memory can be lost if the
process crashes during a simultaneous SQLite outage; the durable record stays
unresolved and another supported recovery attempt is required.
