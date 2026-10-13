# Slice 01 — Current-state and master-compatibility audit

Date: 2026-10-13. Worktree `bmp`, branch `task/jarvis-remotion-master-project-studio-export`, base HEAD `495cd96d`.
Work Agent (audit only, no product code). Task Type: n/a (waived).

Runtime: the pinned gate runtime `_remotion-runtime-gate` (remotion, @remotion/bundler, @remotion/renderer **4.0.534**, react 19.3.0), used read-only through a directory junction from a throw-away root, as `provision_runtime` does. Browser: the host Chrome 155. Host: i7-12700H, 20 logical CPUs, 16 GB RAM (about 3.5 GB free during the runs). No live Jarvis was touched. No Jarvis data root was used.

Evidence (`evidence/`, 290 KB, Windows user and home redacted):
- `control-project/`: `build_project.py` generates the control master project, i.e. `src/master/*`, `src/scenes/<id>/**`, a merged `public/` and a root. `probe.cjs` is an unguarded driver that runs real `bundle` + `selectComposition` + `renderMedia`/`renderStill` and collects `useCurrentFrame`/`useVideoConfig` probes from the browser console. `run_real_host.py` runs the **real guarded** `render-host.cjs` + `render-guard.cjs` from the worktree on the same project. The folder also holds `bundle_only.cjs`, `census.py`, `collect.py` and `jobs_main.json`.
- `generated/`: the generated `studio-root.tsx`, `Presentation.tsx` and `Boundary.tsx`, the files of one namespaced scene (`scene-a/`), and the guard probe scene.
- `results/`: `probe-results.json` (each job: ok/error, the composition as selected, per-scene first/last local frame, `useVideoConfig` values), `real-host-renders.json` (real host: result, egress, ffprobe, silencedetect) and `census.json`.
- `frames/`: 11 PNGs at 640x360, 10-28 KB each.

Reproduce:
1. `python build_project.py <work> <media> [--with-clip]`
2. `node probe.cjs <runtime> <work> <out> jobs_main.json`
3. `python run_real_host.py <scratch> MASTER-OK 640 360 30 180`

`<runtime>/node_modules` is a junction to the gate. Media: `tone.wav` comes from the pinned ffmpeg `sine` filter. `clip.mp4` is rendered by the `CLIP` composition of the same project, because the pinned ffmpeg has no video source filter.

---

## A. Runtime experiments (pinned 4.0.534)

### A1. A child scene inside `<Series>`: `useCurrentFrame` and `useVideoConfig`

Fact: each scene sits in `<Series.Sequence durationInFrames={d}>` and starts at **local frame 0** at every boundary. In `MASTER-OK` (180 frames: a 30, b 45, c 60, c2 45), the probes show these local frames:
- a: 0..29
- b: 0..44
- c: 0..59
- c2: 0..44

Inside the scene, `useVideoConfig()` returns:
- `width`, `height` and `fps` of the **master** composition;
- `durationInFrames` of the **enclosing Sequence**, not of the master (b reads 45; the master is 180).

The code confirms it. `remotion/dist/cjs/use-unsafe-video-config.js` overrides `width`/`height`/`durationInFrames` from `SequenceContext`. A `<Sequence>` can carry `width`/`height` props. **No Sequence prop overrides `fps`.** `id`, `defaultProps` and `props` are the master's.

Evidence: `results/probe-results.json` (jobs `ok`), `frames/ok-f0029.png`, `ok-f0030.png`, `ok-f0090.png`.

Consequence for Slice 02:
- Set each scene's Sequence `durationInFrames` to its **declared** `composition.duration_in_frames` (from `source.json`), never to a score target.
- Then a scene under a common spec (P1) observes exactly the config it observes standalone.
- The master duration is the sum of the declared durations, with zero overlap, since no transition exists today (`composition_clock.py` docstring).
- Residual differences: `useVideoConfig().id`, `.props` and `.defaultProps` belong to the master, and `getInputProps()` would return the master's input props. The census found no use of either in fixtures, guides or shipped code. Scenes must receive their props as React props of the mounted component, not as `inputProps`.

### A2. Mixed fps and mixed dimensions

Mixed fps cannot be mapped. Scene `d60` was authored for 60 fps and 120 frames (2 s). Mounted in a 30 fps master, it reads `fps=30`. At local frame 59 (`frames/mixed-f0089.png`):
- the frame-driven bar (`interpolate(frame,[0,120])`) is at 49 %;
- the seconds-driven bar (`frame/fps/2`) is at 98 %.

Either the scene lasts 4 s instead of 2 s (with 120 frames), or a converted 60-frame Sequence cuts frame-driven animation in half. No Remotion primitive gives a child its own fps. The current lane hides this with one Player per scene, and the composition clock uses `master fps = max`.

Mixed dimensions can be mapped only by changing pixels:
- Without a Sequence size, a portrait scene reads the master `640x360`, so its layout reflows.
- With `<Sequence width={360} height={640}>`, it reads `360x640` but is drawn in a 360x640 box clipped by the 640x360 frame. Its bottom-right marker is invisible (`frames/seqdims-f0000.png`).

Mapping dimensions therefore needs scaling or letterboxing, which is a visual change.

Consequence: P1 is confirmed. The master is ready only when every scene declares the same `(width, height, fps)`. Otherwise it fails closed with a typed reason, and the legacy lane keeps working.

### A3. Audio and video from `staticFile()` inside sequenced scenes

Setup: scene b holds `<Audio src={staticFile('tone.wav')}>` (1.5 s). Scene c holds `<OffthreadVideo>` and scene c2 holds `<Video>` of `clip.mp4`, whose 2 s clip carries the same 1.5 s tone.

Results:
- **Probe MP4:** h264 640x360 30/1, 180 frames, 6.000 s; **aac 48 kHz stereo**, 6.016 s.
- **silencedetect −40 dB:** silence 0–1.000 s, sound 1.000–4.000 s, silence 4.000–4.500 s, sound from 4.500 s. That is b at 1.000 s, the c clip audio at 2.500 s (it ends 1.5 s later), and the c2 clip audio at 4.500 s.
- **Offsets:** every audio offset lands on its boundary within 1 ms.
- **Video:** the video media starts at its own frame 0 at the boundary. At c2 local frame 15 the clip box is at x=60 = 15*4 (`frames/real-ok-t5.0.png`, `ok-f0090.png`).
- **Real guarded host:** the same project rendered by the real `render-host.cjs` + `render-guard.cjs` gives the identical result: ok, 15.2 s, the same ffprobe and silences.
  - Its egress: `browser_launches=1`, `sandbox=true`, `blocked_connect=0`.
  - `blocked_spawn=5` were Remotion's `execSync:nproc` CPU probes.
  - `proxy_denied=16` were Chrome's own Google update hosts.
  - Neither affected the output.

Evidence: `results/real-host-renders.json`.

Consequence:
- D8 holds: `Audio`, `Video` and `OffthreadVideo` from `staticFile` keep working in a master, and timing is native.
- Slice 06 should add the audio-stream check (Readiness item 3). Measure it with silencedetect or stream presence via the pinned ffprobe, because `video_facts` checks only the video stream.

### A4. `staticFile()` collisions and namespacing

- **Collision:** scenes f and g each brought their own `public/x.png`, red and blue. A merged `public/` holds one file, so **g renders f's red image** (`frames/collide-f0000.png`, `collide-f0015.png`). This is silent substitution with no error.
- **Namespacing:** asset `public/scenes/h/logo.png` with an unchanged `staticFile('logo.png')` makes the browser request `/public/logo.png`, which returns 404. `renderStill` then fails: `Error loading image with src: http://localhost:3000/public/logo.png`.
- **Consequence:** namespacing assets under `public/scenes/<id>/` **requires rewriting every `staticFile` string**. That is impossible for computed strings (`staticFile(\`${name}.png\`)`) and forbidden by P2/D9.

P2 is confirmed. Merge `public/**` by exact path:
- identical bytes: de-duplicate;
- different bytes: typed collision naming the path and both scenes;
- never rewrite a string.

Two refinements:
- **Compare case-folded paths.** On NTFS `Logo.png` and `logo.png` are one file. Equal folded paths whose exact spelling differs count as a collision.
- **Frozen Board live copies go to `public/live/<name><ext>`** (`presentation_render_plan.py` `LIVE_PUBLIC_DIR`). They live per pin (`presentation_snapshot_packager.py:327`). Two different pins with the same live ref name collide under the same rule.

Practical risk: authored scenes name assets at the `public/` root (`'public/x.png'` in the guide, `authoring_guide.py:266`). Per-scene narration such as `voice.mp3` will collide routinely. **Slice 07 must make authoring choose collision-free names at creation time**, for example a scene-key prefix written by the author into both the path and the `staticFile` literal. That is source authoring, not rewriting.

### A5. Relative imports after namespacing

The scene modules sit under `src/scenes/<id>/`:
- `Scene.tsx` imports `./parts/Panel`;
- `Panel.tsx` imports `./deep/theme`;
- `theme.ts` re-exports from `../../palette`.

The real bundler resolves the graph unchanged for all 10 scenes. The bundle succeeds, and the accent bar drawn from `palette.ts` appears in every frame.

Entry mapping: `src/Scene.tsx` becomes `src/scenes/<id>/Scene.tsx`, imported by the generated `src/master/Presentation.tsx` as `../scenes/<id>/Scene`. Paths stay well inside the bounds: source paths are ≤ 120 chars and depth ≤ 8, plus 26 chars and 2 segments, against the runner's `safe_relative` limit of 400 chars.

Consequence: relative imports survive without rewriting. Only one generated import per scene is needed.

### A6. Per-scene error boundary

Scene t throws at local frame 5.
- **No boundary** (`MASTER-THROW-RAW`): `renderMedia` **fails the whole render** with `scene t exploded at local frame 5`, after rendering a 0..9 and t 0..4. No partial MP4 is produced.
- **A React error boundary per `<Series.Sequence>`** (`MASTER-THROW-BOUNDARY`): the render **succeeds**. It shows the fallback for t (`frames/throw-boundary-f0015.png`), and scene b still starts on time, with audio at 1.000 s (silencedetect). Remotion logs a console error but does not fail the render.

Consequence and recommendation:
- **Studio:** use a boundary per scene, with a visible fallback that names the scene. This answers the "per-scene failure isolation" precondition of `docs/presentation-studio.md:2394-2403`.
- **Export:** an MP4 must not silently contain a fallback card presented as the user's video. The boundary in render mode should call `cancelRender(error)` (exported by `remotion`) with a typed, scene-naming message, so the job fails as `presentation_render_failed` and names the scene. Slice 02 picks one of two options. Studio was not launched here; the boundary mechanism is plain React and identical in Studio.
  - Option 1, recommended: the fallback card in Studio, a typed failure in render.
  - Option 2: the fallback in both.

### A7. Import guard with N merged sources

How the guard works (code):
- The compile-time allow-list and the "no escape" rule live in `runtime-host.mjs` `virtualPlugin` (L61-88). Its module map is keyed by **one scene's own source paths**. It runs in the Player compile, and in `RemotionBuildGate` before every source-edit publish (`presentation_studio_reload.py:493`).
- The Python `isolation_guard` (`remotion_isolation.py:215`) runs on every `parse_source` of one source. That includes the render plan's revalidation (`presentation_render_plan.py:91-95`).
- `refused_imports` guards a Studio publish (`remotion_studio_workspace.py:166`).
- **No guard sits in the webpack bundle used by Studio or render.** Proof: a master scene importing a sibling scene's module (`../y/palette`) and a bare package outside the list (`@remotion/media-parser`, present in the shared `node_modules`) **bundles without error** (`generated/guardprobe-scene-x.tsx`, `bundle_only.cjs`).

Consequence:
- Guards stay per source and keep holding, provided the master planner works only from parsed, guarded per-scene sources: each pin's `RemotionSource` from the store or the frozen package, revalidated.
- The webpack bundle of a master is no weaker than today's scene Studio and render, which use the same bundler.
- For defence in depth, Slice 03/04 should still re-check each scene's specifiers when planning: relative specifiers resolve inside that scene's module set, and bare ones are in `SCENE_ALLOWED_IMPORTS`, via `remotion_import.specifiers`. A cross-scene import then cannot appear even from an old version that predates the build gate. The typed reason would be `master_source_import_refused`.

---

## B. Frozen snapshot sufficiency (code)

Contents: the `jarvis.presentation-snapshot/1` package (`presentation_snapshot_package.py`, `presentation_snapshot_packager.py:296-336`) holds:
- `presentation/{presentation,variant,art_direction,score}.json`, i.e. the ordered `scenes` with exact `prefab` pins, `props` and `data`;
- per pin: `src/**`, `public/**`, `source.json` (block: composition, entry, engine version and lock), `props_defaults`, `data_defaults`, `source_digest` and engine;
- the frozen live copies `prefabs/<id>/<v>/live/*`;
- the manifest `scenes` order and per-file SHA-256, verified by `read_package`.

`remotion_pins` and `render_props` (`presentation_render_plan.py:27-81`) already give, per scene: the block, the digest and the merged props/data. **Everything a master render needs is there; no new persistence.** A master plan is a pure function of (package or live variant + pinned sources).

Note: the package holds `held_pins()` (`packager:298`), which can include more than the active `scene.prefab`. The master must mount only the active pin of each scene, in `variant.json` order.

Limits:
- package: 600 files and 64 MiB (`presentation_snapshot_package.py:31-32`);
- Studio workspace: 400 files and 64 MiB (`remotion_studio_runner.py:65-66`);
- per source: 64 modules (1 MiB) and 64 assets (4 MiB each, 16 MiB in total) (`remotion_source.py:46-51`).

What a realistic 5-10 scene deck with media needs:
- about 5-10 modules per scene, giving 50-100 modules plus about 1-3 assets per scene;
- images of 0.1-1 MiB;
- narration or music. 30 s of AAC/MP3 is 0.5-1 MiB. A 48 kHz stereo WAV is about 5.6 MiB per 30 s and already exceeds the 4 MiB per-asset cap.

That totals 10-60 MiB and well under 400 files: it fits, but the byte budget is the binding one for media-heavy decks. De-duplicating identical assets only lowers the totals. A master workspace equals the union of its sources plus a few KB of generated files, so it is never larger than the snapshot's sources.

Consequence: the master bound is the minimum of the Studio and render bounds: **400 files and 64 MiB** for the workspace. Over that, refuse with `master_project_too_large` and keep the scene lane. Never relax a per-source cap.

---

## C. Studio lifecycle seam (code)

Identity today: `StudioState.pin` (`remotion_studio.py:213-251`). Its uses:
- `_start_locked` decides whether to keep the workspace: `state.pin == pin` (`remotion_studio_service.py:296`);
- `open` decides between reuse and hot sync (L250);
- `_refuse_unpublished` names the base;
- `_announce_scene` notifies listeners, which `v2_app.py:543` uses to end agent authoring permissions per prefab;
- `restart` reopens the pin;
- `publish` rebases (`_rebase_locked`);
- `public_view` exposes `pin` and `work_copy.base`.

The provider seam is `SourceProvider = (StudioPin) -> (RemotionSource, props)` (L36-37), wrapped by `_prepare` → `plan_workspace` (L225-234).

Safest target union: a frozen `StudioTarget` with `kind` and one of two shapes:
- `scene(pin)`;
- `variant_master(presentation_id, variant_id, variant_revision, project_key, scenes: ((scene_id, pin), …))`.

What changes:
- `_prepare(target)` dispatches to `plan_workspace` or to the master planner.
- Every `state.pin == pin` becomes `state.target == target`. For `variant_master`, equality is `project_key`, so an edit that changes the key is a different target and goes through `sync`.
- `parse_open` gains a master body. Keep the old body `{prefab_id, version, acknowledge_unsandboxed_scene}` exactly as is.
- Scene listeners get one call per mounted pin.

What stays: the runner, process guard, port, idle and egress rules are untouched. P4 holds and no second process is needed. The workspace shape (`src/`, `public/` + generated top-level files) already admits `src/master/**` and `src/scenes/<id>/**` (Readiness item 8).

Generated files: `GENERATED_FILES = (studio-root.tsx, package.json)` (`remotion_studio_runner.py:58`) is a top-level list. The runner makes those files read-only (L341) and never lists them as edits. `src/master/**` sits under `src/` and **would count as editable source**. Slice 04/05 must make "generated" path-based (`studio-root.tsx`, `package.json`, `src/master/**`) for a master target. Otherwise every regeneration reads as a user edit.

`state.json` (a runtime JSON file, not SQLite, so no SQLite migration):
- `from_payload` refuses any `schema != 1` (L260). `_load` (`service:110-127`) turns that into `failed/state_unreadable` and refuses `open` until the file is set aside. It never guesses.
- Recommendation:
  - Keep writing `schema: 1`, byte-compatible, for scene targets.
  - Write `schema: 2` (with `target`) **only** for a `variant_master` target.
  - The new reader accepts 1 (`pin` becomes `target=scene`) and 2.
- Effect on a rollback to an old Core while a master Studio is recorded: it fails closed as `state_unreadable` and the user moves the file aside. That is the existing, documented behaviour. It is never a wrong scene, and no data is lost. Record this in the Slice 09 rollback notes.
- The alternative, an extra `target` key under schema 1, is silently ignored by an old Core, which would then show a master Studio as a scene-less READY state. It is rejected as less explicit.

Acknowledgment:
- Today `acknowledge_unsandboxed_scene: true` is required per pin by `open`, `restart` and a `sync` to another pin.
- A master runs N scene sources unsandboxed in one Studio page and one origin.
- Recommendation: a master body `{presentation_id, variant_id, project_key, acknowledge_unsandboxed_project: true}`. The dialog names the scene count. The ack binds to that `project_key`, so a new key needs a new ack on `sync` or `restart`, as for a different pin today.
- Keep the scene ack field unchanged for scene targets.

Unpublished edits on a master workspace:
- Detection already exists (`runner.modified_work` against `work.files.json`). Classify edits as:
  1. generated paths: refuse to sync or switch without `discard_unpublished`;
  2. `src/scenes/<id>/**` or a `public/**` file owned by exactly one scene: "edits on scene <id>";
  3. shared or ambiguous `public/**` paths.
- In every case: never overwrite silently, and set aside with `discard_unpublished` as today (`studio-edits`).
- Write gate (`presentation_studio_reload.py:304-325`): it compares the workspace base pin to the scene's prefab. For a master target it should refuse a `brain` edit of scene X only when class 2 edits on X exist (or the listing is unreadable). Edits to generated files must not block voice edits; they are refused and set aside at the next sync instead. Otherwise an unpublishable master edit would block D5 forever.

Publish:
- `publish` uses `PublishRequest(presentation_id, variant_id, scene_id, base pin, digest, confirm)`.
- **For A+B it must refuse any master target with a typed code**, `remotion_studio_publish_master_unsupported` or reason `master_publish_not_supported`, before reading the workspace.
- The scene round trip stays as is.

---

## D. Old-caller compatibility map

| Caller | Today | Must keep |
| --- | --- | --- |
| `presentation_render.scene_target` (L291-314) via `presentation_render_plan.choose_scene` (L49-51) | `scene_id` absent and exactly 1 Remotion scene: that scene. Several scenes: `presentation_render_unknown_scene` (404) listing the ids. | Unchanged, byte for byte. The master scope is a **separate** entry (`choose_master`/`plan_master_files`). |
| `plan_workspace` (`remotion_studio.py:184`) | Used by the Studio (`service:234`) and the render (`render_plan:100`). Its root and `package.json` are pinned by tests. | Unchanged. The master gets its own planner. |
| `plan_files` | `render_service:338` (preview), `:553` (export) | Unchanged for the scene scope. |
| `RenderService.submit` (L236) / `export` (L218); route `POST /v1/local-capabilities/remotion/render/jobs` (`presentation_render_routes.py:136-163`) | `{snapshot_id, format, settings?}` or `{presentation_id, variant_id, expected_*_revision, authorised_boards?, format, settings?}` | A body without the new scope keeps the exact current meaning. P3: an explicit settings key opts into the master. |
| Board Artifacts export (`control_center_workspace.js:773`) | Posts `{snapshot_id, format}` with no settings. On a multi-scene snapshot this **fails today** with `unknown_scene`. | The route must not change meaning. Slice 08 decides whether this UI sends the master scope explicitly when the snapshot is master-ready. |
| MCP `remotion_export` (`remotion_mcp.py:164-176`, `remotion_mcp_tools.py:225-267`); `EXPORT_SETTINGS`/`ExportSettings` (`scene_id`, `frame_start`, `frame_end`, `frame`, `scale`, `crf`) | Freezes, then submits. A multi-scene variant without `scene_id` fails with `unknown_scene`. | `scene_id` keeps meaning one scene. Adding the scope (one field) touches the MCP budget pins in `test_mcp_catalog.py` (remotion 5 400 B). |
| MCP `remotion_studio` (`remotion_mcp_tools.py:195-221`) | Pointer only; never opens. Points at the Variants card or a scene card. | Same rule, never opening. The master entry wording changes in Slice 07/08. |
| Studio `open` route (`remotion_studio_routes.py`), Variants door (`explorer_remotion.js:444` posts `{prefab_id, version}`), rail | Scene pin | The scene body and semantics are unchanged (compatibility entry). The master body is new. |
| Preview `POST …/render/preview` (`routes:165-180`) | Per scene (author's look) | Unchanged (scene-scoped by design). |

Render bound:
- `MAX_RENDER_FRAMES = 3600` (`presentation_render.py:35`) caps a range or MP4 at 2 min @ 30 fps. Timeout: `300 + 1 s/frame`, capped at 3600 s (L41-43). Disk: job folder 2 GiB, output 512 MiB.
- A 5-10 scene deck of 8-20 s per scene is 40-200 s, i.e. 1 200-6 000 frames @ 30 fps. **That exceeds 3600 often.**

Measured on this host with the real guarded host, concurrency 1 (the Jarvis default), `results/real-host-renders.json`:

| Composition | Frames / duration | Total time |
| --- | --- | --- |
| 1080p30 | 150 frames (5 s) | 16.3 s |
| 1080p30 | 600 frames (20 s) | 42.7 s |
| 640x360 | 180 frames, with `OffthreadVideo` | 15.2 s |

That gives about **7.5 s fixed cost** (bundling, which alone took 5.3 s, plus the browser) and about **0.059 s/frame ≈ 1.8 s per second of 1080p30 video** for simple scenes. Real scenes with images, gradients and video decoding are plausibly 3-5x heavier, i.e. 0.2-0.3 s/frame.

| Master length | Frames @ 30 fps | Simple | Heavy |
| --- | --- | --- | --- |
| 5 min | 9 000 | about 9 min | about 30-45 min |
| 10 min | 18 000 | about 18 min | about 60-90 min |

Recommendation: a separate `MAX_MASTER_RENDER_FRAMES = 9000` (5 min @ 30 fps, 2.5 min @ 60 fps) and keep the timeout cap at 3600 s. The scene bound stays 3600. Raising the master bound to 18 000 requires raising the timeout cap to about 2 h. That is agent 0's decision.

---

## E. Declared video specs census

Fixtures and tests (`results/census.json`, 27 literal declarations, plus the parametric decks):

| Source | Spec |
| --- | --- |
| Most fixtures and tests | **1280x720@30** (18), incl. `tests/fakes/remotion_scene.py`, `presentation_studio_fake_author.py` and both `presentation_studio_task_base_a8377529` manifests |
| Tests | **1920x1080@30** (4) |
| `test_remotion_import.py`, `test_presentation_studio_composition_clock_routes.py` | 1280x720@24, 800x600@24, 800x600@25 (one each) |
| Gate deck `tests/unit/presentation_playback_gate_world.py` `DECK` | 1280x720 at **30/30/30/25/60/30/24/30/30 fps**: mixed fps |
| Media deck `tests/unit/variants_media_world.py` `MEDIA_DECK` | 1920x1080, 1024x768, 720x1280, 800x800, all @30: mixed dimensions |

The gate deck becomes `master_fps_mismatch` and the media deck `master_dimensions_mismatch`. Both are the natural negative fixtures, and their legacy lanes must stay green.

Authoring defaults:
- `presentation_studio_authoring_remotion.py:50`: `DEFAULT_COMPOSITION = 1280x720@30, 150 frames`.
- Structured slide generator, guide `:114`/`:133`: 1280x720@30, 300 frames.
- **Native example**, guide `:226`: **1920x1080@30**.

Two authoring paths therefore produce two specs. A variant mixing a native scene with a structured or default one is master-incompatible today.

Consequence: Slice 07 must give every new presentation one spec, used for every scene it authors. For example, take the first scene's spec, or one presentation-level constant. Slice 02 records the spec rule.

---

## F. Old-path regression surface

These tests must stay green and are likely to be touched. In `tests/unit/` unless noted:

- **Render:** `test_presentation_render_domain.py` (L244 pins `{studio-root.tsx, package.json}`), `_service.py` (L96-101 pins the root), `_runner.py`, `_routes.py`, `_relay.py`, `_docs.py`, `_real.py` (opt-in real), `test_variants_media_export.py` (opt-in real audio).
- **Studio:**
  - `test_remotion_studio.py` (L77 `jarvis-studio-scene`), `_data.py`, `_routes.py`, `_runner.py`, `_shape.py`, `_shape_real.py`, `_guard.py`, `_rework.py`;
  - `_publish.py`, `_publish_routes.py`, `_publish_crash.py`, `_publish_docs.py`, `_real.py`, `_roundtrip_real_browser.py`, `_docs.py`;
  - `test_control_center_remotion_studio.py`, `test_variants_remotion_studio_{js,browser,publish_js,docs}.py`.
- **Source and edit:** `test_remotion_source*.py`, `test_remotion_source_edit_*`, `test_presentation_studio_reload_*` (one file per process), `test_remotion_isolation*.py`, `test_remotion_compiler*.py`.
- **Clock and playback:** `test_composition_clock.py`, `_conformance_js.py`, `test_presentation_studio_composition_clock_routes.py`, `test_continuous_sequencing_*`, `test_variants_transport_*`, `test_presentation_playback_release_gate_browser.py`.
- **Authoring:** `test_presentation_studio_native_authoring.py`, `_native_loop.py`, `test_presentation_studio_authoring_docs.py`.
- **MCP:** `test_mcp_catalog.py` (budgets), `test_remotion_mcp_{tools,server,docs,ownership}.py`, `test_presentation_studio_mcp_docs.py`.
- **Docs pins:** `test_presentation_experience_contract_docs.py:107` ("Rejected for now: a generated multi-scene root"), `test_presentation_render_docs.py`, `test_remotion_studio_docs.py`, `test_presentation_studio_docs.py`, `test_presentation_artifacts_docs.py`.
- **Release gates:** `test_remotion_release_{gate,flows,faults,docs}.py`, `test_presentation_studio_release_{gate,flows,faults,docs}.py`, `test_workspace_presentations_{js,browser}.py` (Board export).

---

## Other findings

- **The handoff's composition id `JARVIS_PRESENTATION` is invalid.** Remotion 4.0.534 refuses it: "Composition id can only contain a-z, A-Z, 0-9, CJK characters and -". Jarvis `COMPOSITION_ID` (`remotion_source.py:63`) agrees, but `remotion_studio._IDENT_SAFE` (L48) would accept the underscore. Use for example `JarvisPresentation`.
- **Remotion refuses duplicate composition ids** ("Multiple composition with id … are registered", `CompositionManagerProvider.js:47`). Almost every scene declares `id: "Scene"`, so optional per-scene debug compositions need generated unique ids.
- **Engine pins are per source** (`source.json` engine version and lock). Render requires installed = frozen (`render_service:257-261`). A master needs every scene on the same engine version and lock, else `master_engine_mismatch`.
- **Studio playback smoothness:** `Series` does not premount by default, so media loads at the boundary. Consider `premountFor` in the generated master for Studio. It has no effect on render correctness.

## No conflict with D1-D10

No fundamental conflict was found. No schema migration is needed: there is no SQLite change, and `state.json` gets an additive schema 2, written only for master targets.

---

## Recommended contract inputs for Slice 02

1. **P1 confirmed.** The master is ready iff every active scene declares the same `width`, `height` and `fps`. The master composition takes that spec.
   - Duration: the sum of the declared `duration_in_frames`, zero overlap.
   - Each scene: `Series.Sequence durationInFrames = declared`, local frame 0 at each boundary.
   - No fps or size mapping, and no `<Sequence width/height>` trick.
2. **P2 confirmed and refined.**
   - Merge `public/**` and `public/live/**` by case-folded exact path.
   - Identical bytes: de-duplicate. Different bytes, or the same folded path with different spelling: typed collision with the path and scene ids.
   - Never rewrite `staticFile`. Authoring (Slice 07) creates collision-free names.
3. **P3 confirmed.** Add a settings key `scope: "scene" | "master"` (absent means today's semantics; `scene_id` with `scope: "master"` is invalid).
   - Its own bound `MAX_MASTER_RENDER_FRAMES = 9000` (agent 0 may choose 18 000 with a larger timeout cap). Timeout formula unchanged, cap 3600 s.
   - Artifact metadata records `render_scope` and the `project_key`.
   - The scene scope and every old body stay byte-compatible.
4. **P4 confirmed.**
   - One process. `StudioTarget = scene(pin) | variant_master(presentation_id, variant_id, variant_revision, project_key, scenes)`.
   - Master ack `acknowledge_unsandboxed_project: true`, bound to `project_key`, naming the scene count.
   - `state.json`: schema 1 for scene, schema 2 only for master; the reader accepts both.
   - Generated set is path-based (`studio-root.tsx`, `package.json`, `src/master/**`), read-only.
5. **P5 confirmed.**
   - Master publish is refused (typed).
   - Unpublished master edits are classified generated / per-scene / shared. They are never overwritten, and set aside only with `discard_unpublished`.
   - The write gate blocks agent edits on scene X only for per-scene edits on X.
6. **Error isolation.** One boundary per scene. Studio shows a named fallback. Render ends with `cancelRender` and a typed, scene-naming failure (Option 1), not a silent fallback frame.
7. **Master bounds.** Workspace ≤ 400 files and ≤ 64 MiB (the min of Studio and package). Duration ≤ `MAX_MASTER_RENDER_FRAMES` for export. Per-source caps unchanged.
8. **Composition id** `JarvisPresentation`. Debug scene compositions, if any, use generated unique ids.
9. **Reason codes** (typed, not corruption):
   - `master_engine_not_remotion` (presentation engine or a non-Remotion pin)
   - `master_empty`
   - `master_source_unavailable` (missing or tampered pin, digest mismatch)
   - `master_engine_mismatch`
   - `master_fps_mismatch`
   - `master_dimensions_mismatch`
   - `master_public_asset_collision`
   - `master_source_import_refused` (defensive specifier re-check)
   - `master_project_too_large`
   - `master_too_long`
   - optional `master_input_props_reader` (a scene calls `getInputProps`; zero today)
   - outside the planner: `remotion_studio_publish_master_unsupported`
10. **Persistence.** None. The plan derives from the live variant + store, or from the frozen package, for render.
