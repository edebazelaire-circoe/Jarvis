# Slice execution queue — Presentation Edition V1.2

1. [x] `00-project-manager` — **READY** le 2026-10-27 (READINESS.md) — blind audit/reconciliation/readiness gate; runs first and must reach `READY`.
2. `01-presentation-product-brain-scope` — enforce Presentation-focused brain/tool/role scope without breaking research/connectors/Presentation authoring.
3. `02-board-project-continuity` — make Board resume behave as project resume using durable Board memory.
4. `03-research-reuse-freshness-orchestration` — force existing-source lookup, freshness decision and proper use of Research Lead/sub-agents/relations.
5. `04-research-documents-and-dossier` — turn substantial research into durable reusable Board documents visible in Dossier.
6. `05-voice-lifecycle-wake-chat` — launch/close lifecycle and Voice Off/Sleep/Active + chat contract.
7. `06-settings-and-novice-ui` — simplify normal UX while retaining complete Settings/debug/transcription surfaces.
8. `07-bug-report-diagnostic-bundle` — user-facing diagnostic report + sanitized AppData ZIP + send/fallback.
9. `08-macos-portability-build-validation` — platform-path/packaging portability and macOS CI/real-device gate.
10. `09-v1-2-integration-e2e` — whole amendment E2E, regression and Human acceptance package.

## Dependencies
- Slice 01 depends only on 00.
- Slice 02 depends on 01.
- Slice 03 depends on 01 and 02.
- Slice 04 depends on 02 and 03.
- Slice 05 depends on 01.
- Slice 06 depends on 01 and must consume the voice states from 05 if implemented concurrently.
- Slice 07 depends on the stable storage root contract from the parent V1 task plus Slice 01; coordinate with parent storage/installer work through Slice 00 rather than naming an external hard dependency.
- Slice 08 depends on Slice 01 and on current storage/packaging seams discovered by Slice 00.
- Slice 09 depends on 01–08.

Before every dispatch, the Project Manager performs a targeted freshness check against current `main`, parent V1 planning and overlapping Jarvis tasks.