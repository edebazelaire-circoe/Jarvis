# Documentation levels

| Concept | Current evidence | Current level | Required V1 level | Action |
|---|---|---:|---:|---|
| Presentation Board type / interaction mode | `docs/boards.md`, `docs/interaction-mode.md`, Presentation docs/tests | 3 | 3 | Extend with product-edition availability semantics and negative gates. |
| Product edition / capability availability | No single canonical contract identified during planning | 0-1 | 3 | Slice 01 creates canonical model/policy + tests consumed by Core/API/MCP/UI. |
| Local data root | `jarvis/data_root.py`, `docs/local-data.md` | 3 for development root | 3 for installed product | Slice 02 adds installed-product root semantics and migration tests. |
| `CONTEXT_GLOBAL` | `docs/context-global.md`, `claude_local.py` wiring | 2-3 | 3 | Slice 02 documents permanence under product AppData and guards cleanup/migration. |
| Board/Session/Artifact internal storage | dedicated docs/adapters/tests | 3 | 3 | Rebase onto stable product root without weakening path defenses. |
| Internal document vs exported output | scattered Presentation/render behavior; no single product contract | 1 | 3 | Slice 03 defines export contract/service and tests. |
| Agent filesystem/shell confinement | current permission modes + restricted profiles; broad conversation defaults | 1-2 | 3 | Slice 04 creates enforceable product capability profile and trace gates. |
| MCP plugin runtime | `docs/mcp/*`, `mcp_plugin_service`, remote connector/tests | 3 | 3 | Slice 05 configures allowed connector policy and IGuard seam. |
| IGuard connector | external contract not supplied in this handoff | 0 | 2-3 | Slice 05 records exact endpoint/transport/auth/tool mapping when supplied; do not invent. |
| Google Drive connector | existing Drive service/MCP/docs/tests | 2-3 | 3 | Slice 05 validates product onboarding and credential behavior. |
| Local capabilities / Remotion | `docs/local-capabilities.md`, `docs/remotion-runtime.md`, runner/tests | 3 | 3 | Slice 06 switches installed product to private Node/runtime ownership and keeps integrity gates. |
| Windows production packaging | `setup.ps1` is developer bootstrap; no canonical installer contract | 0-1 | 3 | Slices 06-07 create package/installer manifests, build and smoke contracts. |
| Product readiness/repair | current `jarvis/runtime/health.py` is limited; local capability health exists | 1-2 | 3 | Slices 07 and 10 create product-level readiness matrix and recovery behavior. |
| Presentation product UI | extensive Control Center/Studio UI and recent Settings refactors | 2-3 | 3 | Slice 08 adds Presentation-edition UX contract and visual/runtime gates. |
| Presentation editing UX | functional editing exists; product usability pass not yet canonical | 1-2 | 3 | Slice 09 documents and validates the V1 editing journey. |
| Release CI / packaged acceptance | local verification docs; latest audited commit had no workflow run | 1 | 3 | Slice 10 establishes reproducible pipeline and artifact gates. |

## Rule
A Level 3 requirement means not only prose documentation but a reusable implementation/schema/validator/conformance test. If Slice 00 finds newer canonical contracts on `main`, it may update this table before dispatch.

## Slice 00 revision (2026-10-26)
| Concept | Correction |
|---|---|
| CIRCOE Mail | **No implementation** (level 0). It was absent from the table: new external input X2, Slice 05. |
| CIRCOE Calendar | `jarvis/adapters/google_calendar.py` (Google Calendar), level 2. CIRCOE = Google Workspace still to confirm. |
| Runtime dir / logs / config | `JARVIS_RUNTIME_DIR` relative to the working directory, level 1 for the product. Slice 02 targets level 3. |
| Product secrets (API keys) | Plain text in `control-center-settings.json`/`.env`, level 1. Slice 05 targets level 3 (DPAPI vault). |
| Brain CLI provisioning | Absent from the handoff, level 0. Slices 06/07 target level 3. |
| Release CI | `ci.yml` exists (Ubuntu only, no artifact): level 1 confirmed, to extend rather than recreate. |

## Slice 06 (2026-10-26)
| Concept | Level reached |
|---|---|
| Windows production packaging (package layout, private runtimes, runtime manifest, third-party policy/manifest) | **3**: `docs/windows-packaging.md`, `jarvis/private_runtime.py`, `packaging/windows/*`, conformance `tests/unit/test_private_runtime.py` + `test_windows_packaging.py`, real reproducible build. Installer/launcher remain Slice 07. |
| Local capabilities / Remotion in the installed product | **3**: private Node resolution (default `which` of the three runners), child `PATH`, typed `node_missing` repair message; real `npm ci` + MP4/PNG/PDF renders with the packaged Python and Node, `PATH` reduced to Windows. |
