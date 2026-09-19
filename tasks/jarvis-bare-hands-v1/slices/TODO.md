# Implementation TODO

## Orchestration rule

Execute Slice 00 first. No implementation Slice may begin until Slice 00 declares READY and resolves a valid Workspace Task Type for that Slice.

## Required coding skills

Every coding Slice must load /caveman and /coding-guideline. Every frontend/browser Slice must additionally load /impeccable and use a Claude agent when the host supports that routing rule.

## Slices

- [ ] 00 — Project Manager readiness and orchestration gate
- [ ] 01 — Define Bare Hands V1 contracts, schemas and compatibility boundaries
- [ ] 02 — Implement OFF/SLEEP/ACTIVE lifecycle and C-pose wake flow
- [ ] 03 — Stabilize hand identity, filtering and motion feature extraction
- [ ] 04 — Build semantic gesture + primary/secondary pinch engines
- [ ] 05 — Build semantic target resolver and visual targeting feedback
- [ ] 06 — Implement capture-based interaction engine and bimanual frame geometry
- [ ] 07 — Add Bare Hands Tools and Settings surfaces
- [ ] 08 — Implement calibration overlay, profile derivation and persistence
- [ ] 09 — Implement tutorial overlay and voice entry points
- [ ] 10 — Add diagnostics, replay traces and benchmark metrics
- [ ] 11 — Integrate, migrate, validate end-to-end and document rollout

## Dependency graph

00 -> 01 -> {02,03}
03 -> 04
01,03,04 -> 05
05 -> 06
01,05,06 -> 07
03,04,05,06,07 -> 08
06,07,08 -> 09
03,04,05,06,08 -> 10
02,03,04,05,06,07,08,09,10 -> 11

## Planning blocker

task_type is intentionally null in planning metadata because the Workspace Task Type vocabulary is unavailable here. Slice 00 must resolve valid existing Task Types before dispatch; do not fabricate labels.
