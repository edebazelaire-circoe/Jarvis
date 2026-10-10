# 07 - Evidence index and source stability

## Exact code snapshot

- Branch: https://github.com/edebazelaire-circoe/Jarvis/tree/task/jarvis-interactive-presentation-studio
- Audited commit: https://github.com/edebazelaire-circoe/Jarvis/commit/16e3dc585a29a767af26440e5a4364c8d57d9065
- Branch compare at observation: `main...task/jarvis-interactive-presentation-studio` -> 129 ahead, 85 behind; main compared SHA `fed66732c793f3bdc05cf88d9ec61efb2eab0bff`.
- No PR associated with the branch was found by the connected repository search at that moment.

## Canonical code and docs reviewed (use the exact SHA link when verifying)

- [Studio domain and status](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/docs/presentation-studio.md) - positions 19-50, 143-165, 583-766; says Presentation is distinct from Artifact and stores in `presentations/`.
- [Old Slices TODO](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/tasks/jarvis-interactive-presentation-studio/slices/TODO.md) - 15,18-22 remain unchecked at snapshot.
- [Old implementation LOG](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/tasks/jarvis-interactive-presentation-studio/LOG.md) - test claims, QA evidence, outstanding voice/visual checks.
- [Presentation model](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/domain/presentation_studio.py) and [scene controls](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/domain/presentation_studio_scene.py).
- [Score](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/domain/presentation_studio_score.py) and [Cue follower](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/domain/presentation_studio_cues.py).
- [Core persistence](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/adapters/file_presentation_studio_store.py) and [hot reload](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/core/presentation_studio_reload.py).
- [Playback](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/core/presentation_studio_playback.py) and [browser fullscreen model](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/jarvis/domain/surface_fullscreen.py).
- [Artifacts contract](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/docs/artifacts.md) - closed kinds, terminal states, immutable payloads, Board links.
- [Board contract](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/docs/boards.md) and [data-root layout](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/docs/local-data.md).
- [Prefab contract](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/docs/prefabs.md).
- [Remote MCP plugin contract](https://github.com/edebazelaire-circoe/Jarvis/blob/16e3dc585a29a767af26440e5a4364c8d57d9065/docs/mcp/plugins.md) - external URL-based MCP Plugin definition, not a local runtime installer.

## Remotion upstream to re-check at execution time

- Remotion parameterized rendering: https://www.remotion.dev/docs/parameterized-rendering
- Remotion Player: https://www.remotion.dev/docs/player
- Remotion SDK/Canvas: https://www.remotion.dev/docs/sdk (experimental)
- Remotion codemods: https://www.remotion.dev/docs/codemods/ (experimental)
- Remotion license and pricing: https://www.remotion.dev/docs/license/pricing ; FAQ: https://www.remotion.dev/docs/license/faq
- OpusClip source/template examples: https://github.com/opus-pro/opusclip-video-tools (templates under MIT, Remotion runtime license separate)

## Evidence vs inference

- Fact from branch: code/docs of Slidecar and incomplete original checklist at pinned SHA.
- Fact from current public docs: Remotion uses React props, Player, Studio, local rendering and optional experimental SDK/codemods; licensing varies by product usage.
- Inference/desired behavior, not proven: adopting current Remotion as install-once Jarvis plugin, source/Board artifacts support, display compatibility across renderer types and fast safe edits under user voice. All must be built and tested.

---

# Final-head evidence (Slice 01, 2026-10-09)

Observed by running and reading, not copied from the snapshot above.

## Exact code

- Head audited: `main` = `de7b9c59` (merge of origin/main into the studio branch; `origin/main` identical, 0/0). Studio branch snapshot `16e3dc58` is an ancestor (`git merge-base --is-ancestor`).
- Worktree: `C:/Projects/jarvis/brm`, branch `task/jarvis-remotion-presentation-integration` at `7648eba5` (main + this handoff, no product change). Schemas: `jarvis.sqlite3` v8, `scene.sqlite3` v1 (READINESS).
- The snapshot's "129 ahead / 85 behind" and "no PR" observations are superseded.

## Where each fact is documented

| Fact | Document |
| --- | --- |
| Requirement-by-requirement status with file:line | `docs/06-branch-compliance-audit.md`, section "Final-head audit (main de7b9c59)" |
| Measured test results (files, counts, failures, environment) | `slices/01-final-branch-conformance/BASELINE.md` ("not ours, do not fix") |
| Plan changes, integration risks, what is redundant | `docs/06-branch-compliance-audit.md` (sections "Redundant, overlapping or re-scoped plan entries" and "Integration risks for Remotion"); per-Slice "Plan amendment after Slice 01" sections; `slices/TODO.md` banner |
| Inherited debt of the studio task | `Issues/01-inherited-debt-from-the-studio-task.md` |
| Studio release status, H-1..H-11 | `docs/presentation-studio-release.md` (in the repo, not in this folder) |

## Canonical code actually read for the audit (all on `de7b9c59`)

- Presentation domain: `jarvis/domain/presentation_studio.py`, `presentation_studio_scene.py`, `presentation_studio_score.py`, `presentation_studio_playback.py`, `presentation_studio_edit.py`, `presentation_studio_reload.py`, `presentation_studio_template.py`, `presentation_studio_roles.py`; store `jarvis/adapters/file_presentation_studio_store.py`.
- Core: `jarvis/core/presentation_studio_service.py`, `_playback.py`, `_reload.py`, `_template.py`, `_variants.py`, `_autosave.py`, `_stage.py`.
- Agent surface: `jarvis/runtime/presentation_studio_mcp.py`, `presentation_studio_mcp_tools.py`, `tool_brain_executor.py`.
- Control Center: `jarvis/runtime/control_center_fullscreen.js`, `control_center_presentation_studio_*.js`, `control_center_prefabs.js`, `control_center_mcp_plugins.js`.
- Artifact / Board / plugin owners: `jarvis/domain/artifacts.py`, `jarvis/core/artifact_service.py`, `jarvis/core/workspace_service.py` (`artifact_link`), `jarvis/domain/board_artifact_links.py`, `jarvis/core/board_service.py`, `jarvis/domain/mcp_plugins.py`, `jarvis/core/mcp_plugin_service.py`, `docs/mcp/plugins.md`, `docs/prefabs.md`, `docs/artifacts.md`.

## Evidence vs inference (update)

- Fact (this head): there is no `remotion` string and no `package.json` in the repository; no engine/source-kind field exists in the Presentation, variant or scene models; `ArtifactKind` is closed (7 kinds); `WorkspaceService.artifact_link` takes only a `jart_` artifact id; `McpPlugin.transport` is `streamable_http` only; prefab manifests are a closed key set at `schema_version == 1`.
- Fact (docs, not re-run): real-model authoring traces and the release journeys come from the studio task's own evidence (`docs/presentation-studio-release.md`); this Slice re-ran the unit suites but not the real-model harness (it costs money and needs the `claude` CLI).
- Still inference: every Remotion behaviour (install-once, Player/Studio, HMR, export, Board bridging) remains untested desired behaviour.

## Slice 03 - local capability host (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s03`, base `9f363475`)

- Contract: `docs/local-capabilities.md` (Level 2); code `jarvis/domain/local_capabilities.py`, `jarvis/ports/local_capabilities.py`, `jarvis/adapters/file_local_capability_store.py`, `jarvis/core/local_capability_host.py` (Level 3 host skeleton, fake runner only).
- Evidence: `tests/unit/test_local_capability_host.py` (40 passed, run in the worktree with the repo venv); remote MCP plugin suites unchanged and green (see LOG). Remote registry fact re-checked: `McpPlugin` URL-only, `transport == streamable_http` (`jarvis/domain/mcp_plugins.py`).
- Not evidenced: any real install, npm, child process, Windows process-tree kill, Control Center card.

## Slice 02 (engine semantics, 2026-10-09, branch `task/jarvis-remotion-presentation-integration-s02`)

- Contract: `docs/presentation-engine.md` (Level 2) + rows in `docs/presentation-studio.md` and `docs/prefabs.md` (repo, not this folder).
- Code: `jarvis/domain/presentation_studio_engine.py`, `jarvis/domain/presentation_studio.py` (`Presentation.engine`, manifest v3, `_presentation_v2_to_v3`), `jarvis/domain/presentation_studio_checks.py` (3 codes).
- Conformance: `tests/unit/test_presentation_studio_engine{,_tools,_docs}.py`; fixtures `tests/fixtures/presentation_studio/presentation.v3.json`, `presentation.future.json` (now v4).
- Test counts and the exact commits: LOG.md, entry "Slice 02". Baseline reds (BASELINE.md) were not touched.

## Slice 07 (source parent vs terminal Artifacts, 2026-10-09, branch `task/jarvis-remotion-presentation-integration-s07`, base `d3709520`)

- Contract: `docs/presentation-artifacts.md` (Level 2) + rows in `docs/artifacts.md` (kinds, `rendered_from`, Board-links owner), `docs/presentation-studio.md`, `docs/local-data.md`, `docs/boards.md` (repo, not this folder).
- Code: `jarvis/domain/presentation_artifacts.py`, `jarvis/core/presentation_artifacts.py`; 4 `ArtifactKind` values and `ArtifactRelationKind.RENDERED_FROM` in `jarvis/domain/artifacts.py`. No schema change (`jarvis.sqlite3` stays v8, no snapshot file).
- Conformance: `tests/unit/test_presentation_artifacts.py` (service on real SQLite registry + real Studio store), `tests/unit/test_presentation_artifacts_docs.py`.
- Test counts and exact commits: LOG.md, entry "Slice 07".

## Slice 04 - Remotion environment install and lifecycle (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s04`, base `14e6045f`)

- Contract: `docs/remotion-runtime.md` (Level 2); code `jarvis/adapters/node_capability_runner.py`, `jarvis/adapters/process_tree.py`, `jarvis/domain/remotion_capability.py`, `jarvis/core/local_capability_service.py`, `jarvis/protocol/local_capability_routes.py`, shipped `jarvis/capabilities/remotion/{package.json,package-lock.json,runtime-host.mjs}`.
- Real-machine evidence: `slices/04-remotion-one-time-provisioning/evidence/real-install.json` produced by `scripts/remotion_install_harness.py` at branch head `208aeaea` (Windows 11 10.0.26200, Node v24.18.0, npm 11.16.0 bundled with that Node, real npm registry, private data root in the OS temp folder): fresh install, no-op second install, concurrent installs, restart of the host, corruption + repair, interrupted install + reconcile + repair, offline, permission denied, timeout with process-tree kill, tampered-lock `EINTEGRITY`, uninstall with presentation sources untouched. Version facts: `npm view` on 2026-10-09 (remotion, @remotion/{player,cli,bundler} 4.0.534; react, react-dom 19.3.0).
- Unit evidence (fake npm/node, no network): `tests/unit/test_node_capability_runner.py`, `test_process_tree.py`, `test_remotion_lifecycle.py`, `test_local_capability_routes.py` (+ unchanged `test_local_capability_host.py`).
- Not evidenced: a real Core process serving the routes (rule: never start the user's Core; routes tested on an in-process Core with a fake runner); macOS/Linux; Control Center card; Remotion Player/Studio use (Slices 10-11).

## Slice 05 - Remotion scene source, module layout, compile contract (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s05`, base `11fea74a`)

- Decision and contract: `docs/remotion-source.md` (Level 2) + rows/sections in `docs/prefabs.md` (manifest v2), `docs/local-data.md`, `docs/presentation-studio.md`, `docs/presentation-engine.md`, `docs/remotion-runtime.md` section 12 (repo, not this folder). Code: `jarvis/domain/remotion_source.py`, `jarvis/domain/remotion_compile.py`, `jarvis/adapters/remotion_compiler.py`, `jarvis/capabilities/remotion/runtime-host.mjs`, `jarvis/domain/prefab.py` (manifest v2, `PrefabBundle.sources`), `jarvis/adapters/file_prefab_library.py`, `jarvis/core/prefab_service.py`.
- Real-machine evidence: `slices/05-remotion-project-source-contract/evidence/real-compile.json` produced by `scripts/remotion_compile_harness.py` at repository head `72518b1c` (clean tree; rework S5, first run was `7a0daf78`; Windows 11 10.0.26200, Node v24.18.0, real npm registry for the install, real esbuild 0.28.1, real Chrome headless rendering the Player). Reproduce: run the script with a private `--work-dir` outside `~/.jarvis`.
- Unit evidence (no network): `tests/unit/test_remotion_source.py`, `test_remotion_source_store.py`, `test_remotion_compiler.py`, `test_remotion_source_docs.py`; real-compile unit tests `test_remotion_compiler_real.py` need `JARVIS_REMOTION_RUNTIME_DIR` (13 passed against a fresh private install). Counts and neighbours: LOG.md entry "Slice 05".
- Not evidenced: a real Core serving the compiled files (Slice 10; Core never started), macOS/Linux, runtime isolation of the scene code (Slice 06), a Player in a real window.

## Slice 08 - Board discoverability and derived provenance (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s08`, base `a87e82b1`)

- Contract: `docs/presentation-artifacts.md` section "Board discoverability (Slice 08)"; `docs/boards.md` (workspace routes, Artefacts view); code `jarvis/core/workspace_service.py` (`bind_presentations`, `presentation_sources`, `presentation_source`), `jarvis/protocol/workspace_routes.py`, `jarvis/runtime/workspace_relay.py`, `jarvis/core/v2_app.py`, `jarvis/runtime/capture_mcp.py`, `jarvis/runtime/control_center_workspace.js`.
- Browser evidence: `slices/08-artifact-board-registration/evidence/s8-*.png` (1440 and 700 px: Board groups, render provenance, explorer opened from "Ouvrir la source") produced by `tests/unit/test_workspace_presentations_browser.py` against a real Core and Control Center on free ports and an isolated data root.
- Unit evidence: `tests/unit/test_presentation_board_discovery.py`, `test_workspace_presentations_js.py`, `test_workspace_presentations_browser.py`, `test_presentation_artifacts_docs.py`.
- Not evidenced: the user's live Core (never started); macOS/Linux.

## Slice 17 - semantic prefab catalog (branch `task/jarvis-remotion-presentation-integration-s17`, base `33694eac`)

- Contract: `docs/prefabs.md` > *Manifest v3 and the semantic catalog* (Level 2); code `jarvis/domain/prefab_catalog.py`, `jarvis/domain/prefab.py` (`parse_manifest`, `is_remotion_manifest`, `catalog_view`), `GET /v1/prefabs` extensions in `jarvis/protocol/prefab_routes.py` / `jarvis/core/prefab_service.py`, UI `jarvis/runtime/control_center_prefabs.js` + `control_center.html`.
- Tests: `tests/unit/test_prefab_catalog.py` (domain, derivation, immutability, old reader, library scan, base lock, service filters, Core route), `tests/unit/test_prefab_library.py` (JS filters), `tests/unit/test_prefab_catalog_browser.py` (real headless Chrome on an isolated Core, own ports and temporary data root).
- Screenshots (real Chrome, 1400x900 and 390x800): `slices/17-prefab-shop-semantic-catalog/evidence/*.png` (`list-all`, `detail-composition`, `detail-legacy`, `narrow`).
- Not proven here: a real Remotion Player preview of a catalogue entry (Slice 10), an upstream URL check (Slice 18).
## Slice 06 - Remotion scene isolation: static guards, sandbox contract, bounds (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s06`, base `a87e82b1`)

- Contract: `docs/remotion-isolation.md` (Level 2) + `docs/SECURITY.md` section 18, `docs/OPERATIONS.md` (Isolation runbook), `docs/remotion-source.md` sections 6-7-10, `docs/remotion-runtime.md` section 12 (repo, not this folder). Code: `jarvis/domain/remotion_isolation.py`, `jarvis/domain/remotion_sandbox.py`, `jarvis/runtime/remotion_sandbox.py`, `jarvis/runtime/remotion_sandbox_protocol.js`, `jarvis/runtime/remotion_sandbox_child.js`, `jarvis/adapters/node_capability_runner.py` (heap cap), `jarvis/domain/remotion_source.py` (`SOURCE_GUARDS`).
- Real-machine evidence: `slices/06-remotion-source-isolation/evidence/real-isolation.json` produced by `scripts/remotion_isolation_harness.py` (+ `scripts/remotion_isolation_cdp.mjs`) at repository head `5cd1fa9f` (rework QA, clean tree; Windows 11 10.0.26200, Chrome 154.0.8037.99, Node v24.18.0, real esbuild compile, real Chrome driven over DevTools, three loopback origins): verdict PASSED, 44 checks (benign scene, sibling spoof, 13 hostile samples x direct/evasive including WebRTC, link hints and a 64 MB message, SVG opened as a document, negative controls, ablations including the WebRTC hardening, channel observations from UDP/TCP sinks and Chrome's net-log, credentials never reaching the sandbox origin). Reproduce: `python scripts/remotion_isolation_harness.py --work-dir <short temp dir> --runtime-dir <root>/local_capabilities/remotion/runtime --evidence <file>`; or `JARVIS_REMOTION_RUNTIME_DIR=... pytest tests/unit/test_remotion_isolation_real.py` (about 3 minutes).
- Unit evidence (no network, no browser): `tests/unit/test_remotion_isolation.py` (229), `test_remotion_sandbox_protocol_js.py` (15, node), `test_remotion_isolation_docs.py` (7); hostile corpus `tests/fakes/remotion_hostile.py`; compile-bound tests in `test_remotion_compiler_real.py` (need an installed runtime). Counts and neighbours: LOG.md entry "Slice 06".
- Open by measurement (named residual, not closed): `<link rel=dns-prefetch|preconnect>` from the scene; WebRTC closed in-realm only.
- Not evidenced: the sandbox mounted in Core/Control Center (Slice 10; Core never started), browsers other than Chrome, macOS/Linux, a browser without site isolation, CPU-burning but responsive scenes, native memory of the compiler child.

## Slice 09 - Live Board references and immutable freeze (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s09`, base `a4b39d46`)

- Contract: `docs/presentation-live-refs.md` (new) and `docs/presentation-artifacts.md` section "Snapshot package (Slice 09)"; code `jarvis/domain/presentation_live_refs.py`, `jarvis/domain/presentation_snapshot_package.py`, `jarvis/core/presentation_live_refs.py`, `jarvis/core/presentation_snapshot_packager.py`.
- Unit evidence (no network, no browser, no Core started): `tests/unit/test_presentation_live_refs.py` (42), `test_presentation_freeze.py` (25: real SQLite registry, Board memory, Studio file store, `PrefabService`, spool), `test_presentation_live_refs_docs.py` (3). Counts and neighbours: LOG.md entry "Slice 09".
- Not evidenced: packager wired in a running Core (not wired yet), sandbox receiving the resolved payload in a browser (Slice 10), macOS/Linux.
## Slice 10 - Remotion Player in Jarvis, engine gate (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s10`, base `a4b39d46`)

- Contract: `docs/remotion-isolation.md` section 10 (stage document, `frame-src`, protocol, visible states, gate, sound, residuals), `docs/presentation-engine.md` "Runtime wiring status" (gate and scene-add compatibility now wired), `docs/presentation-studio.md` (stage window), `docs/OPERATIONS.md` ("Scène Remotion jouée par Jarvis" Human checks), `docs/prefabs.md` (bundle `{kind: remotion}`).
- Real-machine evidence: `slices/10-remotion-player-host/evidence/real-player.json` (+ one JSON per scenario and screenshots `windowed`, `fullscreen`, `unavailable`, `compile_error`, `killed`) produced by `scripts/remotion_player_harness.py` at repository head `00a571b9` (rework) (clean tracked tree; Windows 11 10.0.26200, Chrome 154.0.8037.99, Node v24.18.0; isolated Core composed like `jarvis/app.py` on free ports and a throwaway data root, real compiler/esbuild, real Control Center and prefab host, real Player in a sandboxed cross-origin frame; the Remotion runtime is made `ready` by copying the small files of an existing private install and a junction to its `node_modules`: no new install, never the live profile). Verdict PASSED, 7 scenarios incl. the `frame-src` navigation measurement and its positive control. Reproduce: `python scripts/remotion_player_harness.py --runtime-dir <root>/local_capabilities/remotion/runtime --evidence <dir>`, or `JARVIS_REMOTION_RUNTIME_DIR=... pytest tests/unit/test_remotion_player_realpage_browser.py` (about 100 s).
- Unit evidence (no browser, no network): `tests/unit/test_remotion_player.py`, `test_remotion_stage_js.py` (node), `test_remotion_sandbox_server.py` (real loopback socket), `test_remotion_player_routes.py`, `test_remotion_relay.py`, `test_remotion_app_wiring.py`, `test_remotion_player_docs.py`. Counts and neighbours: LOG.md entry "Slice 10".
- Not evidenced: audio through speakers, physical Esc key, a second screen, macOS/Linux, a Chrome other than 154, a live Jarvis (never started).
## Slice 11 - Optional Remotion Studio (2026-10-09, branch `task/jarvis-remotion-presentation-integration-s11`, base `a4b39d46`)

- Contract: `docs/remotion-studio.md` (Level 2); `docs/SECURITY.md` section 19; `docs/OPERATIONS.md` "Studio Remotion optionnel"; `docs/local-capabilities.md` sections 6-7; Issue 02 point (a) partly resolved.
- Real-machine evidence: `slices/11-remotion-studio-process-ui/evidence/real-studio.json` (phases 0-10, 39 checks) + `real-studio-late.json` (phases 11-14, 10 checks) + `evidence/screens/*.png`, produced by `scripts/remotion_studio_harness.py --part early|late` after the QA rework (heads `4dbb18cd` and `a4e8eb05`, clean tree; Windows 11 10.0.26200, Node v24.18.0, Chrome 154.0.8037.99): both PASSED. Initial pass at `875407f1` (38 checks) was superseded. Isolated Core (own host/port/data root), real npm install of the capability, real prefab library, real `remotion studio` (Node, webpack, HMR), real isolated Control Center, real headless Chrome over DevTools. Reproduce: `python scripts/remotion_studio_harness.py --work-dir <short temp dir> --evidence <file>` (about 8 minutes, about 600 MB).
- Unit evidence (no network, no browser): `tests/unit/test_remotion_studio.py` (42), `test_remotion_studio_runner.py` (22), `test_remotion_studio_guard.py` (12, real Node, no Remotion), `test_remotion_studio_routes.py` (18, real Core), `test_control_center_remotion_studio.py` (17), `test_remotion_studio_docs.py` (9); opt-in `test_remotion_studio_real.py` (1, needs `JARVIS_REMOTION_RUNTIME_DIR`). Counts and neighbours: LOG.md entry "Slice 11".
- Not evidenced: macOS/Linux, a non-Chrome browser, the Human check HV-11-01, WebRTC/link-hint exfiltration from the user's browser tab (documented residual), a hostile scene run in the Studio (the Slice 06 corpus targets the Player sandbox, not the Studio).
- Rework (QA verdict REWORK, 2026-10-10): B1 Studio page vs Control Center (CSP `connect-src 'self'`, Control Center refuses another loopback port and same-site mutating requests, Studio refuses foreign Origin/Host; real-Chrome group 5b), B2 mandatory `acknowledge_unsandboxed_scene` + provenance confirmation dialog, B3 `parent.json` identity (pid + creation time) and adoption outliving the old grace. New unit evidence: `test_remotion_studio_rework.py` (40), `test_control_center_origin_ports.py` (6); guard tests 17. Counts and neighbours: LOG.md entry "Slice 11 rework".

## Slice 12 - Score to Remotion timeline bridge (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s12`, base `dcfa565d`)

- Contract: `docs/presentation-studio.md` > *Remotion timeline bridge* (anchors with `at_ms`, frame mapping, segments, the `timeline` of the playback view, follower and drift rules, authority, limits), `docs/remotion-isolation.md` sections 5 and 11 (additive `control.until`, `clock` messages, residuals), `docs/presentation-engine.md` (wiring status), `docs/presentation-mode.md` (owner map), `docs/OPERATIONS.md` ("Scène Remotion conduite par la partition" Human checks). Code: `jarvis/domain/remotion_timeline.py`, `jarvis/core/presentation_studio_playback.py` (`_resolve_timeline`, `_timeline_view`), `jarvis/core/prefab_service.py` (`remotion_composition`), `jarvis/domain/presentation_studio_scene.py` (`ScoreAnchor.at_ms`), `jarvis/runtime/{remotion_sandbox_protocol,remotion_sandbox_child,control_center_remotion_stage,control_center_remotion_frame,control_center_prefab_host,control_center_scene_page,control_center_presentation_studio_player}.js`.
- Real-machine evidence: `slices/12-score-to-remotion-runtime/evidence/real-timeline.json` (+ `timeline_bridge.json`, `timeline_two_scenes_remount.json`, `intro_hold.png`, `end_hold.png`) produced by `scripts/remotion_player_harness.py --test tests/unit/test_remotion_timeline_realpage_browser.py --slice 12 --report real-timeline.json` at repository head `74eeed68` (QA rework: hot-reload retime, variant schema v5, Player remount re-apply) (clean tracked tree; Windows 11 10.0.26200, Chrome 154.0.8037.99, Node v24.18.0; isolated Core composed like `jarvis/app.py`, free ports, temporary data root, private runtime reused by junction). Frames are read inside the sandbox: entry segment 0..29 then hold, anchor `intro` 30..74 then hold, cue 75..119, pause holds the image, resume continues, `previous` returns to 75, forged `clock` messages refused by the watchdog, an anchor-less scene plays on its own with no `timeline` in the view.
- Unit evidence (no browser): `tests/unit/test_remotion_timeline.py` (17), `test_remotion_timeline_service.py` (10), `test_remotion_timeline_composition.py` (3), `test_remotion_timeline_js.py` (22, node), `test_remotion_sandbox_child_js.py` (7, node), `test_remotion_sandbox_protocol_js.py` (16), `test_presentation_studio_player_js.py` (30). Regression net unchanged and green: `test_presentation_studio_sequence*`, `_playback_*`. Counts and neighbours: LOG.md entry "Slice 12".
- Not evidenced: audio through speakers or sync with speech, physical Esc, a second screen, macOS/Linux, a Chrome other than 154, a live Jarvis (never started), the planner/voice tools setting `at_ms` (Slices 15 and 21), Remotion props and controls through the score (Slice 13).


## Slice 13 - Typed variables and fast edits (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s13`, base `dcfa565d`)

- Contract: `docs/remotion-isolation.md` section 12, `docs/presentation-studio.md` "Typed variables and fast edits", `docs/prefabs.md` (typed variables per engine), `docs/remotion-source.md`.
- Real-machine evidence: `slices/13-remotion-controls-bridge/evidence/real-slice-13.json` (+ `typed_controls.json`, `controls_before.png`, `controls_after.png`) produced by `scripts/remotion_player_harness.py --slice 13 --test tests/unit/test_remotion_controls_realpage_browser.py` at head `24b368dc` (clean tracked tree), isolated Core, real Chrome, never the live Jarvis.
- Unit evidence: `tests/unit/test_remotion_input_props.py` (+ `tests/fixtures/remotion_input_props_cases.json`, Python and JavaScript), `test_remotion_controls.py`, `test_remotion_controls_docs.py`, `test_remotion_stage_js.py`, `test_presentation_studio_inspector_behaviour_js.py`, `test_remotion_relay.py`, `test_remotion_player.py`.
- Not evidenced: per-parameter engine labels in the manifest (not built), a Chrome other than 154, macOS/Linux, a live Jarvis.


## Slice 20 - Remotion default, Slidecar experiment, no fallback (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s20`, base `26d23678`, code head `ed2e4642`)

- Contract: `docs/presentation-engine.md` > *Human engine control* (door, actors, confirmation, diagnostics table, fail-closed guidance, legacy documents) and its wiring-status row, `docs/presentation-studio.md` > *Engine choice and Slidecar experiment*, `docs/OPERATIONS.md` (operation and one-time human check), `docs/remotion-runtime.md` section 7 and `docs/remotion-studio.md` (install and repair now relayed, nothing else).
- Real-machine evidence: `slices/20-engine-ui-policy-and-slidecar/evidence/real-slice-20.json` (+ `ui_engine_flow.json`: measured reads, exact request bodies the page sent, Core listing and diagnostics; `engine_card.png`, `engine_confirm.png`, `engine_card_390.png`, `repair_missing.png`, `repair_failed.png`, `repair_done.png`) from `JARVIS_ENGINE_UI_EVIDENCE=<dir> pytest tests/unit/test_control_center_presentation_studio_engine_browser.py`; Chrome 154.0.8037.99, Node v24.18.0, Windows 11, real Core + protocol server + Control Center on free ports and a throwaway data root.
- Unit evidence: `tests/unit/test_presentation_studio_engine_human.py` (32), `test_presentation_studio_engine_migration.py` (6, frozen v1/v2 fixtures), `test_control_center_presentation_studio_engine_js.py` (9), `test_presentation_studio_engine_tools.py` (parity, extended), `test_control_center_remotion_studio.py` (install/repair relay).
- Not evidenced: the real npm install or repair started from the page (scripted runner; Slice 04 holds the real-npm proof), a person typing the confirmation on a real desktop, macOS/Linux, a Chrome other than 154, a live Jarvis (never started), a Remotion scene compile error rendered in the card (it stays in the stage window), authentication of the actor (declaration only).

## Slice 18 - import d'un modèle Remotion amont (2026-10-10, branche `task/jarvis-remotion-presentation-integration-s18`, base `a556decd`, code `f38f351c`)

- Contrat : `docs/remotion-import.md` (Level 2), section 20 de `docs/SECURITY.md`, `docs/prefabs.md` (clés `upstream.*` vérifiées, `runtime_license`), pointeurs dans `docs/remotion-source.md` et `docs/remotion-isolation.md` ; code `jarvis/domain/remotion_upstream.py`, `remotion_import.py`, `jarvis/core/remotion_import_service.py`, `jarvis/protocol/remotion_import_routes.py`, `jarvis/adapters/https_upstream_fetcher.py` (+ faux), `jarvis/ports/upstream_fetcher.py`.
- Preuve réelle (réseau GitHub, vrai compilateur, Chrome 154) : `slices/18-upstream-template-import/evidence/real-import.json` (rapport, tête `f38f351c`, arbre propre), `real_import_render.json` + `imported.png` (import MIT de `hongjiapeng/remotion-workflow-visualizer@730615b7`, compilé et joué), `real_refusals.json` (5 refus réels typés + propriétaire hors liste). Rejeu : `JARVIS_REMOTION_IMPORT_NETWORK=1 python scripts/remotion_player_harness.py --test tests/unit/test_remotion_import_real.py --slice 18 --report real-import.json --runtime-dir <runtime/> --evidence <dossier>`.
- Fait vs inférence : fait (mesuré) = import, compilation, rendu et refus ci-dessus ; fait (tests sans réseau) = refus d'hôte, redirections, liens, zip-slip, doublons, bombes, SHA non attesté, provenance non falsifiable ; non prouvé = import par l'agent ou la voix (volontairement absent), promotion vers la bibliothèque (Slice 19), macOS/Linux.


## Slice 15 - Remotion scene generator behind the authoring tools (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s15`, base `e7100b75`)

- Contract: `docs/presentation-studio.md` > *Remotion scenes: the generator (Slice 15)* (generator object, `theme` prop, motion kit, compile validation, engine policy, TSX rules, live references, inspiration), the rule table (64 rules, parity-tested), `docs/presentation-engine.md` (the Slice 20 agent carve-out closed), `docs/presentation-live-refs.md` > *Authoring*, `docs/remotion-source.md` section 9 bis, `docs/remotion-import.md` section 7 bis, `docs/prefabs.md` (planner row), `docs/OPERATIONS.md` ("Présentation rédigée par l'agent en Remotion"), `docs/presentation-studio-release.md` > *Real-model release gate, re-run for Remotion scenes* and check H-12. Code: `jarvis/domain/presentation_studio_authoring_{remotion,tsx,kit}.py`, the Remotion rules in `presentation_studio_authoring_gate.py`, `jarvis/core/presentation_studio_authoring.py` (compile, engine policy, live references, inspiration), `jarvis/core/v2_app.py` (`LiveRefResolver`, `_authorised_boards`, `authoring_compiler`), `jarvis/protocol/client.py` (`AUTHORING_TIMEOUT_S`).
- New rule codes (all in the table of `presentation-studio.md`): `prefab_engine_mismatch`, `tsx_compile`, `tsx_theme_unread`, `tsx_color_hardcoded`, `tsx_text_hardcoded`, `tsx_static_scene`, `tsx_interpolate_unclamped`, `tsx_props_unread`, `tsx_props_undeclared`, `tsx_monolith`, `tsx_layout_monotone`, `tsx_anchor_range`, `tsx_anchor_untimed`, `tsx_live_ref_invalid`, `tsx_live_ref_unresolved`, `tsx_inspiration_unconfirmed`.
- Real-machine evidence (a), scripted end to end: `slices/15-remotion-one-shot-authoring/evidence/real-slice-15.json` (+ `authoring_e2e.json`, `authoring_exploratory.json`, `authoring_refused.json` and screenshots) produced by `scripts/remotion_player_harness.py --test tests/unit/test_presentation_studio_authoring_remotion_browser.py --slice 15` at repository head `6b00292b` (tracked tree clean; Windows 11 10.0.26200, Chrome 154.0.8037.99, Node v24.18.0; isolated Core composed like `jarvis/app.py` on free ports and a throwaway data root, real compiler/esbuild, real Control Center, real Player; private runtime `jrs10` reused by junction; never the live Jarvis). Reads inside the sandbox: titles, ground / accent colours and font of each scene equal the stored art direction; an edit of `props.theme.accent` changes the colour in the same sandbox document.
- Real-machine evidence (b), real model: `slices/15-remotion-one-shot-authoring/evidence/authoring-real-traces.run-a.{json,md}` (rich brief, vague / exploratory, one-shot report) and `authoring-real-traces.run-b.{json,md}` (custom layout, hostile text; Claude `sonnet` through the CLI, the real prompt program, the real MCP servers, a real Remotion Core; planner fingerprint = the code's, checked by `scripts/verify_release.py`). Cost USD 0.74 for the committed evidence, about 3.0 over every iteration. Raw streams stayed outside the repository. Redaction as for Slice 22: ids are aliases, tool arguments' texts `<text>`, scene titles and final answers quoted (synthetic subjects).
- Scripted rig evidence: `slices/15-remotion-one-shot-authoring/evidence/fake-author-rig.{json,md}` (redacted, compared with the live rig by `test_presentation_studio_authoring_rig.py`). Not a trace of Claude.
- Real compile (no browser): `JARVIS_REMOTION_RUNTIME_DIR=<runtime/> pytest tests/unit/test_presentation_studio_authoring_remotion_real.py` (6): guide example, rig slide, exploratory fan, the three layouts and the kit compile; syntax error with file / line / column, forbidden import, missing default export; a whole deck compiled before it is written; runtime not ready is the 409.
- Not evidenced: whether a first draft is presentable to a person (H-12); a brand sheet or two conflicting brands with a real model; live Board data delivered to a playing scene (not wired); an upstream inspiration with a real model; macOS/Linux; a Chrome other than 154; a live Jarvis (never started).

## Slice 14 - Remotion source edit and safe hot reload (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s14`, base `26d23678`)

- Contract: `docs/presentation-studio.md` > *Hot reload contract* > *Remotion sources (Slice 14)*, `docs/remotion-isolation.md` section 13, `docs/OPERATIONS.md` (agent source edit), `docs/presentation-engine.md` (typed build failure, no fallback), `docs/remotion-source.md` sections 6 and 8.
- Real-machine evidence: `slices/14-source-edit-hmr-and-agents/evidence/real-slice-14.json` (+ `source_edit_hmr.json`, `before.png`, `edited.png`, `broken.png`, `restored.png`) produced by `scripts/remotion_player_harness.py --slice 14 --test tests/unit/test_remotion_source_edit_realpage_browser.py` at head `b8c7f86f` (clean tracked tree), isolated Core, real esbuild, Chrome 154, never the live Jarvis.
- Unit evidence: `tests/unit/test_remotion_source_edit_domain.py` (26), `_service.py` (26, FakeBuilder with the real error contract, real stores), `_routes.py` (2), `_docs.py` (4, pins the codemods decision to the lock), `_real.py` (1, real compiler, opt-in), `_realpage_browser.py` (1, opt-in), `test_presentation_studio_reload_host_js.py` (+3, render proof), `test_remotion_sandbox_child_js.py` (+1, error boundary).
- Defect found by the real run and fixed (Slice 10 code): a scene that compiles but throws at render was reported as mounted and replaced the good one; see LOG.
- Not evidenced: TypeScript type errors (no type checker in the pinned lock), a render error after the first frame as a rollback, macOS/Linux, a Chrome other than 154, a live Jarvis, the voice/brain delegating the edit end to end (Slice 21 owns the tool layer; this Slice reuses `scene.source_request` and exposes the HTTP door a sub-agent calls), `@remotion/codemods` (decided not to use, with evidence).
## Slice 16 - Render and export: MP4, stills, PDF, exact origin links (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s16`, base `a556decd`)

- Contract: `docs/remotion-render.md` (Level 2: decisions, pipeline, settings and bounds, isolation of the render process, job model, derivative Artifact and its metadata, routes and codes, residuals); `docs/presentation-artifacts.md` > "Renders (Slice 16)"; `docs/SECURITY.md` control 20; `docs/OPERATIONS.md` "Export d'une presentation"; `docs/artifacts.md` > "Presentation derivatives".
- Real-machine evidence: `slices/16-render-export-and-derived-artifacts/evidence/real-render.json` (PASSED 69/69 after the QA rework, three runs at `4df3d83b`, product tree clean, Windows 11 10.0.26200, Node v24.18.0, Chrome 154.0.8037.99, Remotion 4.0.534) with `evidence.mp4` / `evidence_still.png` / `evidence.pdf`, produced by `scripts/remotion_render_harness.py --only <scenarios> --append`; real-browser export `tests/unit/test_presentation_render_real.py` (opt-in `JARVIS_REMOTION_RUNTIME_DIR`) with `s16-board-before-export.png` / `s16-board-after-export.png`.
- Unit evidence: `tests/unit/test_presentation_render_domain.py` (44), `_service.py` (43), `_runner.py` (35), `test_render_guard.py` (6, real Node), `_routes.py` (23, real Core), `_relay.py` (5), `_docs.py` (12), `test_workspace_presentations_js.py` (+8). Neighbours listed in LOG.md "Slice 16".
- Not evidenced: audio of an exported video (never listened to), a player other than ffprobe/Chrome's `<video>`, macOS/Linux, a Chrome other than 154, Edge, a live Jarvis (never started), voice/Tool Brain entry points (Slices 20-21), the Human check HV-16-01.
- Rework (QA REWORK, 2026-10-10): `evidence/real-render.json` now also covers `sandbox` (chrome://sandbox ON/OFF probe, typed sandbox failure; `sandbox-probe.json`), `burst` (40 concurrent requests -> 8 accepted) and `two_cores` (render lock); `test_presentation_render_real.py` 2 tests (the second opens a > 8 MiB 4K render whole through the Control Center relay); LOG.md "Slice 16 rework" lists B1, M2, M3, P4-P8 and the counts.


# Slice 19 evidence (2026-10-10, code `4fd71fcb`, branch `task/jarvis-remotion-presentation-integration-s19`)

| Claim | Where it is proven |
| --- | --- |
| A whole presentation is promoted as ONE record, nothing is published to the shared library, sources embedded by content hash | `tests/unit/test_presentation_studio_template_service.py::test_a_whole_variant_is_promoted_as_one_artefact_and_publishes_no_scene_to_the_library`, `test_presentation_studio_template_remotion.py::test_a_remotion_presentation_is_one_artefact_with_embedded_sources_and_publishes_nothing` |
| Remotion promotion: TSX untouched, engine-tagged v3 catalog, guards refuse, leaks block (project, Board, path, content) | `test_presentation_studio_template_remotion.py` (first 6 tests) |
| Modified imports are never promoted as verified; forged embedded claims refused before anything is created | `test_a_modified_import_can_never_be_promoted_as_verified`, `test_an_embedded_intact_import_is_reverified_at_instantiation_and_a_forged_claim_is_refused` |
| Restrictive upstream licence needs a named acknowledgement (library scene and presentation record) | `test_a_restrictive_upstream_licence_needs_an_explicit_named_acknowledgement`, `test_a_restrictive_licence_also_gates_a_presentation_template` |
| Score skeleton, no words, instantiated | `test_presentation_studio_template_score.py`, `test_the_score_travels_as_a_skeleton_without_speech_cues_or_control_values`, `test_presentation_studio_release_flows.py::test_journey_compare_mix_and_promote_a_template_then_reuse_it` |
| Newer-version notice is read-only; a trial is a child variant; the original is byte-identical; nothing rebound; incompatible/non-native versions refused; retention keeps both pins; declined trial rolls back | `tests/unit/test_presentation_studio_upgrades.py`, `_upgrades_routes.py` |
| The same, in a real Chrome against an isolated Core and the real Control Center | `tests/unit/test_presentation_studio_explorer_upgrades_browser.py` ; screenshots `tasks/jarvis-remotion-presentation-integration/slices/19-promotion-pins-and-upgrades/evidence/upgrades-*.png` |
| Contracts | `docs/presentation-studio.md` (*Template and prefab promotion contract*, *Newer prefab versions and trial variants*), `docs/prefabs.md`, `docs/remotion-import.md` section 11, `docs/local-data.md` |

# Slice 21 evidence (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s21`, base `122fdcfe`)

| Claim | Where it is proven |
| --- | --- |
| A separate small server carries the Remotion verbs; `jarvis-presentation` budget (17 100 B) is untouched; the global gate rose deliberately | `tests/unit/test_mcp_catalog.py::test_the_remotion_server_lists_its_tools_in_order_within_its_budget`, `test_the_whole_native_surface_declared_to_the_brain_stays_within_its_budget` (measure: 5 178 B, global 109 726 B / 110 000), `docs/mcp/tool-contract.md` section 10.17 |
| No install, repair, export, cancel, import or trial from a turn that is not an addressed user turn: zero Core calls | `tests/unit/test_remotion_mcp_tools.py` (`..._send_nothing_to_core`, 4 families), `test_remotion_mcp_server.py::test_over_the_wire_an_ambient_turn_cannot_install_export_import_or_try` |
| A source request needs the same turn; a props edit does not | `tests/unit/test_remotion_mcp_ownership.py` (real Core) |
| The Studio is never opened and never acknowledged by an agent; a licence is never acknowledged by the brain | `test_remotion_mcp_tools.py::test_studio_never_opens_and_never_acknowledges_...`, `..._licence_to_acknowledge_is_left_to_the_user`, `test_remotion_mcp_server.py::test_an_argument_the_model_must_never_send_is_refused_before_any_tool_runs`, `..._never_name_the_engine_selection_policy_or_the_unsandboxed_acknowledgement_route` (AST) |
| No engine argument on any native tool | `test_remotion_mcp_server.py::test_no_native_tool_of_any_server_takes_an_engine_parameter`, `test_presentation_studio_engine_tools.py` |
| Ids come from the state; typed Core failures are said as they are | `test_remotion_mcp_tools.py` (`invalid_id`, `invalid_version`, `presentation_render_*`, `origin_not_allowed`, `license_*`) |
| Real-model behaviour of the brain with these tools (7 scenarios, 20 turns, $1.08) | `slices/21-voice-tools-and-toolbrain/evidence/remotion-real-traces.{md,json}` (final), `evidence/first-run/` (before the fixes), `evidence/trace-analysis.md` (findings T1-T6), harness `tests/replay/remotion_mcp_real_trace.py` |
| Contracts | `docs/remotion-runtime.md` section 13, `docs/tool-brain-contracts.md` section 19, `docs/remotion-render.md`, `docs/remotion-import.md`, `docs/remotion-studio.md`, `docs/presentation-engine.md` |
| Not evidenced | real voice (HV-21-01), a real Control Center page answering the attestation, the sub-agent's own `source-edits` call, real-model sessions for import and upgrades, real Remotion routes under the model (scripted capability stub) |
