# Slice Execution Order

1. `00-project-manager` — readiness gate and blind repository audit — **done (READY)**
2. `01-contract-audit` — recover/canonicalize scene, window, and prefab contracts — **done**
3. `02-prefab-schema` — definition/instance schemas, structured inputs, versioning, base protection — **done (QA rework done)**
4. `03-dynamic-prefab-runtime` — manifest-driven discovery, scoped styles, lifecycle — **done (QA rework done)**
5. `04-scene-prefab-bridge` — declarative scene object ↔ prefab instance integration — **done (QA rework done)**
6. `05-window-family-prefabs` — migrate the already-defined Rework FENETRES families — **done — awaiting HV-WINDOW-FAMILIES-01**
7. `06-structured-interactive-prefabs` — structured data + interactive checklist proof — **done (QA rework done)**
8. `07-agent-prefab-operations` — list/inspect/instantiate/fork/create/save controlled operations — **done (QA rework done)**
9. `08-prefab-library-management` — human/agent library browsing, preview, provenance, protection UX — **done — awaiting HV-PREFAB-LIBRARY-01**
10. `09-integration-hardening` — migration completion, regression removal, end-to-end validation — **done — awaiting HV-PREFAB-E2E-01 (last)**

Do not dispatch implementation work until Slice 00 reports `READY`.

Status (2026-10-03): all Slices implemented and machine-validated; task awaiting Human validation (`../CLOSEOUT.md`).
