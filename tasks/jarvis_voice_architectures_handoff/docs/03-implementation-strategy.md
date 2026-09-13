# Implementation Strategy

## Principle

Refactor around a stable JARVIS-owned contract first, but integrate GPT-Live early enough that the contract is validated by a genuinely different provider/session model rather than overfitted to Realtime.

## Phase A — Baseline and contracts

Inventory current code; define architecture config/capabilities; define canonical frontend contract; add actually-spoken/provisional state.

Exit gate: current Realtime behavior can run behind the contract without intentional UX change.

## Phase B — Repair Realtime

Add WAIT/backchannel/preamble/delegation policy; Semantic VAD; freshness-aware speech scheduling; actual-output feedback; non-blocking backend work.

Exit gate: replay of the 11 September failures no longer produces stale FIFO speech or systematic reflex filler.

## Phase C — Front Brain experiment

Define sidecar contract; add Luna; consume partial deltas speculatively; keep sidecar parallel/optional; compare against Simple.

## Phase D — Duplex / GPT-Live

Implement client delegation; map quiet/spoken updates; add lifecycle/cost watchdog before general use.

Exit gate: backend work does not block conversation and no billable Live session can remain silently active.

## Phase E — Settings and observability

Architecture-aware Settings, prompt inspector/editor, Live status/Stop/timer, comparable session metrics.

## Phase F — Benchmark and rollout

Run identical scenarios across all modes and choose provisional defaults based on measured UX/cost/reliability. Keep alternate modes for regression and future model comparisons.

## Migration rule

Do not delete old paths until the equivalent adapter path passes replay and contract tests. Keep changes reversible and avoid mixing unrelated UI/core/provider refactors in one slice.

## Task11 implementation boundary

The bridge now reuses JobService with atomic source-bound acceptance, authenticated bounded conversation APIs and a separate configured CLI worker. The production controller can delegate the exact admitted operation while direct conversation continues; it does not submit arbitrary provider text as authority. Replay after Core restart is deliberately disabled: nonterminal Jobs become interrupted. Frontend replacement leaves Core-owned work active. Validate the controlled long-running composition, exact dependency freshness, cross-connection deduplication, post-COMMIT caller cancellation, storage/projection failures and native cleanup before rollout. [Core evidence](11-core-back-brain-evidence.md) and [runtime evidence](11-runtime-implementation-evidence.md) record the actual implementation, commands and limitations; Task12 will supply Live advisory references without broadening their execution permission.
