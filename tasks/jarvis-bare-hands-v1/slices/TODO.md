# Implementation TODO

## Orchestration rule

Execute Slice 00 first. No implementation Slice may begin until Slice 00 declares READY.

Slice 00 ran on 2026-09-19; see `00-project-manager/READINESS.md`. The Task Type gate was waived by the Human (D1), so `task_type` stays null everywhere.

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
- [ ] 12 — Build the Bare Hands command channel from the brain to the page (added by Slice 00, decision D2)

## Slice status

**The unticked boxes above are a repository-wide convention, not a status.** The
finished 2026-08-31 handoff's `TODO.md` is unticked too. Do not read them as
evidence that a Slice is incomplete.

Real status, as of Slice 11 (the last): **all thirteen Slices are implemented**;
01-09 and 12 were reworked after QA. The close-out record — scope narrowings,
deferrals with their reasons, the clean-room re-verification, and what a human
must still do — is `../ROLLOUT.md`. The durable narrative is `../LOG.md`.

**The real-camera validation was waived by the Human, not passed.** The
procedure a human must still run is `docs/OPERATIONS.md` › *Procédure de test
manuel (caméra réelle)*, batches A1-A7.

## Dependency graph

00 -> 01 -> {02,03}
03 -> 04
01,03,04 -> 05
05 -> 06
01,05,06 -> 07
03,04,05,06,07 -> 08
02,07 -> 12
06,07,08,12 -> 09
03,04,05,06,08 -> 10
02,03,04,05,06,07,08,09,10,12 -> 11

## Resolved planning blockers

Both blockers recorded in `task.json` were closed by Slice 00 on 2026-09-19.

- **Task Type.** No Workspace Task Type vocabulary exists in this repository, in any form. The Human waived the gate (D1), matching the precedent of the settings, observability and category2 tasks. `task_type` stays null in every metadata file; do not fabricate labels.
- **Freshness audit.** The Control Center, Constellation and voice-command integration points were audited against `origin/main@6af6df91`, which is exactly the planning snapshot. Findings F1-F7 are in `00-project-manager/READINESS.md`; F2, F3 and F5 were applied to the Slices below.

## Standing constraints discovered by Slice 00

Read `00-project-manager/READINESS.md` before implementing any Slice. In particular:

- New page JS is not loaded by `<script src>`. Each module is a marker comment in `control_center.html` substituted server-side by `control_center.py`, and load order is asserted by tests. Registering a new module is part of the Slice that creates it.
- `pointerId 9001` and the `#jarvisHands` DOM shape are a contract with `control_center_scene_page.js` and `control_center.html`, not Bare Hands internals.
- Scene geometry lives in `control_center_scene_interact.js` and works in scene units (±160 × ±90), not pixels. Extend it; do not build parallel geometry.
- Edge/corner manipulation applies to `capsule` and `window` representations only (Human decision D3). `point` and `signal` stars stay move-only.
- There is no LogBroker. Emit through `RuntimeJournal` to `runtime/trace.jsonl`, with a stable `code` in `data` for every refusal.
