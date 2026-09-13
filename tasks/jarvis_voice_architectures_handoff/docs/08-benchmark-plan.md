# Benchmark Plan

## Initial configurations

- Simple: GPT-Realtime-2.1 Mini
- Simple: GPT-Realtime-2.1
- Simple: existing compatible Gemini voice model(s), once discovered
- Front Brain: Realtime Mini + GPT-5.6 Luna
- Duplex: GPT-Live 1 + JARVIS client delegation

## Scenario set

Short acknowledgement; short direct question; pause mid-sentence; long reflective monologue; late correction; long backend task; backend result during a new topic; user barge-in; bus/background noise; output stall/reconnect; mode switch; GPT-Live idle/manual stop.

## Metrics

Every activated frontend writes one JSON record and one text summary under
`<runtime_root>/benchmarks/voice-sessions/`. Filenames contain a sanitized
session ID plus its hash. The JSON contract is
`jarvis.voice_benchmark.session`, schema version 1. Every architecture emits the
same keys; unavailable evidence is represented by zero samples and `null`
aggregates, never an invented duration.

Responsiveness and latency keys (milliseconds):

- `provider_first_pcm_ms`: user speech start to the first PCM block received
  from the provider.
- `playback_attempt_ms`: user speech start to the first local playback attempt.
- `time_to_first_audible_reaction_ms`: user speech start to the first successful
  native device write. This is not provider receipt or full playback proof.
- `time_to_first_useful_answer_ms`: the same successful-write boundary, limited
  to direct conversation or brain speech classified as progress, result,
  question, or error; acknowledgements do not qualify. A successful first write
  is retained per output, so an audible acknowledgement cannot consume the later
  useful-answer sample for the same user speech segment.
- `frontend_blocking_ms`: completed transcript to Core turn acceptance.
- `delegation_latency_ms`: accepted client/back-brain delegation to its traced
  terminal append/result state, joined by job ID.
- `speech_queue_wait_ms`: canonical speech queue admission to frontend dispatch,
  measured on a monotonic clock before awaiting any provider command.
- `brain_speech_to_first_audio_ms`: brain speech request to its first audio;
  this remains separate from queue wait.
- `backend_first_progress_ms` and `backend_result_ms`: accepted backend work to
  first public progress and successful completion.
- `user_interrupt_stop_ms`: confirmed interruption to local output stop.
- `device_drain_ms`: checked native drain operation duration for complete output.

Quality/reliability counters are `backend_task_started`,
`backend_task_result`, `stale_cancellation`, `user_interruption`,
`false_or_rejected_barge_in`, `output_stall`,
`unnecessary_acknowledgement`, and `intended_spoken_divergence`. Raw counts and
manual `pass`/`fail`/`uncertain` annotations remain separate; no composite score
is computed.

The four playback boundaries stay distinct in trace evidence:
`voice.latency.provider_first_pcm`, `voice.latency.playback_attempted`,
`voice.latency.first_audible_write`, and `audio.drain_result`. A rejected or
failed write can produce the first two but cannot produce
`first_audible_write`; only a complete checked drain proves the full output.
`voice.latency.output_first_write` records the same successful-write boundary
for each output so useful-answer latency remains observable after a prior ACK;
`first_audible_write` remains the unique first reaction for the user segment.

Each report records architecture, provider/model IDs for the surface, optional
Front Brain analysis, and configured backend components, configuration ID,
prompt revision/fingerprint evidence (including analysis calls), a session
fingerprint, wall/session duration, Core-owned Live active seconds, and
cumulative provider duration/token usage when exposed. Realtime surface,
Front Brain analysis, and correlation-bound Back Brain provider usage remain
separate component records; a backend that exposes no token counters remains
explicitly unavailable, never zero. Monetary values are
explicitly estimates. They are omitted unless pricing metadata exactly matches
the model and schema version 1 and includes currency, source and a timezone-aware
effective date. Surface pricing uses a nonnegative per-minute rate. Analysis or
backend pricing can instead provide nonnegative input/output rates per million
provider tokens. Provider-reported duration is preferred to lifecycle active
time.

Core events have no frontend session ID. The reporter admits them only when a
session-bound Voice event proves the same correlation, then admits result and
latency evidence only for work started inside that report window. This prevents
a restarted architecture from claiming an earlier frontend's work. Voice-side
events require the exact frontend session ID. Free-form
quality notes are stored only as length and SHA-256 fingerprint. A spoken
divergence requires complete playback evidence with independently confirmed
text; generated/intended differences alone do not count. Provider VAD advisory
signals are not classified as false interruptions. An unnecessary
acknowledgement is counted only from an explicit failed benchmark annotation,
because delivery evidence alone cannot decide whether an ACK helped. The
readable summary is replaced first and the JSON record last as the report commit
marker. A failed write freezes its terminal timestamps/evidence and retries that
same report before a later activation can replace its recorder.

## Decision criterion

Do not select a default on average latency alone. Compare user-facing quality, billable idle cost, false interruptions, task continuity, and operational reliability.

## Frozen offline closeout run — 2026-09-13

Run the production-seam suite with:

```powershell
.venv\Scripts\python.exe scripts\benchmark_voice_architectures.py --output-root tasks\jarvis_voice_architectures_handoff\artifacts\task20-offline
```

Suite `voice-common-v1` contains 14 ordered scenarios and has fingerprint
`a12285b93fd158a29e7906b68b1959b718a5b39ee387e72adf553ee3ddb2b6a2`.
Its code contract fixes every scenario ID, action, parameter, invariant and
allowed pytest evidence node. The runner executes 16 exact selectors, which
expand to 26 production-seam pytest cases, before writing any report. Failed,
skipped/reclassified or incomplete evidence
cannot produce an accepted report.

The compared explicit configurations are Simple with
`gpt-realtime-2.1-mini`, Front Brain with `gpt-realtime-2.1-mini` plus
`gpt-5.6-luna` at low reasoning, and Duplex with `gpt-live-1`, client
delegation and a 60-second idle setting. Compatibility sessions are excluded
from architecture comparison; their `legacy`/`continuous_brain` migration and
operational labels are verified separately.

The offline run proves one architecture-specific direct conversation for
Simple and Front Brain, one representative delegated Duplex conversation, and
11 shared production-policy contracts. Quiet ambient and long monologue remain
unrun for every mode; a direct-question scenario remains unrun for Duplex.
Task18-shaped reports contain no live latency samples and no provider usage or
cost. Therefore no architecture ranking or new default is selected.

The current Settings Front Brain preset resolves to full Realtime plus Luna,
whereas this controlled comparison deliberately freezes Realtime Mini plus
Luna to isolate architecture overhead. The preset is not changed or described
as a benchmark winner.

Machine and readable results are under
`artifacts/task20-offline/benchmarks/voice-cross-architecture/`; the decision
and detailed limitations are in `20-benchmark-results.md`.
