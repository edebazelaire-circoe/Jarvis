# Jarvis Remotion-native Studio + Playback Fix

**Project:** Jarvis  
**Repository:** `edebazelaire-circoe/Jarvis`  
**Task slug:** `jarvis-remotion-native-studio-playback-fix`  
**Drive target:** `Jarvis/task/to-do/jarvis-remotion-native-studio-playback-fix/`  
**Evidence/plan origin:** two user screenshots and spoken feedback, 2026-10-11; GitHub source inspection (reference HEAD `d2332e61c0e384d1e75d7d31a81efb730254eb6e`, refresh mandatory).  
**Nature:** corrective implementation, not a second presentation product.  
**Status:** queued for Project Manager, not implemented or accepted.

## Executive objective

Use native Remotion Studio as the creative baseline. Keep the current **Variants** screen (screenshot 2) as the Jarvis view for versions, branching, preview and publication. Remove the unwanted floating viewer (screenshot 1), not create a second viewer. Make the Remotion Player the one reliable playback mechanism with a canonical clock, seamless full-deck compositions, deterministic scene starts and fully synchronized controls. Unblock a Claude/agent-native authoring experience with quality comparable to using Remotion directly from a terminal; Jarvis must add capabilities rather than constrain creative output.

## Start here

1. Read `slices/TODO.md` and execute `slices/00-project-manager/SLICE.md` **yourself**, not delegated.
2. Blindly inspect fresh repository/branch/running work and record baseline before accepting the findings of this handoff.
3. Compare with `docs/01-decision-log.md`, `docs/02-architecture.md`, user observation in `docs/06-screen-evidence.md`, and the reconstructed `grill-session.md`.
4. Report one readiness state (`READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`); dispatch no implementation before READY.
5. Select next eligible Slice; re-audit its code and contracts on the actual HEAD immediately before dispatch.

## Locked boundaries

- Native **Remotion Studio** and Jarvis **Variants** are two views, not two Jarvis playback engines.
- No third floating presentation viewer; delete/deprecate it once functionality is migrated.
- Do not replace native Remotion primitives with homemade video controls or an arbitrary time-per-slide scheme.
- Explicitly preserve variants, pins, reusable prefab sources, Board/Artifact provenance, presenter roles, cues, security and compatible historical content.
- Do not silently fall back from Remotion to Slidecar. Slidecar remains an existing human-only experimental engine, not a reason to fork the UI.
- New left-rail geometry is **deferred** until the user supplies a sketch; clean integration is in scope, speculative redesign is out of scope.
- Don't change user's running Jarvis/Core or any production data as part of automated verification.

## QA doctrine for every Slice

- Every implemented Slice: independent `qa-verification`.
- Code Slice: add `code-review`.
- User-visible or runtime change: add `runtime-validation` with real evidence.
- Agent prompt/tools/routing/runtime change: add `agent-trace-analysis` with **real** traces, not just fakes.
- QA agents produce evidence and findings; Project Manager decides acceptance, rework, new Slice, Issue or Human escalation.
- Regressions introduced by the current Slice are blocking and cannot be parked in `Issues/`.
- Exhaust available machine checks before asking a person; Human video/voice/projector and subjective deck-quality validation remains separate.
- Coding Slices must use `/caveman` and `/coding-guideline`; frontend Slices additionally `/impeccable` and Claude as the frontend Work Agent when routing supports it.
- Each Slice must have a valid Workspace Task Type resolved at runtime. No fabricated type or default `code` when type is unknown.

## Handoff inventory

`docs/` contains decisions, architecture, implementation sequence, QA and documentation contracts. `evidence/` contains the two original screenshots (local handoff). `slices/` contains the 00 Project Manager gate and 16 focused work Slices. `LOG.md` is for agents to fill as they work, not an invented progress report.
