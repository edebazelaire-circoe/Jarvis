# Slice Execution Order

1. [x] `00-project-manager` - Project Manager readiness and reconciliation gate. READY (2026-10-21, see LOG).
2. [x] `01-settings-registry-ia-contract` - Canonical Settings registry and six-category IA contract. Approved 2026-10-21 (626e08ab).
3. [x] `02-settings-shell-visual-redesign` - Settings shell and visual redesign. Approved 2026-10-21 (8583ac1c + 77740b68).
4. [x] `03-voice-audio-reorganization` - Voice and audio reorganization. Approved 2026-10-21 (2d114097 + 55b59ad0 + ccc46063).
5. [x] `04-agents-models-reorganization` - Agents and models reorganization. Approved 2026-10-21 (fc5f2ff8 + 56c17532; S3 test fix 3e47b4c3).
6. `05-memory-knowledge-reorganization` - Memory and knowledge reorganization.
7. `06-interface-interactions-reorganization` - Interface and interactions reorganization.
8. `07-connections-reorganization` - Connections reorganization.
9. `08-advanced-diagnostics-labs` - Advanced diagnostics and labs.
10. `09-legacy-routing-and-deeplink-compatibility` - Legacy tab cleanup and compatibility aliases.
11. `10-integration-accessibility-release-qa` - Integrated accessibility and release QA.

Dependencies in each Slice are authoritative. Slice 00 may split, reorder, supersede, or add Slices after its blind audit, but it must record why.
