# Implementation TODO

## Orchestration rule

Execute Slice 00 first. No implementation Slice may be dispatched until Slice 00 reaches `READY` after a blind live-repository audit and reconciliation.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline`. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## Slices

- [x] 00 - Project Manager readiness and orchestration gate (`slices/00-project-manager/SLICE.md`) — depends: none — **READY** (conditional on W1 + D15), record in `slices/00-project-manager/READINESS.md`
- [x] 01 - Define interaction-mode and output-disposition contracts (`slices/01-interaction-mode-contract/SLICE.md`) — depends: 00 — **APPROVED** (`584b51f` + rework `b75b8e9`), report in `slices/01-interaction-mode-contract/REPORT.md`
- [x] 02 - Add live interaction-mode control plane and persistence (`slices/02-interaction-mode-control-plane/SLICE.md`) — depends: 01 — **APPROVED** (`52ab8cf` + `abc73c9` + `0de10f8`), three QA passes incl. runtime; report in `slices/02-interaction-mode-control-plane/REPORT.md`
- [x] 03 - Add the left-side Jarvis mode selector (`slices/03-control-center-mode-hud/SLICE.md`) — depends: 02 — **APPROVED, pending `HV-PRES-MODE-01`** (`a3e5583` + `347c3c1` + `48bea17`), three QA passes incl. real-browser runtime
- [x] 04 - Add Presentation session working set and transcript-tail contracts (`slices/04-presentation-working-set/SLICE.md`) — depends: 01, 02 — **APPROVED** (`4078acc` + `34dcf0b`), report in `slices/04-presentation-working-set/REPORT.md`
- [x] 05 - Introduce shared audio capture and explicit-address trigger lane (`slices/05-shared-audio-command-lane/SLICE.md`) — depends: 02, 04 — **APPROVED** (`34de032` + `0461fca`); `HV-PRES-AUDIO-01` is NOT reachable from this slice and moves to Slice 11
- [x] 06 - Implement continuous ambient ingestion and asynchronous analysis admission (`slices/06-ambient-ingestion-lane/SLICE.md`) — depends: 04, 05 — **APPROVED** (`4e85429` + `43c51dc`), report in `slices/06-ambient-ingestion-lane/REPORT.md`
- [x] 07 - Enforce Presentation response/speech policy (`slices/07-presentation-response-policy/SLICE.md`) — depends: 01, 02, 06 — **APPROVED** (`708eaef` + `0c122d4`); `HV-PRES-SPEECH-01` must be run **once per voice architecture**
- [ ] 08 - Implement speculative preparation, delegation, and staged display resources (`slices/08-speculative-preparation/SLICE.md`) — depends: 04, 06, 07
- [ ] 09 - Add fact-check attention events, floating warning, and discreet sound (`slices/09-fact-check-attention/SLICE.md`) — depends: 03, 08
- [ ] 10 - Complete priority addressed turns with fresh context and prepared-resource reuse (`slices/10-priority-addressed-turns/SLICE.md`) — depends: 05, 07, 08
- [ ] 11 - End-to-end integration, diagnostics, latency, privacy, and rollout (`slices/11-integration-rollout/SLICE.md`) — depends: 03, 06, 07, 08, 09, 10

## Planning blocker

Workspace Task Type vocabulary is unavailable in this task-creation environment. All `metadata.json` files keep `task_type: null`. Slice 00 must resolve valid existing Task Types before dispatch or obtain an explicit waiver. Never fabricate labels.

**Slice 00 finding:** the vocabulary does not exist anywhere this host can reach, so it cannot be
resolved. **Waived by the Human on 2026-09-23 (W1)** — `task_type: null` stands in all 12
`metadata.json`, and `task_type_blocker` is no longer a dispatch gate. No label was invented.

**D15, decided by the Human on 2026-09-23:** interaction mode does *not* enter
`VoiceComposition.configuration_id`. Core owns the effective live mode and Voice consumes it
through an event, so a mode toggle never restarts the Voice process. Binding on Slice 02.

## Slice 00 constraints carried into implementation

Every Slice below inherits the gaps recorded in `slices/00-project-manager/READINESS.md` §3:
G1 (two voice-architecture axes) → 01, 02; G2 (`Disposition` name collision) → 01;
G3 (`PERSISTABLE_OPTION_IDS` allow-list) → 02, 03; G4/D15 (`configuration_id` restart) → 02;
G5 (no work-lane priority field) → 08, 10; G6 (no generic UI seam) → 03;
G7 (`AddressingDecision` is closed) → 06.

The 26 pre-existing unit-test failures listed in `READINESS.md` §4 are inherited. Every
implementer receives them as "not yours, do not fix"; a failure outside that list belongs to the
Slice that produced it.
