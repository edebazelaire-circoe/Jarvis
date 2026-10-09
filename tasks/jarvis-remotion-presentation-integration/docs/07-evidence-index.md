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
