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

## Slice 12 - Score to Remotion timeline bridge (2026-10-10, branch `task/jarvis-remotion-presentation-integration-s12`, base `dcfa565d`)

- Contract: `docs/presentation-studio.md` > *Remotion timeline bridge* (anchors with `at_ms`, frame mapping, segments, the `timeline` of the playback view, follower and drift rules, authority, limits), `docs/remotion-isolation.md` sections 5 and 11 (additive `control.until`, `clock` messages, residuals), `docs/presentation-engine.md` (wiring status), `docs/presentation-mode.md` (owner map), `docs/OPERATIONS.md` ("Scène Remotion conduite par la partition" Human checks). Code: `jarvis/domain/remotion_timeline.py`, `jarvis/core/presentation_studio_playback.py` (`_resolve_timeline`, `_timeline_view`), `jarvis/core/prefab_service.py` (`remotion_composition`), `jarvis/domain/presentation_studio_scene.py` (`ScoreAnchor.at_ms`), `jarvis/runtime/{remotion_sandbox_protocol,remotion_sandbox_child,control_center_remotion_stage,control_center_remotion_frame,control_center_prefab_host,control_center_scene_page,control_center_presentation_studio_player}.js`.
- Real-machine evidence: `slices/12-score-to-remotion-runtime/evidence/real-timeline.json` (+ `timeline_bridge.json`, `timeline_two_scenes_remount.json`, `intro_hold.png`, `end_hold.png`) produced by `scripts/remotion_player_harness.py --test tests/unit/test_remotion_timeline_realpage_browser.py --slice 12 --report real-timeline.json` at repository head `74eeed68` (QA rework: hot-reload retime, variant schema v5, Player remount re-apply) (clean tracked tree; Windows 11 10.0.26200, Chrome 154.0.8037.99, Node v24.18.0; isolated Core composed like `jarvis/app.py`, free ports, temporary data root, private runtime reused by junction). Frames are read inside the sandbox: entry segment 0..29 then hold, anchor `intro` 30..74 then hold, cue 75..119, pause holds the image, resume continues, `previous` returns to 75, forged `clock` messages refused by the watchdog, an anchor-less scene plays on its own with no `timeline` in the view.
- Unit evidence (no browser): `tests/unit/test_remotion_timeline.py` (17), `test_remotion_timeline_service.py` (10), `test_remotion_timeline_composition.py` (3), `test_remotion_timeline_js.py` (22, node), `test_remotion_sandbox_child_js.py` (7, node), `test_remotion_sandbox_protocol_js.py` (16), `test_presentation_studio_player_js.py` (30). Regression net unchanged and green: `test_presentation_studio_sequence*`, `_playback_*`. Counts and neighbours: LOG.md entry "Slice 12".
- Not evidenced: audio through speakers or sync with speech, physical Esc, a second screen, macOS/Linux, a Chrome other than 154, a live Jarvis (never started), the planner/voice tools setting `at_ms` (Slices 15 and 21), Remotion props and controls through the score (Slice 13).

