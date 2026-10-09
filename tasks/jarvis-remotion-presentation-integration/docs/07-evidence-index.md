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
