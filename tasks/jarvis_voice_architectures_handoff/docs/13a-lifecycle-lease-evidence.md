# Task13A — durable Live lifecycle lease

Implementation slice, 2026-09-12. This slice defines Core ownership and durable
state only. It does not open a provider session, attach sideband, run a watchdog
or idle loop, install shutdown hooks, or expose UI. Those are Task13B and later
integration concerns.

## Contract and authority

`jarvis/domain/live_lifecycle.py` defines a strict version-1 record and the
provider-neutral states `STARTING`, `ACTIVE`, `IDLE_CANDIDATE`, `STOPPING`,
`STOPPED`, and `UNKNOWN_REAP_REQUIRED`. Operational loss can converge from every
nonterminal operational state to `UNKNOWN_REAP_REQUIRED`. Before any provider
start send, Voice must call the CAS `mark_start` operation. A reservation whose
marker is still false can be finalized with durable `start_not_sent` evidence;
once true, an attempt without a provider ID remains unresolved because no lookup
API is known. `STOPPED` is accepted only through `finalize` with either that
pre-send proof or `provider_session_closed` evidence matching the durable
provider session ID. `provider_session_closed` also requires the provider's
strict, finite, nonnegative final usage value (zero is valid). Missing or
malformed final usage leaves the record unresolved. `start_not_sent` requires
no provider ID, no provider usage, and zero active seconds.

The durable record contains the logical session ID, optional provider session
ID, current owner incarnation, owner kind and fencing epoch, the durable
start-may-have-been-sent marker, heartbeat and lease deadline,
creation/update/state-entry/activation/stop timestamps, local active seconds,
cumulative provider usage seconds and finality, close reason, revision and
schema version, typed closure evidence, and the durable type of the last
successful mutation. IDs are printable UTF-8 text bounded to 128 characters. Usage
must be finite, nonnegative and at most ten years. Lease intervals are positive
and at most 300 seconds. Datetimes are timezone-aware and constrained to
years 2000–2200. Payload decoding rejects missing, additional and malformed
fields.

`LiveLifecycleService` exposes `reserve`, `mark_start`, `bind`, `heartbeat`, `transition`,
`usage`, `status`, `claim_reap`, and `finalize`. Every mutation is fenced by
logical session, owner incarnation, owner epoch and expected revision. Exact
retries after an ambiguous response require the immediately preceding revision,
matching identity, matching operation result, and the corresponding durable
`last_operation` receipt. This prevents a stale heartbeat retry from mistaking
an unrelated usage or transition commit for its own acknowledgement. A reaper claim increments
the owner epoch atomically and changes owner kind from `primary` to `reaper`;
stale Voice owners cannot update the claimed record. An explicitly uncertain
primary may be claimed immediately. A different reaper cannot steal an existing
reaper claim until its durable deadline expires; an exact same-claim retry is
idempotent.

Core supplies every lifecycle timestamp and computes every deadline from an
injected monotonic test clock or the UTC system clock plus a fixed bounded lease
interval. Protocol callers cannot submit timestamps or deadlines. The service's
admission callback blocks reservation, the pre-send marker, and transition to
`ACTIVE` while Core is not ready. Status and cleanup remain available, including
late binding of a provider ID already returned after shutdown began, transitions
to `STOPPING` or `UNKNOWN_REAP_REQUIRED`, reaper claim, and finalization.

SQLite stores all attempts and enforces a partial unique index over the one
nonterminal global lease. `BEGIN IMMEDIATE` covers reservation and revision CAS,
so separate repository connections cannot both reserve or claim. An expired or
uncertain row is retained and continues to block reservation. It can only move
to a different owner through `claim_reap`; expiry never deletes, stops or
replaces it.
The primary key, projected state, and projected revision are validated against
the strict JSON record on every lifecycle read and CAS; any disagreement fails
closed and cannot hide or release the global unresolved slot. The current
implementation validates all historical terminal rows while reserving or finding
the unresolved row. That scan is unbounded in the number of completed sessions;
bounded archival or a dedicated singleton slot remains a storage follow-up.

The authenticated local protocol exposes the same nine operations below
`/v1/live/sessions`. Bodies have exact key sets and typed responses decode back
to `LiveSessionRecord`. Conflicts return stable HTTP 409 codes; malformed input
returns 400. No provider request or provider wire type crosses this interface.

## Observability and test contract

Normal durable mutations emit `live.lifecycle.<action>` through the injected
`DiagnosticSink`, correlated by logical `session_id`, owner epoch and revision.
Rejected CAS operations emit `live.lifecycle.rejected`; storage failures emit
`live.lifecycle.persistence_failed` with a stable exception type only. Records,
provider payloads, owner incarnation values, credentials, audio and transcript
content are absent from diagnostics. Journal failures do not change lifecycle
authority.

Permanent tests cover multi-connection reservation, restart persistence,
owner/epoch/revision fencing, invalid transitions, expired-lease blocking,
unique reaper claims, confirmed terminal evidence, monotonic usage, SQLite
failure before commit, ambiguous reserve/start-marker/CAS responses after commit and exact retry,
malformed/bounded records, HTTP round trips and strict ingress. The repository
does not include the separate LogBroker CLI referenced by the generic coding
skill; this project’s canonical `DiagnosticSink`/`RuntimeJournal` seam and
recording test sink are used instead.

## Limits retained for Task13B

No timer in this slice renews or expires a lease. No code sends `session.start`,
`session.close` or a sideband attach. A known provider ID is durable recovery
input, not proof that attachment or closure will succeed. A crash after provider
start transmission but before `bind` remains conservatively unresolved. The
watchdog must consume this authority without weakening its CAS or interpreting
EOF, timeout, 404, transport close, UI state, silence or lease expiry as
provider-confirmed `STOPPED`.
