# Slice execution queue

1. [x] `00-project-manager` — **READY** on 2026-10-26 (main `2d6ca879`). See `00-project-manager/READINESS.md`. Task Types: Human global waiver of 2026-09-14, `task_type: null`.
2. [x] `01-product-edition-and-board-lock` — **APPROVED** on 2026-10-26 (`41a9965d`, rework `27e8e345`). Leftovers: `Issues/I-001-s01-polish.md`.
    — canonical Presentation product policy + Core/API/MCP Board enforcement.
3. [x] `02-windows-data-root-context-global` — **APPROVED** on 2026-10-26 (`f239e91c`, rework `797ba070`). Leftovers: `Issues/I-002-s02-leftovers.md`.
    — stable AppData root, migration and permanent `CONTEXT_GLOBAL`.
4. [x] `03-internal-documents-and-export-boundary` — **APPROVED** on 2026-10-26 (`ef514a5a`, rework `1fc5dc88`). Leftovers: `Issues/I-003-s03-leftovers.md` (incl. HV OneDrive).
    — internal canonical documents + explicit `Documents\Jarvis` export contract.
5. [x] `04-agent-confinement-capability-policy` — **APPROVED** on 2026-10-26 (`7da5dec8`..`5484d8e4`, rework `10094459`). Leftovers: `Issues/I-005-s04-leftovers.md`.
    — remove general shell/filesystem write authority from product brain/sub-agents.
6. [x] `05-connectors-secrets-and-iguard-hook` — **APPROVED** on 2026-10-26 (branch `-s05`: `5fad8d8f`..`b55aae8b`, merged). IGuard part pending its contract. Leftovers: `Issues/I-004-s05-leftovers.md`.
    — allowed connectors, credentials, Drive/CIRCOE integration and IGuard seam.
7. [x] `06-windows-private-runtime-packaging` — **APPROVED** on 2026-10-26 (`5ed074e8`..`3f2ba594`, rework `c89dd253`; reference fingerprint `ecdf881d…`). HV-PACKAGE-01..10 open. Leftovers: `Issues/I-007-s06-leftovers.md`.
    — private Python/Node/FFmpeg, dependency/license manifest, production package layout.
8. `07-installer-onboarding-health` — installer, first-run provisioning, product readiness and repair UI.
9. [x] `08-presentation-product-ui` — **APPROVED** on 2026-10-26 (branch `-s08`: `abdfeea9`..`7b38db15`, rework `062b83d1`, merged). Criterion 7 deferred to Slice 07. Leftovers: `Issues/I-006-s08-leftovers.md`.
    — Presentation-only Board/product shell + end-to-end Presentation workspace UX pass.
10. `09-presentation-editing-ui` — dedicated editing/variants/media/preview UX pass.
11. `10-production-readiness-recovery-ci` — crash/update/recovery, CI and packaged artifact release gates.
12. `11-final-e2e-windows-acceptance` — clean-machine physical E2E and Human acceptance.

## Parallelism after READY
- Slice 01 first.
- Slice 02 depends on 01 only for product-edition selection semantics; its storage implementation can be planned in parallel after Slice 00.
- Slice 03 depends on Slice 02.
- Slice 04 depends on 01 and the write/export contract from 03.
- Slice 05 depends on 01; IGuard-specific completion waits for its real contract.
- Slice 06 depends on 01-04 because packaging must freeze the correct security/storage contract.
- Slice 07 depends on 02, 05 and 06.
- Slice 08 depends on 01 and should coordinate with 07 for onboarding surfaces.
- Slice 09 depends on 03 and 08.
- Slice 10 depends on 04, 06, 07, 08 and 09.
- Slice 11 depends on all implementation Slices.

Before every dispatch, Slice 00's Project Manager performs a targeted freshness check against current `main` and active/queued Jarvis tasks.

## Slice 00 status (2026-10-26)
- Dispatch 1: Slice 01.
- External inputs bounded to Slice 05: X1 IGuard, X2 CIRCOE Mail (no connector exists).
- Release gates (Slices 06/10/11): openWakeWord, Remotion licence, FFmpeg GPLv3, Barehands/ai-visualizer AGPL, Claude Code CLI distribution, signing.
