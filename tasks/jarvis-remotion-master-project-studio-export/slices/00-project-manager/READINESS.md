# Slice 00 — Readiness (agent 0)

Date: 2026-10-13. Agent 0 = Claude Code orchestrator (handle-task, start mode).

## Declared state

- Repository `C:/Projects/jarvis` (GitHub `edebazelaire-circoe/Jarvis`). `origin/main` = `d101d887`, the handoff's planning reference exactly.
- Task branch `task/jarvis-remotion-master-project-studio-export` from `origin/main` (`d101d887`), upstream unset. No `dev` branch in this repository: `main` is the base (same as every previous handoff).
- `docs/workflows/AGENT_TASK_LIFECYCLE.md` does not exist in this repository: fallback = the Drive queue IDs recorded in project memory (`to-do` `1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm`, `current` `1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D`, `done` `16yBLZRVOEbfDAN_CRh5722bkN46IUmo7`). The Drive connector cannot move folders: the Human moves the handoff `to-do` → `current` (asked 2026-10-13).
- Handoff mirrored byte for byte (42 files, every JSON parses) as S0 `4bba7217`.
- Worktrees owned by this task: `C:/Projects/jarvis/bmp` (task branch, implementers), `C:/Projects/jarvis/bmq` (detached, baseline then QA), `C:/Projects/jarvis/bms` (reserved for a parallel Slice 06). All other worktrees (`bqa`, `bqb`, `bwt`, `bwt2`, `bsc`, `brn`, `brq`, `brs3`, …) belong to other tasks/sessions. The main checkout stays on `main` (the Human's live Jarvis runs from it).
- Real Remotion runtime for real tests: `C:/Projects/jarvis/_remotion-runtime-gate` (read only; `JARVIS_REMOTION_RUNTIME_DIR`), copied into throw-away roots as the previous task did. Pinned set `remotion`, `@remotion/{bundler,cli,player}` 4.0.534, `react` 19.3.0 (`jarvis/domain/remotion_capability.py:16-27`).

## Blind audit (before reading the handoff conclusions)

Run by an Explore agent given only the Slice 00 goal and forbidden to read this task folder. Owners at `d101d887`:

| Concern | Owner (file:line) |
| --- | --- |
| Studio workspace plan | `jarvis/domain/remotion_studio.py::plan_workspace` L184-209: copies one scene's `src/**`+`public/**`, generates `studio-root.tsx` (one `<Composition>` from the manifest's declared composition) + `package.json` `jarvis-studio-scene`. Reused unchanged by render (`presentation_render_plan.py:19,100`). |
| Studio identity / state | `StudioPin(prefab_id, version)` L113-121, `parse_open` L145 requires `acknowledge_unsandboxed_scene`; `StudioState` `state.json` schema 1 stores no presentation/variant id. |
| Studio service | `jarvis/core/remotion_studio_service.py` `RemotionStudioService` L44: `open` L238, `_start_locked` L293, `enforce_shape` L329, `sync` L369, `publish` L460 → `VariantScenePublisher` (`remotion_studio_publish.py:42-61`) → `apply_source_edit`. |
| Studio runner | `jarvis/adapters/remotion_studio_runner.py`: layout `<runtime>/studio/…`, argv `remotion studio studio-root.tsx --port … --ipv4 …` L602-635, top-level shape = `src/`, `public/` + generated files; `MAX_WORK_FILES=400`, `MAX_WORK_BYTES=64 MiB`. |
| Studio routes / UI | `jarvis/protocol/remotion_studio_routes.py` (`/v1/local-capabilities/remotion/studio`), relay `remotion_studio_relay.py`; Variants door `control_center_presentation_studio_explorer_remotion.js` L99-114, L410-467 (`open {prefab_id, version}`); rail `control_center_presentation_rail.js:84,381-397`. |
| Scene source model | `jarvis/domain/remotion_source.py`: manifest v2, `src/**` ≤ 64 modules / 1 MiB, `public/**` ≤ 64 assets / 16 MiB (audio/video allowed), declared `Composition(id,w,h,fps,frames)` L170, `source_digest` L320. Store `<data_root>/prefabs/<id>/<v>/`. |
| Source-edit door | `PresentationStudioReloadService.apply_source_edit` (`jarvis/core/presentation_studio_reload.py:258`), CAS on `variant.revision` L335, `restore_version`. |
| Guards | imports `react`, `react/jsx-runtime`, `react/jsx-dev-runtime`, `remotion` only (`remotion_compile.py:34`, enforced in `runtime-host.mjs:66-78`); isolation rules `remotion_isolation.py:78-115`. `Audio`/`Video`/`OffthreadVideo` from `remotion` allowed. |
| Presentation / Variant | `PresentationVariant` (`presentation_studio.py:311-322`): ordered `scenes`, `revision`; `StudioScene` exact `prefab` pin + `props`/`data`. **Engine is per presentation** (`Presentation.engine`, L269), not per scene. |
| Render | `jarvis/domain/presentation_render.py`: one scene per job (`scene_target` L291-314 refuses a multi-scene snapshot without `scene_id`), `MAX_RENDER_FRAMES = 3600` (L35), `SETTINGS_KEYS` L50. Plan `presentation_render_plan.py::plan_files` L85-103. Snapshot package ≤ 600 files / 64 MiB (`presentation_snapshot_package.py:31-32`) already holds the full variant + every pinned source. Service `presentation_render_service.py` `export` L218 / `submit` L236 / `_execute` L546 / `_finalize` L602. Host `render-host.cjs` bundles `work/studio-root.tsx`, `selectComposition` + declared-config check (`composition_mismatch`), `renderMedia({muted:false})`. Verification `video_facts` (`presentation_render_output.py:135-152`) checks the video stream only — **audio is not verified**. |
| Variants playback | `PresentationStudioCompositionClock` (`jarvis/core/presentation_studio_composition_clock.py`) + pure `jarvis/domain/composition_clock.py` (master fps = max fps) + JS port and `control_center_presentation_studio_sequencer.js` (one sandboxed Player per scene). |
| Agent / MCP | `presentation_source` read/write/preview (`presentation_studio_mcp.py:363-377`); native authoring (`Authoring.NATIVE`, `NATIVE_LOOP`); `remotion_export` (`remotion_mcp.py:164-176`, `EXPORT_SETTINGS` incl. `scene_id`, user turn + `user_request`); budgets in `test_mcp_catalog.py` (presentation 21 000 B, remotion 5 400 B, declared 113 700 B). |
| Single-scene doc sentences | `docs/remotion-render.md:12,43,140,160,211`; `docs/remotion-studio.md:10-11,20-35,176,190`; `docs/presentation-studio.md:2394-2403` (**"Rejected for now: a generated multi-scene root"**, pinned by `test_presentation_experience_contract_docs.py:107`), L2713, L2719. |
| Harnesses | `RemotionStack` (`tests/fakes/remotion_player_stack.py:75`), `JARVIS_REMOTION_RUNTIME_DIR`, gate world (`presentation_playback_gate_world.py`, 9 scenes, **mixed fps**), CDP helper `_remotion_stage_browser.mjs`, release gates `test_remotion_release_gate.py`, `test_presentation_studio_release_gate.py`, `test_presentation_playback_release_gate_browser.py`. Layout pins: `test_presentation_render_domain.py:244`, `test_presentation_render_service.py:96-101`, `test_remotion_studio.py:77`. |

## Baseline tests (branch point `d101d887`)

See `baseline.md` (filled when the detached `bmq` sweep reports). Gate rule inherited from the previous task: run `test_presentation_studio_reload*` / `test_scene_variants_crash*` one file per process.

## Reconciliation with the handoff

The handoff's "current-state facts" are all confirmed with file:line above. Additions and corrections the handoff does not state:

1. **A documented prior decision rejects "a generated multi-scene root"** (`docs/presentation-studio.md:2394-2403`) and lists four security preconditions for a future review (guards hold for N merged sources, per-scene failure isolation with an error boundary per `<Sequence>`, combined size/compile budget + same CSP, pins and hot-reload gate still name one scene per mounted source). That rejection was made **for the Variants Player sandbox**. The user's mandate (D1, D6, D7) now explicitly asks for a merged master root in **Studio and render** only; the Player stays per scene (phase C deferred). Not a conflict needing the Human: **Slice 02 must write the security review answering those four points for the Studio and render contexts**, keep the Player sentence true and accurate, and update the pinned doc test deliberately.
2. **`MAX_RENDER_FRAMES = 3600`** caps any export at 2 min @ 30 fps. A whole-variant export needs its own explicit bound (D8: no accidental narrowing). Slice 02 fixes the master bound (frames, wall time, disk) without changing the scene bound.
3. **Audio is not verified** by `video_facts` (only "one video stream"). Slice 06 adds an audio-stream check when the authored sources contain audio.
4. **Engine is per presentation**; per-scene "is Remotion" is inferred from the manifest `source` block. The planner's "non-Remotion scene" reason reads both.
5. **Studio trust acknowledgment is per pin** (`acknowledge_unsandboxed_scene`). A master target runs N scene sources unsandboxed in one Node/Studio process: Slice 02 defines the master acknowledgment (bound to `project_key`, naming the scene count).
6. **Bounds differ**: Studio workspace 400 files / 64 MiB, snapshot package 600 files / 64 MiB, per-scene 64+64 files. Slice 02 states the master project bound as the minimum that the Studio workspace and render job already enforce.
7. **The gate world deck mixes fps**: under P1 it is the natural master-incompatible fixture (legacy lane must keep working).
8. The Studio's top-level shape (`src/`, `public/`, generated files) already accepts the handoff's proposed master layout (`src/master/…`, `src/scenes/<id>/…`, generated root). No shape widening needed.
9. Slice 01's code/runtime owner inventory is largely done by this audit; Slice 01 keeps the **runtime experiments** (child scene inside `<Series>` with `useVideoConfig`/`useCurrentFrame`, audio + video, `staticFile` collisions, real bundle/render of a 2-3 scene master under the pinned runtime) and the old-caller compatibility map.

No D1-D10 conflict. No persistence change expected (derive from pins; the snapshot already freezes everything a master render needs).

## Decisions by agent 0 (Human delegated autonomy)

- **Workspace Task Type**: the vocabulary does not exist in this repository (waived by the Human on every previous handoff). Waived; recorded per Slice as `n/a (waived)`.
- **QA tiers** (blocking / polish / issue dispositions; mutations only on `critical`):
  - 01 audit — `docs` (agent 0 reviews the evidence);
  - 02 contract — `docs` + doc tests;
  - 03 planner — `glue` + `code-review`;
  - 04 materialization — `critical` (merged sources, path safety, bounds) + real compile;
  - 05 master Studio — `critical` + `runtime-validation` (real Studio, real Chrome);
  - 06 whole export — `critical` + `runtime-validation` (real render, ffprobe incl. audio);
  - 07 voice — `glue` + `agent-trace-analysis` (real traces, Sonnet);
  - 08 Variants entrypoints — `ui` (real Chrome at 800×600 / 1280×720 / 1920×1080 + fullscreen, `/impeccable`);
  - 09 release — wide sweep + real journeys.
- **Pipeline**: 01 → 02 → 03 → 04 sequential in `bmp`; then 05 (in `bmp`) and 06 (in `bms` on `task/…-s06`, merged `--no-ff`) in parallel; 07 → 08 → 09. QA in detached `bmq`. Reworks on `fix/rmp-sN-rework`.
- **Dispatch gate**: Slices 01 and 02 write no product code and may start before the baseline table is recorded; Slice 03 (first product code) is not dispatched until `baseline.md` is committed.

## Readiness

**READY.**
