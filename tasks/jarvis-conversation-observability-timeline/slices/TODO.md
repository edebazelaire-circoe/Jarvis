# Implementation TODO

## Orchestration rule

Execute Slice 00 first. No implementation Slice may begin until Slice 00 declares `READY` and resolves a valid Workspace Task Type for the Slice.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline` before implementation. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## Slices

- [x] 00 — Project Manager readiness and orchestration gate (READY 2026-09-16, Task Type gate waived by Human — see LOG.md)
  - Path: `slices/00-project-manager/SLICE.md`
  - Depends on: none
- [x] 01 — Define the canonical conversation event contract (2026-09-16, QA APPROVE_WITH_ISSUES → reworked)
  - Path: `slices/01-conversation-event-contract/SLICE.md`
  - Depends on: 00
- [ ] 02 — Add durable append/replay storage for conversation events
  - Path: `slices/02-durable-event-store/SLICE.md`
  - Depends on: 01
- [ ] 03 — Instrument User, Brain, Mouth, tools and sub-agents at source
  - Path: `slices/03-source-instrumentation/SLICE.md`
  - Depends on: 01, 02
- [ ] 04 — Expose conversation query and live-stream APIs
  - Path: `slices/04-query-live-stream-api/SLICE.md`
  - Depends on: 02, 03
- [ ] 05 — Build the live four-lane transcript/debug timeline
  - Path: `slices/05-timeline-debug-ui/SLICE.md`
  - Depends on: 04
- [ ] 06 — Add readable transcript/export/search and end-to-end rollout gates
  - Path: `slices/06-transcript-export-search-rollout/SLICE.md`
  - Depends on: 03, 04, 05

## Planning blocker

`task_type` is intentionally null in planning metadata because the Workspace Task Type vocabulary was unavailable here. Slice 00 must resolve valid existing Task Types before dispatch; do not fabricate labels.
