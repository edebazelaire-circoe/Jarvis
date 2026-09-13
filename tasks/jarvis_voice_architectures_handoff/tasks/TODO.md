# JARVIS Voice Architecture — Implementation TODO

## Entry point for implementation agents

This handoff converts the September 11, 2026 voice-session review and follow-up architecture discussion into ordered implementation slices. Start with Task 00. A fresh agent should not need the original chat.

### Mandatory workflow

- Task 00 is the orchestrator. It owns sequence, status, conflict avoidance, documentation consistency, and final reporting.
- For every coding task, load and follow `/caveman` and `/coding-guideline` from `~/ai/skills/` before changing code.
- Read `docs/00-overview.md`, `docs/01-decision-log.md`, `docs/02-architecture-spec.md`, and the current task before implementation.
- Use `docs/current-code-map.md` after Task 01 creates it; paths in task files are intentionally responsibility-based until the real repository map exists.
- Preserve unrelated dirty working-tree changes. Do not commit or rewrite them unless the task explicitly owns them.
- Mark a task complete only after focused tests and its acceptance criteria pass. Record blockers explicitly.
- If repository evidence contradicts a provisional assumption, update docs/decision log and affected future tasks before continuing.

### Locked program intent

- Provide three switchable voice architectures: Simple, Front Brain, and Duplex.
- Use a provider-neutral `VoiceFrontend` boundary and JARVIS-owned conversation/task state.
- Treat actually spoken output as authoritative for what the user heard.
- Make silence/WAIT a legitimate conversational action and eliminate systematic filler acknowledgements.
- Keep long backend work non-blocking and result-oriented.
- Implement GPT-Live 1 client delegation as the principal Duplex target while keeping Realtime baselines benchmarkable.
- Expose architecture-relevant model selection and all JARVIS-controlled prompt layers in Settings.
- Make active GPT-Live billing state prominent, timed, manually stoppable, automatically closable when idle, and guarded by a watchdog.
- Benchmark architecture/model/prompt combinations on common latency, correctness, interruption, stale-output, and cost metrics.

## Task order

- [x] Task 00 — Orchestrate the voice architecture program
  - Path: `tasks/00-orchestrate-voice-architecture-program/TASK.md`
  - Depends on: None. Start here.
  - Status: complete — Tasks 01–20 accepted with independent review, synchronized evidence and final release 3176 passed, 5 skipped (333.76s).
- [x] Task 01 — Inventory current voice, settings, providers, and baseline
  - Path: `tasks/01-inventory-current-voice-stack/TASK.md`
  - Depends on: Task 00 orchestration initialized.
  - Status: complete — code map reviewed; 300 focused baseline tests passed (9.78s), production unchanged.
- [x] Task 02 — Add voice architecture config schema and capability registry
  - Path: `tasks/02-architecture-config-capability-registry/TASK.md`
  - Depends on: Task 01 code map.
  - Status: complete — typed schema/registry reviewed; independent parent gate 180 passed (4.23s). New runtime modes remain inactive.
- [x] Task 03 — Define canonical VoiceFrontend and event contracts
  - Path: `tasks/03-voice-frontend-contracts/TASK.md`
  - Depends on: Task 02 config schema.
  - Status: complete — contract gate 190 passed; 03R repaired six legacy helper imports. Global collection 1992 tests clean, 42 affected tests passed.
- [x] Task 04 — Add conversation state and actually-spoken ledger
  - Path: `tasks/04-conversation-state-spoken-ledger/TASK.md`
  - Depends on: Task 03 canonical contracts.
  - Status: complete — reducer/snapshot reviewed; independent parent gate 243 passed (6.91s), including existing history and recovery regressions.
- [x] Task 05 — Wrap the existing Realtime path in the VoiceFrontend adapter
  - Path: `tasks/05-realtime-frontend-adapter/TASK.md`
  - Depends on: Tasks 03-04.
  - Status: complete — production composition and Core history reviewed; parent release 2113 passed, 4 skipped (226.88s), all release checks green. Real device completion remains mandatory Task07.
- [x] Task 06 — Implement reflex speech gate and WAIT/preamble policy
  - Path: `tasks/06-reflex-speech-gate/TASK.md`
  - Depends on: Task 05 Realtime adapter and Task 04 state.
  - Status: complete — gate/races and documentation reviewed; parent 567 passed (22.07s). Synthetic preambles 6→2 with both long waits retained; Task05 terminal-publication follow-up fixed.
- [x] Task 07 — Improve VAD, interruption, and noise handling
  - Path: `tasks/07-vad-interruption-noise/TASK.md`
  - Depends on: Task 05 adapter; Task 01 inventory of existing owner-recognition plan.
  - Status: complete — all-part/device proof, interruption and native ownership reviewed; parent release 2205 passed, 4 skipped (252.11s), all release checks green. No hardware/live-provider quality claim.
- [x] Task 08 — Add freshness-aware semantic speech scheduler
  - Path: `tasks/08-freshness-aware-speech-scheduler/TASK.md`
  - Depends on: Tasks 04 state and 06 reflex gate.
  - Status: complete — source/chunk admission, durable outcomes and production device sequencing reviewed; parent release 2294 passed, 4 skipped (242.19s), all release checks green. First-pass fixture regressions and duplicate expiry telemetry repaired.
- [x] Task 09 — Define Front Brain sidecar hint contract
  - Path: `tasks/09-front-brain-hint-contract/TASK.md`
  - Depends on: Tasks 02 config, 04 state, 06 gate.
  - Status: complete — strict advisory contract, deterministic consumer and bounded fake reviewed; independent 59-test QA and parent 284-test gate passed. Oversized-number and context-role findings repaired; no provider call or authority added.
- [x] Task 10 — Implement Luna Front Brain sidecar with speculative transcript analysis
  - Path: `tasks/10-luna-front-brain-sidecar/TASK.md`
  - Depends on: Task 09 hint contract and Task 02 capability/config registry.
  - Status: complete — explicit Simple/Front Brain direct composition, optional bounded Luna sidecar and canonical Core admission reviewed. All four Core findings and composition/adapter regressions repaired; parent release 2595 passed, 4 skipped (294.40s), all release checks green. No live-provider or hardware claim.
- [x] Task 11 — Make back-brain work non-blocking and result-oriented
  - Path: `tasks/11-nonblocking-back-brain/TASK.md`
  - Depends on: Task 04 state; current backend map from Task 01.
  - Status: complete — atomic admitted-source jobs, independent owned worker, typed progress/result/cancel, direct delegation tool and source-bound controller ACK reviewed; parent release 2700 passed, 4 skipped (320.97s).
- [x] Task 12 — Implement GPT-Live 1 Duplex adapter with client delegation
  - Path: `tasks/12-gpt-live-duplex-adapter/TASK.md`
  - Depends on: Tasks 03-04 contracts/state and Task 11 non-blocking backend.
  - Status: complete — client-delegated GPT-Live adapter, restricted durable analysis, canonical evidence and conservative stop/playback semantics reviewed; parent release 2765 passed, 5 skipped (299.86s).
- [x] Task 13 — Add GPT-Live lifecycle, idle close, and orphan watchdog
  - Path: `tasks/13-live-lifecycle-cost-safety/TASK.md`
  - Depends on: Task 12 GPT-Live adapter.
  - Status: complete — durable lease/epoch fencing, strict terminal evidence, sideband reaper, primary wiring and validated semantic idle reviewed; parent release 2937 passed, 5 skipped (327.32s).
- [x] Task 14 — Redesign Settings around voice architecture modes
  - Path: `tasks/14-settings-voice-architecture-ui/TASK.md`
  - Depends on: Task 02 schema/registry; adapters available enough for selected choices to be validated.
  - Status: complete — registry-driven architecture panels, explicit atomic persistence, dynamic legacy compatibility and unavailable reasons reviewed; parent release 2996 passed, 5 skipped (332.31s).
- [x] Task 15 — Add prompt registry, inspector, and editor
  - Path: `tasks/15-prompt-registry-editor/TASK.md`
  - Depends on: Task 14 Settings architecture UI; Task 02 config registry.
  - Status: complete — 24-layer/14-program registry wired to actual sends, architecture-scoped Settings inspector/editor, atomic overrides and truthful fingerprints reviewed; final release 3054 passed, 5 skipped (348.03s).
- [x] Task 16 — Add prominent GPT-Live active indicator, timer, Stop control, and cost awareness
  - Path: `tasks/16-live-active-indicator-stop-ui/TASK.md`
  - Depends on: Task 13 lifecycle manager; Task 14 Settings shell.
  - Status: complete — Core-authoritative global banner/timer, idempotent Voice Stop command, retained uncertain states, semantic-idle context and provenance-bound optional cost estimate reviewed; final release 3062 passed, 5 skipped (329.16s).
- [x] Task 17 — Implement safe architecture and model switching with state rehydration
  - Path: `tasks/17-safe-architecture-switching/TASK.md`
  - Depends on: Tasks 04 state, 05/10/12 frontend modes, 13 Live lifecycle.
  - Status: complete — Core snapshot, terminal close gate, supervised Voice restart, bounded canonical/task rehydration and correlated architecture/model/prompt evidence reviewed; final release 3075 passed, 5 skipped (320.42s).
- [x] Task 18 — Add per-session voice benchmark metrics and reports
  - Path: `tasks/18-voice-benchmark-metrics/TASK.md`
  - Depends on: Tasks 04 state, 06-08 conversation policies, 10/12 modes, 13 lifecycle.
  - Status: complete — comparable session schema, canonical delivery/queue/backend instrumentation, correlation-safe component usage and strict versioned pricing reviewed; final release 3093 passed, 5 skipped (331.34s).
- [x] Task 19 — Build transcript and trace replay regression harness
  - Path: `tasks/19-trace-replay-regression-harness/TASK.md`
  - Depends on: Tasks 03-08 canonical/state/policy layers and Task 18 metrics.
  - Status: complete — strict replay codec/fixtures, nine production-seam scenarios and real metric reports independently reviewed; final release 3146 passed, 5 skipped (316.41s).
- [x] Task 20 — Run cross-architecture benchmark, choose provisional defaults, and close migration
  - Path: `tasks/20-cross-architecture-benchmark-migration/TASK.md`
  - Depends on: All Tasks 01-19.
  - Status: complete — strict 14-scenario offline suite, 16 exact selectors/26 cases, representative E2E for all modes and migration proof reviewed; safe legacy default retained; final release 3176 passed, 5 skipped (333.76s).

## How to pick the next task

Choose the lowest-numbered unchecked task whose dependencies are complete. Do not skip a contract/state slice merely because a later provider integration looks more immediately useful. Task 00 may reorder only when repository evidence shows the dependency graph is wrong, and must document the change.

## Global implementation rules

- Keep provider SDK details inside adapters.
- Prefer typed events/results and deterministic state transitions.
- Do not let UI state claim a Live session is stopped until runtime confirms or enters an explicit uncertain/reap state.
- Do not use exact generated wording as the only voice-quality test; test behavioral invariants.
- Keep partial-transcript analysis speculative and reversible.
- Do not make Luna a serial dependency in the critical voice path.
- Do not let the back brain seize speech authority directly.
- Version/fingerprint architecture, model, config, and prompt revisions in session diagnostics.

## Completion reporting

At program completion, use `templates/final-implementation-report-template.md`. Include changed files, tests, replay results, benchmark results, provider gaps, lifecycle/cost-safety verification, selected provisional defaults, and unresolved risks.
