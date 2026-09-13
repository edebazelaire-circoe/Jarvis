# Task20 cross-architecture benchmark results

Run date: 2026-09-13.

The accepted offline run is
`offline-voice-common-v1-a12285b93fd1`. Its suite fingerprint is
`a12285b93fd158a29e7906b68b1959b718a5b39ee387e72adf553ee3ddb2b6a2`.
The CLI executed 16 exact allowlisted selectors, expanding to 26 pytest cases,
before committing the JSON and text reports.

| Architecture | Frozen components | Architecture-specific scenarios | Shared contract evidence | Not run | Failures | Representative E2E |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Simple | Realtime Mini | 1 | 11 | 2 | 0 | Passed: direct two-turn conversation, controlled provider/device |
| Front Brain | Realtime Mini + Luna low | 1 | 11 | 2 | 0 | Passed: same direct conversation while Luna remains optional and parallel |
| Duplex | GPT-Live 1, client delegation, 60 s idle | 0 | 11 | 3 | 0 | Passed: Live deltas, non-blocking delegated work and retained Core result |

Shared contract evidence proves architecture-neutral JARVIS policy seams. It is
recorded separately and never counted as a per-architecture pass. The Task18
annotations for this evidence are `uncertain`, while only explicit composition
tests may be `pass`.

The run verified the compatibility projection and correct operational
provenance for `legacy`, `continuous_brain` and explicit `simple`. Compatibility
reports are excluded from the three-way comparison.

No provider session, external network or physical audio device was used. All
live latency fields have zero samples and null aggregates; provider usage and
cost are unavailable. Acoustic and conversational quality, provider
availability, billing behavior and an architecture ranking are unavailable.
Quiet ambient and long-monologue remain unrun for all three modes, and the
Duplex direct-question case remains unrun.

Decision: preserve the current safe `legacy` operational default. Keep Simple,
Front Brain and Duplex switchable. The evidence does not justify a winner or a
change to the current Front Brain UI preset.

Artifacts:

- `artifacts/task20-offline/benchmarks/voice-cross-architecture/voice-common-v1-a12285b93fd1.json`
- `artifacts/task20-offline/benchmarks/voice-cross-architecture/voice-common-v1-a12285b93fd1.txt`
- three Task18 JSON/text session reports under
  `artifacts/task20-offline/benchmarks/voice-sessions/`
- execution trace at `artifacts/task20-offline/trace.jsonl`
