# Slice Execution Order

1. `00-project-manager` — readiness gate and blind repository audit
2. `01-contract-audit` — recover/canonicalize scene, window, and prefab contracts
3. `02-prefab-schema` — definition/instance schemas, structured inputs, versioning, base protection
4. `03-dynamic-prefab-runtime` — manifest-driven discovery, scoped styles, lifecycle
5. `04-scene-prefab-bridge` — declarative scene object ↔ prefab instance integration
6. `05-window-family-prefabs` — migrate the already-defined Rework FENETRES families
7. `06-structured-interactive-prefabs` — structured data + interactive checklist proof
8. `07-agent-prefab-operations` — list/inspect/instantiate/fork/create/save controlled operations
9. `08-prefab-library-management` — human/agent library browsing, preview, provenance, protection UX
10. `09-integration-hardening` — migration completion, regression removal, end-to-end validation

Do not dispatch implementation work until Slice 00 reports `READY`.
