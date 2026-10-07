# Slice 11 — End-to-end Presentation hardening

## Goal

Prove the complete Presentation experience under realistic deterministic scenarios and eliminate regressions, privacy leaks and latency hazards.

## Context

Presentation spans audio context, mode state, Brain reasoning, sub-agents, speech, Tool Brain, scene/prefab and observability. Unit correctness alone is insufficient.

## Canonical Concepts

End-to-end scenario, deterministic replay, latency budget, privacy boundary, explicit-turn priority, SIMPLE regression safety.

## Scope

### In Scope

- Build/reuse deterministic presentation transcript/audio fakes and scenario fixtures.
- Run the scenario matrix in `docs/04-testing-and-quality.md`.
- Validate SIMPLE mode regression safety.
- Validate mode transitions, cancellation, stale-context behavior, prepared-resource reuse, contradiction attention, and recording boundary.
- Measure explicit-turn latency impact and background concurrency/resource use.
- Run full required QA composition and remediate findings.

### Out of Scope

- Adding unrelated new Presentation features.
- Per-user interruption preference learning.
- REUNION behavior.

## Dependencies

- `03-control-center-mode-ui`
- `04-ambient-presentation-lane`
- `05-presentation-working-set`
- `06-background-intelligence-arbitration`
- `07-manifestation-policy`
- `08-tool-brain-integration`
- `09-scene-prefab-integration`
- `10-observability-attention`

## Implementation Steps

1. Assemble deterministic end-to-end fixtures/replays.
2. Execute required scenario matrix.
3. Measure/compare explicit-turn latency and resource usage.
4. Run QA: `qa-verification`, `code-review`, `runtime-validation`, `agent-trace-analysis`.
5. Fix every regression introduced by the task.
6. Perform final Human validation only after machine QA is clean.

## Files Likely Touched

E2E/runtime tests, fixtures, performance tests, docs; product code only for remediation.

## Architecture Constraints

Do not weaken authority/privacy boundaries to make tests pass. SIMPLE must remain the baseline behavior outside PRESENTATION.

## Automated Validation

Full Presentation scenario matrix plus existing Jarvis regression suites and trace assertions.

## Acceptance Criteria

- All deterministic scenarios pass.
- Ambient speech never gains unintended command authority.
- Explicit requests remain highest priority.
- Presentation mode alone does not create durable recordings.
- Visual actions use Tool Brain and canonical scene/prefab paths.
- SIMPLE behavior is not regressed.
- Required QA has no blocking findings.

## Documentation Updates

Finalize operator/developer docs, known limitations and validation evidence references.

## Handoff Notes

Coding/runtime/frontend Slice as required by fixes: load all mandated skills for the affected surface. Human check only after automated QA is exhausted.


## Slice 00 contract (binding)

Scope in:
- **Deterministic scenario suite.** `tests/integration/test_presentation_scenarios.py`, through the real `PresentationComposition` with fake hub, `TranscriptionBackend`, core, CLI runner and scene tools. It covers scenarios 1–12 of `docs/04-testing-and-quality.md`, with these mappings:
  - (2) deictic → SHOW_PREPARED intent, no filler speech;
  - (5) the named hit goes through the P5 projection (brain double reveals by `object_id`);
  - (6) stale enriched context never overrides a fresher tail;
  - (9) explicit turn preempts speculative and calls `withdraw_speculative` (direct path = 0);
  - (10) exit stops lane and scheduling within one drain;
  - (11) no recording artifact or file beyond the ledger;
  - (12) restart: mode re-adopted (P1), no old ambient replayed as a turn.
- **SIMPLE regression.** The suite also runs with mode SIMPLE: bridge, scheduler and brief byte-identical.
- **Privacy.**
  - Fix Issue 002: `voice.transcript_dropped` messages at `realtime_audio.py:4565-4568,4621-4624` become length + reason, in every mode.
  - Planted-phrase sweep over every durable sink: `trace.jsonl`, errors, state DBs, conversation events store, staged ledger, CC journal.
- **Latency/concurrency.** Explicit-turn admission latency with vs without ambient load and 2 running preparations (fakes + one real-host measurement); pool never exceeded.
- Full unit suite vs the agent-0 baseline, diffed name by name.
- Final docs: `docs/presentation-mode.md` limitations (R6), operator runbook in `OPERATIONS.md`, `ACCEPTANCE_STATUS.md`.
- Amend the HV-PRESENTATION-E2E-01 instruction to include the AUDIO/SPEECH/PRIORITY sub-checks (R8).

**Deferred acceptance items** (listed, not run): "visual actions use Tool Brain" (08) and "prefab-backed scene resources" (09). Today's evidence is "visual actions go through `PresentationDisplaySink` → `DirectSceneDisplaySink`".

Scope out: new features; Issue 001; Issue 003 (`barehands_replay.py:144`, pre-existing); REUNION.

Files: new `tests/integration/test_presentation_scenarios.py` and fixtures, `jarvis/runtime/realtime_audio.py` (Issue 002), docs above; product code only for remediation.

Acceptance:
- 12 scenarios green, plus the SIMPLE-identity variant.
- `test_no_planted_room_phrase_in_any_durable_sink`.
- `test_dropped_transcript_trace_carries_no_text` (SIMPLE and PRESENTATION).
- Latency report attached: p50/p95 delta within 10 % of the no-ambient baseline on fakes; host numbers recorded.
- Full suite: failures identical to the baseline set.
- Required QA without blocking findings.

QA tier: critical. Passes:
- qa-verification + code-review + runtime-validation + agent-trace-analysis (real CLI on scenarios 3 and 5);
- mutation: ≤10, foreground, on the scenario oracles for authority, preemption and the privacy sweep.

Human check: HV-PRESENTATION-E2E-01, last, after everything machine-side is green. It supersedes HV-PRES-AUDIO-01, HV-PRES-SPEECH-01, HV-PRES-PRIORITY-01 and HV-PRES-E2E-01. Restart the JARVIS stack from this branch first.

Not yours: 08 and 09 items; baseline failures.

Depends on: 03, 04, 05, 06, 07, 10.

Documentation: final Level 3 for every concept in `docs/05-documentation-levels.md`, except the Tool Brain and Scene/Prefab rows (deferred).

## Amendement 2026-10-07 : mesure sur hote reel differee

Amende, sans le reecrire, le texte d'origine des criteres « Latency/concurrency » (« fakes + one real-host measurement ») et « Acceptance » (« host numbers recorded »).

- La mesure de latence sur hote reel n'est pas faite dans cette Slice : elle est differee vers **HV-PRESENTATION-E2E-01**, sous-controle **PRIORITY** (point humain).
- Ecart au critere d'acceptation **accepte par le PM**. Preuve retenue pour la Slice : mesures sur fakes (voir LOG.md, entree de rework e9e8119, B1).
