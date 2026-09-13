# Task18 — per-session benchmark evidence

Accepted 2026-09-13.

Every attempted Voice frontend session now owns one versioned benchmark
recorder. It writes a machine-readable JSON commit record and a readable text
summary under `<runtime_root>/benchmarks/voice-sessions/`. The schema exposes
the same latency samples and quality counters for Simple, Front Brain and
Duplex; missing evidence remains unavailable rather than becoming a measured
zero.

The instrumentation keeps provider PCM receipt, local playback attempt, first
successful native write and checked full-device drain distinct. Useful-answer
latency is measured per output, so an earlier acknowledgement cannot consume
the later result sample. Queue wait stops before the provider call. Backend
ready/result latency remains separate from frontend and speech-queue latency.

Reports bind Voice events to the exact frontend session. Core events require a
Voice-admitted correlation, while restricted Duplex analysis usage can use its
immutable conversation/session provenance. Realtime, Front Brain and Back Brain
usage remain separate component records. Back Brain traces retain only bounded
token counters and the provider/model identity observed by Core. A mismatch
with Voice's configured backend is explicit and disables pricing. Estimates
require a strict schema version, exact model match, source and timezone-aware
effective date.

Quality counters require observable evidence: advisory VAD signals are not
false interruptions, an unnecessary acknowledgement requires an explicit
failed annotation, and intended/spoken divergence requires complete playback
with independently confirmed differing text. Annotation text is replaced by
its length and SHA-256 fingerprint.

Report writes are retryable. The readable file is replaced first and JSON last
as the commit marker; a failed terminal write freezes its timestamps and input
evidence. A later activation retries that report and cannot overwrite the
recorder while it remains pending.

Verification before the final release gate:

- Focused remediation gate: **95 passed**.
- Audio/admission/metrics/Back Brain gate: **157 passed**.
- Independent final review: **ACCEPT**, with **142 targeted tests passed** and
  no open P0/P1/P2 finding.
- Final release: **3093 passed, 5 skipped in 331.34 s**; all release checks
  passed. An earlier run surfaced one delayed SQLite `ResourceWarning`; the
  affected test passed alone, explicit per-test connection tracking found no
  leak, and the clean `-W error` release rerun did not reproduce it.
- Python compilation and `git diff --check` passed through the release gate.

No provider, billable session, microphone or speaker was used. Provider usage
and cost evidence therefore remains synthetic until Task20's explicitly
authorized live benchmark.
