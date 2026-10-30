# Preview liveness artifact review — source only

2026-10-30, product full-gate revision `97d56f11`. Reviewed `preview.py`, reused
S05 LiveAcceptance seed, canonical WorkStateStore/domain, public agent reader,
BlockingWorker/JobCore fixture and JobService execution/cancel path. No runtime,
browser, test or model invoked; preview remains stopped. No code change made.

## Duration and status semantics

- Preview default is **600 seconds after ready**. At15 minutes, a default
  invocation has intentionally stopped and its URL is no longer available.
  The manifest records ready/expiry/stop timestamps and bounded stop reason.
  For a Human likely arriving15 minutes later, PM must explicitly choose a
  longer duration, e.g `--duration 3600` or the allowed maximum7200. This is
  server lifetime, not a Work State heartbeat/fixture TTL.
- Core WorkStateStore has **no age-based heartbeat TTL** for active entries.
  Its module doc explicitly says a disappeared producer's active items remain
  active until producer replacement; active entries are never evicted under
  capacity pressure. `snapshot/current_snapshot` only sort existing active and
  finished records, without aging them. S05 seeds parent/child directly through
  canonical observations, with no periodic producer replacement.
- Public AgentDetail reads canonical state without an updated_at age filter.
  Therefore, while the owned preview Core remains alive, the seeded parent
  and child do not unexpectedly become unknown15 minutes later. Their
  status/activity/progress are **synthetic QA facts**, not a successful model
  execution or live external provider heartbeat. The manifest explicitly
  labels synthetic content and zero model requests. Elapsed time continues
  from their seeded canonical started_at; it is not model activity evidence.
- The Core `demo` job has a **genuine controlled worker** owned by this
  preview: BlockingWorker.execute awaits its own Event indefinitely.
  JobService._run_worker directly awaits execute and imposes no execution
  timeout on this worker. It stays running at15 minutes until the Human uses
  canonical Stop, the preview stops, or the owned Core otherwise stops. The
  five-second user-cancel settle bound and viewer cancellation-confirmation
  deadline are not job execution TTLs. Stop produces an actual JobService
  terminal observation and end timestamp.
- An intentional Core restart empties live Work State (durable mission stays),
  and job recovery follows canonical interrupted semantics. That is a
  deliberate fixture-driving path, not spontaneous heartbeat expiration.
  Preview shutdown finally cancels/closes only its own fixture objects; no
  external runtime or process tree is touched.

## Conclusion and operational limit

No QA liveness fix or synthetic periodic heartbeat is necessary under these
actual semantics. Do not add fabricated external live authority to keep a
demo looking active. The useful real execution control is the owned blocking
Core job; the Claude parent/child intentionally demonstrate labeled public
fixtures. A long Human review needs an explicitly long **server duration** and
the observed manifest URL. This conclusion is a code-path audit, not a15-minute
or two-hour soak test, and should not be described as one.
