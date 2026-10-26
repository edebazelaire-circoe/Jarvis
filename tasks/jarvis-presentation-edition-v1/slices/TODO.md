# Slice execution queue

1. [x] `00-project-manager` — **READY** on 2026-10-26 (main `2d6ca879`). See `00-project-manager/READINESS.md`. Task Types: Human global waiver of 2026-09-14, `task_type: null`.
2. `01-product-edition-and-board-lock` — canonical Presentation product policy + Core/API/MCP Board enforcement.
3. `02-windows-data-root-context-global` — stable AppData root, migration and permanent `CONTEXT_GLOBAL`.
4. `03-internal-documents-and-export-boundary` — internal canonical documents + explicit `Documents\Jarvis` export contract.
5. `04-agent-confinement-capability-policy` — remove general shell/filesystem write authority from product brain/sub-agents.
6. `05-connectors-secrets-and-iguard-hook` — allowed connectors, credentials, Drive/CIRCOE integration and IGuard seam.
7. `06-windows-private-runtime-packaging` — private Python/Node/FFmpeg, dependency/license manifest, production package layout.
8. `07-installer-onboarding-health` — installer, first-run provisioning, product readiness and repair UI.
9. `08-presentation-product-ui` — Presentation-only Board/product shell + end-to-end Presentation workspace UX pass.
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
