# Task 09 — Build repeatable speaker-engine benchmark harness

## Goal

Compare local/commercial speaker-verification candidates on identical audio and choose based on measured JARVIS quality.

## Context

The user prioritizes quality and is open to B2B engines if their advantage is real, but wants to avoid sales/licensing friction without evidence.

## Scope
### In Scope
- engine-neutral replay harness;
- adapters for the currently available baseline and any immediately accessible candidates;
- scenario manifest;
- latency/false accept/false reject/CPU/RAM summary;
- threshold sweep support;
- machine-readable result output.

### Out of Scope
- fabricating access to commercial SDKs;
- vendor selection without data.

## Dependencies

Task 03; preferably Tasks 04–08 for end-to-end metrics.

## Required Skills
- `/caveman`
- `/coding-guideline`

## Implementation Steps

1. Implement a benchmark interface against the same `SpeakerVerifier` contract or a thin offline equivalent.
2. Support WAV/PCM fixtures with labels and time intervals.
3. Keep private recordings outside Git; provide manifest paths and synthetic/redistrutable fixtures in tests.
4. Add threshold sweeps and P50/P95 confirmation latency.
5. Record engine/model/version/preprocessing configuration.
6. If Picovoice/Vivoka/Sensory SDKs are unavailable, leave adapter slots documented rather than faking results.

## Files Likely Touched

- `scripts/benchmark_speaker_verification.py` or project-equivalent
- benchmark manifests/docs
- adapter modules
- tests for metric calculations

## Architecture Constraints

- Same preprocessing for fair comparison unless explicitly testing an ablation.
- No private audio committed.
- Results reproducible from manifest + engine config.

## Testing Requirements

- deterministic metric unit tests;
- threshold sweep correctness;
- missing-file/engine diagnostics;
- result schema stability.

## Acceptance Criteria

- At least one local engine can be benchmarked end-to-end.
- Adding a commercial engine requires only an adapter, not harness changes.

## Documentation Updates

Write benchmark usage and result interpretation guide.

## Handoff Notes

Do not set the production default here unless enough real workstation data exists; Task 14 finalizes.
