# Task18 orchestrator review

Accepted 2026-09-13 with no open P0/P1/P2 finding.

The initial review challenged five material areas: an acknowledgement could
hide useful-answer latency; Core events could leak across restarted frontends;
surface/analysis/backend usage was incomplete; quality counters inferred facts
that traces did not prove; and a partial report write could not be retried.
It also found provider time inside queue-wait measurements, free-form notes in
reports and permissive boolean pricing versions. Each finding received a direct
regression test and was repaired before acceptance.

A second review found that Back Brain token usage was dropped before Core and
that direct conversation dispatch ordering and activation retry behavior needed
stronger proof. The worker now emits a bounded correlation-safe usage event,
and the tests observe dispatch before provider entry and prevent a pending
report from being replaced.

The final adversarial pass caught two cross-process cost issues. Duplex uses
non-authorizing speculative work without a Core source correlation, so its
usage is now joined through immutable session provenance. Core's observed
provider/model identity is retained and must match the configured component
before a price can be applied. A real restricted-worker/Core-journal/recorder
test proves the Duplex path; a mismatch test proves that misleading cost is
withheld.

The release suite also exposed a device-lock race: an output could become stale
while waiting for PortAudio yet still announce `speaking`. A pre-write readiness
check now waits behind the device lock without crossing the write boundary;
admission is checked again after the async callback and immediately before the
native write. The check runs only for the first block of an admitted output.

Independent final verdict: **ACCEPT**, no remaining P0/P1/P2. The exact metric
contract and report path are documented in `08-benchmark-plan.md`.
