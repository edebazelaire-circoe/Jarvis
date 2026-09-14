# Implementation TODO

## Orchestration rule

Execute Slice 00 first. Slice 00 is `READY`; user globally waived the unavailable Workspace Task Type gate on 2026-09-14. Every Slice keeps `task_type: null` rather than inventing a value.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline` before implementation. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## Slices

- [x] 00 — Project Manager readiness and orchestration gate
  - Path: `slices/00-project-manager/SLICE.md`
  - Depends on: none
- [x] 01 — Define the new Settings information architecture and option contracts
  - Path: `slices/01-settings-ia-contract/SLICE.md`
  - Depends on: 00
- [x] 02 — Persist and expose Agent/CLI technical + personality options
  - Path: `slices/02-settings-backend/SLICE.md`
  - Depends on: 01
- [x] 03 — Create a sourced comparison view model for sub-agent and voice catalogs
  - Path: `slices/03-catalog-view-model/SLICE.md`
  - Depends on: 01
  - QA rework complete; canonical `/api/catalog` integrated and tested.
- [x] 04 — Build the reusable sortable/filterable catalog table
  - Path: `slices/04-shared-catalog-table/SLICE.md`
  - Depends on: 03
  - Shared module, injection, responsive styles, deterministic Node fixture tests and docs complete.
- [x] 05 — Replace “Aiguillage” with technical-first Agent/CLI settings and catalog
  - Path: `slices/05-agent-cli-settings-ui/SLICE.md`
  - Depends on: 02, 04
  - Unified Agent / CLI tab, guarded async hydration, canonical bindings, lazy advanced profiles and shared catalog complete; QA rework passed.
- [ ] 06 — Split voice settings into top sub-tabs and embed the voice catalog
  - Path: `slices/06-voice-settings-tabs/SLICE.md`
  - Depends on: 01, 04
  - Backend schema/effective-stack/AEC projection complete; UI, responsive and human validation pending.
- [ ] 07 — Prove migration, personalization, catalog UX and rollout
  - Path: `slices/07-e2e-migration-docs/SLICE.md`
  - Depends on: 05, 06

## Planning blocker

`task_type` stays intentionally null because the Workspace Task Type vocabulary was unavailable. Explicit global user waiver permits Slices 01–07; do not fabricate labels.
