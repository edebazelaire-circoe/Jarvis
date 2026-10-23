# Slice Execution Order

1. [x] `00-project-manager` - Project Manager readiness and reconciliation gate. READY (2026-10-21, see LOG).
2. [x] `01-settings-registry-ia-contract` - Canonical Settings registry and six-category IA contract. Approved 2026-10-21 (626e08ab).
3. [x] `02-settings-shell-visual-redesign` - Settings shell and visual redesign. Approved 2026-10-21 (8583ac1c + 77740b68).
4. [x] `03-voice-audio-reorganization` - Voice and audio reorganization. Approved 2026-10-21 (2d114097 + 55b59ad0 + ccc46063).
5. [x] `04-agents-models-reorganization` - Agents and models reorganization. Approved 2026-10-21 (fc5f2ff8 + 56c17532; S3 test fix 3e47b4c3).
6. [x] `05-memory-knowledge-reorganization` - Memory and knowledge reorganization. Approved 2026-10-22 (d1fd5690 + 36085b29 + 28e055d8 + c6d85fb7).
7. [x] `06-interface-interactions-reorganization` - Interface and interactions reorganization. Approved 2026-10-22 (2ec2a203 + 83387ef1).
8. [x] `07-connections-reorganization` - Connections reorganization. Approved after independent QA (3f0a6cd7, b6786c09, 4394bacd).
9. [x] `08-advanced-diagnostics-labs` - Advanced diagnostics and labs. Approved after independent QA (d22870ed, dfc45f35, 7ce0209f; S7 fix 7eb74cc1).
10. [x] `09-legacy-routing-and-deeplink-compatibility` - Legacy tab cleanup and compatibility aliases. Approved after independent QA (9c509238, 6efd5041).
11. [x] `10-integration-accessibility-release-qa` - Integrated accessibility and release QA. Machine validation exhausted after re-QA (5e54df9b, rework a89dcf93..81a7565f); Human checks pending (HUMAN-CHECKS.md).

Dependencies in each Slice are authoritative. Slice 00 may split, reorder, supersede, or add Slices after its blind audit, but it must record why.
