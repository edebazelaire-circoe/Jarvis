# Remotion master project of a Presentation Variant: plan, readiness, Studio target, whole-video export

Status: **Level 3 — implemented by Slices 03-08 of handoff jarvis-remotion-master-project-studio-export, released by its Slice 09.** Shipped:
§ 2, § 3 and § 5, the pure planner (Level 3 (Slice 03), `jarvis/domain/remotion_master_project.py`); § 6 and § 7, the workspace files and
the generated composition (Level 3 (Slice 04), `jarvis/domain/remotion_master_files.py`); § 9 and § 11, the Studio master target and the
live readiness read (Level 3 (Slice 05), `jarvis/core/remotion_studio_service.py`); § 10, the whole-video render scope (Level 3
(Slice 06), `jarvis/domain/presentation_render_master.py`); § 12, voice and agent (Level 3 (Slice 07), `jarvis/domain/remotion_master_sentences.py`,
`jarvis/runtime/remotion_mcp_tools.py`); § 13, the Variants and Board entrypoints (Level 3 (Slice 08),
`jarvis/runtime/control_center_presentation_studio_explorer_remotion.js`, `jarvis/runtime/control_center_presentation_studio_explorer_export.js`,
`jarvis/runtime/control_center_workspace.js`). § 4 (spec and timeline) and § 8 (security review) are implemented through those sections;
§ 14 is the compatibility table and § 15 the non-goals (master publish-back and the master Player stay Level 1, deferred, never partially
implemented). Release proof (Slice 09, real Core + Control Center + `remotion studio` + render host, real Chrome):
`tests/unit/test_remotion_master_release_real.py` (opt-in), evidence in the handoff's `slices/09-release-and-human-acceptance/`;
operations, set-aside location and rollback: [OPERATIONS.md](OPERATIONS.md) › *Studio Remotion optionnel*. Evidence for the choices: the handoff's Slice 01 audit (`tasks/jarvis-remotion-master-project-studio-export/slices/01-current-state-and-compatibility-audit/AUDIT.md`,
real runs on the pinned Remotion 4.0.534). Decisions marked *decided by agent 0* were taken by the handoff's orchestrator under the Human's
delegated autonomy (2026-10-13).

Neighbouring contracts, all still true for the scene lane: [remotion-source.md](remotion-source.md) (one scene source),
[remotion-studio.md](remotion-studio.md) (the managed `remotion studio` process, scene target), [remotion-render.md](remotion-render.md) (guarded
render of a frozen snapshot, scene scope), [presentation-studio.md](presentation-studio.md) (Presentation, Variant, scene pins, the Variants
composition clock and its security review), [remotion-isolation.md](remotion-isolation.md) (guards and sandbox).

## 0. Terms

| Term | Meaning |
| --- | --- |
| **master Remotion project** | A deterministic, derived projection of ONE Presentation Variant into one normal Remotion project: the exact pinned source of every scene, a merged `public/`, and generated orchestration files. Never a source of truth. |
| **master Remotion Composition** | The generated full-video `<Composition id="JarvisPresentation">` of that project: every scene of the variant end to end in one native Remotion timeline (`<Series>`). |
| **Variants composition clock** | The existing Jarvis interval map over per-scene sandboxed Players ([presentation-studio.md](presentation-studio.md) › *Composition clock (Level 3)*). It is **compatibility playback**, not a Remotion Composition; its "master fps" is the clock's timebase. It is unchanged by this contract. |
| **MasterProjectPlan** | The pure planner's output (§ 2): the single source of truth for readiness, files, key and timeline, shared by Studio, render, UI and agent. |
| **scene lane** | Everything that exists today: one scene per Studio workspace, one scene per export, the Variants Players. It stays supported and byte-compatible. |

Never write "master composition" for the Variants composition clock, and never write "the video composition" for the master Remotion
Composition without the word *master*.

## 1. Decisions

| # | Decision | Source |
| --- | --- | --- |
| M1 | **Common spec only (P1).** A master is ready only when every active scene declares the same `width`, `height` and `fps`. No fps mapping, no size mapping, no `<Sequence width/height>` trick, no source rewriting. | AUDIT A2; decided by agent 0 |
| M2 | **Zero overlap.** Master duration = sum of the declared `duration_in_frames`; each scene sits in `<Series.Sequence durationInFrames={declared}>` and starts at its local frame 0. Score targets never shorten or lengthen a scene. | AUDIT A1; decided by agent 0 |
| M3 | **Public assets merged by case-folded exact path (P2)**, `public/**` and render-only `public/live/**`: identical bytes are de-duplicated; different bytes, or one folded path spelled two ways, are a typed collision. `staticFile()` strings are never rewritten. | AUDIT A4; decided by agent 0 |
| M4 | **Additive render scope (P3):** settings key `scope: "scene" \| "master"`; absent = today's semantics byte for byte; `scene_id` with `scope: "master"` is invalid. | decided by agent 0 |
| M5 | **One Studio process, two target kinds (P4):** `StudioTarget = scene(pin) \| variant_master(...)`; master acknowledgment `acknowledge_unsandboxed_project` bound to `project_key` and naming the scene count; `state.json` schema 1 for a scene target, schema 2 only for a master target, the reader accepts both. | AUDIT C; decided by agent 0 |
| M6 | **No master publish-back (P5):** master publish is refused `remotion_studio_publish_master_unsupported`; unpublished master edits are classified (generated / per-scene / shared), never overwritten, set aside only with `discard_unpublished`; the agent write gate blocks scene X only for per-scene edits on X. | AUDIT C; decided by agent 0 |
| M7 | **One error boundary per scene.** Studio shows a fallback card naming the scene; a render calls `cancelRender` and the job fails with a typed error naming the scene. No fallback card ever ends up in an MP4. | AUDIT A6 Option 1; decided by agent 0 |
| M8 | **Bounds:** master workspace ≤ 400 files and ≤ 64 MiB; `MAX_MASTER_RENDER_FRAMES = 9000`; render timeout formula and its 3600 s cap unchanged; the scene bound `MAX_RENDER_FRAMES = 3600` unchanged; per-source caps unchanged. | AUDIT B, D; decided by agent 0 |
| M9 | **Composition id `JarvisPresentation`.** `JARVIS_PRESENTATION` (the handoff's draft) is refused by Remotion 4.0.534 and is never used. | AUDIT, other findings |
| M10 | **`project_key` inputs** (§ 5): generator version, master spec, ordered scene pins with source digest and instance props+data digest, public-asset merge plan. Titles and the variant revision are not inputs. | decided by agent 0 |
| M11 | **Spec of new decks:** a scene added to a variant takes the variant's shared spec; a brand-new native deck defaults to 1920x1080 @ 30 fps. Structured and guided defaults are not changed by this handoff. | decided by agent 0 |
| M12 | **No persistence change.** No SQLite migration, no new field in a Presentation or Variant document: the plan derives from the live variant + prefab store (Studio, UI, agent) or from the frozen snapshot package (render). | AUDIT B; decided by agent 0 |
| M13 | **Board Artifacts export** requests `scope: "master"` when the snapshot is master-ready, otherwise posts today's body unchanged (Slice 08). | decided by agent 0 |

## 2. MasterProjectPlan — Level 3 (Slice 03)

One pure function family (Slice 03, `jarvis/domain/`; no disk, no process, no clock) builds the plan from either input:

- **live**: the current `PresentationVariant` (ordered `scenes`, `revision`), its `Presentation.engine`, and each active pin's `RemotionSource`
  read through `PrefabService.remotion_source` (guards and SHA-256 checks of today included);
- **frozen**: a `jarvis.presentation-snapshot/1` package (`presentation/variant.json` order, per pin `src/**`, `public/**`, `source.json`,
  `props_defaults`, `data_defaults`, `source_digest`, frozen live copies). Only the **active** pin of each scene is mounted, in `variant.json`
  order, even when the package holds more pins (`held_pins`).

Plan fields (the wire view adds nothing else; it never contains a path of the machine):

```text
MasterProjectPlan
  presentation_id, variant_id
  variant_revision            the basis the plan was computed from (carried alongside, NOT a key input)
  generator_version           MASTER_GENERATOR_VERSION (integer, starts at 1)
  status                      "ready" | "incompatible"
  reason, detail, scene_ids   only when incompatible (§ 3); detail is bounded English, no path
  project_key                 "mpk_" + 24 hex (§ 5); present when ready
  composition                 {id: "JarvisPresentation", width, height, fps, duration_in_frames}
  scenes[]                    {scene_id, prefab_id, version, source_digest, engine_version, from_frame, duration_in_frames,
                               entry, mount: "src/scenes/<scene_id>/"}
  public_assets[]             {path, sha256, bytes, scene_ids[]}  (sorted by path; one row per merged file)
  totals                      {files, bytes}  (whole workspace, generated files included)
```

A plan is a value: the same inputs give the same plan, the same files and the same key, on every machine.

**Implementation (Level 3, Slice 03).** `jarvis/domain/remotion_master_project.py`: `live_inputs(presentation, variant, pins)` and
`frozen_inputs(package)` build one `MasterInputs`; `plan_master(inputs) -> MasterProjectPlan`; `MasterProjectPlan.to_wire()` is the view
above. `jarvis/core/remotion_master_project.py` `MasterProjectReader.live_plan(presentation_id, variant_id)` is the live read seam (variant
from `PresentationStudioService`, each active pin through `PrefabService.manifest` + `remotion_source`, the props/data defaults exactly as
the snapshot packager freezes them; it emits `core.remotion_master.planned` at info). Facts the implementation fixes:

- `scenes[].entry` is the workspace-relative mounted entry (`src/scenes/<scene_id>/Scene.tsx`); `mount` is its folder.
- The wire view of an incompatible plan carries `reason`, `detail`, `scene_ids` and no `project_key`, `composition`, `scenes`,
  `public_assets` or `totals`; a ready plan carries those and no reason.
- `public_assets[]` of a frozen plan also lists the `public/live/**` copies (render workspace); they count in the collision check and in
  `totals`, never in the key (§ 5).
- `totals` counts the scene modules, the merged `public/**` and the generated set, whose bytes come from
  `jarvis/domain/remotion_master_generated.py` `generated_files(...)` (the function Slice 04 writes to disk); the plan keeps those bytes
  (`plan.generated`) and, per scene, the parsed source and merged props, never on the wire.
- A pin unreadable in the store (`PrefabStoreError`) is `master_source_unavailable` with the store's code in `detail`; an HTML pin is
  `master_engine_not_remotion`. A frozen pin is revalidated with `parse_source` and its recomputed digest compared with the manifest's
  `source_digest`. A package whose `presentation.json` / `variant.json` cannot be read is `presentation_render_snapshot_invalid`
  (corruption, not incompatibility).
- The import re-check (`master_source_import_refused`) resolves each relative specifier against the scene **as mounted** under
  `src/scenes/<scene_id>/` (`../src/lib/x` from `src/Scene.tsx` resolves standalone, not once mounted: refused) and refuses what the isolation
  guard's `LOADER_RULES` refuse (`loader_finding`, over the raw text): any dynamic `import(...)` whatever the quoting or spacing, `require` in
  any form (call, bare reference, alias, `require.context`), `.context(`, `import.meta`, `module.hot`, `__webpack_*`, and every ASCII
  `\uXXXX` / `\u{…}` escape (`\u0072equire` IS `require` to webpack: QA S04 B1 proved a file outside the workspace bundled through it). The generated composition imports each entry by its exact
  file, extension included, and hands each scene its props as `JSON.parse("<json>")`, so every key (`__proto__` included) is an own property,
  as in the scene lane's JSON input props.
- The planner also runs the workspace path-set check (`path_set_problems`) over the merged `public/` paths, frozen live copies included
  (`master_public_asset_collision`): a pinned `public/live/a.png` beside a frozen copy `a.png/b.json` is refused at planning, so a ready plan
  never fails in `plan_master_files`.
- The `getInputProps` check (`master_input_props_reader`, comments stripped) and the loader check are **textual**: defence in depth,
  not a guarantee. A computed name (`remotion["get" + "InputProps"]`) escapes them; the per-source isolation guard is the boundary.
- Conformance: `tests/unit/test_remotion_master_project.py`.

## 3. Readiness and reason codes — Level 3 (Slice 03)

The planner checks in this fixed order and reports the **first** failing check as `reason` (with `detail` and the involved `scene_ids`;
`MasterReason` declares the codes in this order; `detail` names scenes as « scene n (pss_…) », at most 300 characters, never a machine path). An
incompatible master is **not** a corruption: the variant keeps opening, playing, exporting scene by scene and opening a scene in Remotion
Studio exactly as today. Nothing is rewritten to make a variant ready.

| Order | `reason` | When | Sentence shown to the user (Slice 08 / agent) |
| --- | --- | --- | --- |
| 1 | `master_empty` | the variant has no scene | « La variante n’a aucune scène : pas de vidéo entière à construire. » |
| 2 | `master_engine_not_remotion` | `Presentation.engine` is not Remotion, or an active pin has no Remotion `source` block | « Une scène n’est pas une scène Remotion : la vidéo entière n’est pas disponible. » |
| 3 | `master_source_unavailable` | an active pin is unknown, unreadable, tampered or its digest does not match | « La source d’une scène est introuvable ou altérée (scène n) : la vidéo entière n’est pas disponible. » |
| 4 | `master_engine_mismatch` | the pins do not share one engine version and lock | « Les scènes n’ont pas toutes été écrites pour la même version de Remotion. » |
| 5 | `master_fps_mismatch` | the scenes declare different `fps` | « Les scènes n’ont pas toutes la même cadence (images par seconde) : la vidéo entière n’est pas disponible ; chaque scène reste lisible. » |
| 6 | `master_dimensions_mismatch` | the scenes declare different `width` or `height` | « Les scènes n’ont pas toutes la même taille d’image : la vidéo entière n’est pas disponible ; chaque scène reste lisible. » |
| 7 | `master_source_import_refused` | the defensive per-scene re-check (§ 8 a) finds a bare specifier outside `SCENE_ALLOWED_IMPORTS` or a relative import resolving outside the scene's own module set | « Une scène importe un module qui n’est pas le sien : la vidéo entière n’est pas disponible. » |
| 8 | `master_input_props_reader` | a scene module contains `getInputProps` (it would read the master's input props, not its own; zero uses today) | « Une scène lit les paramètres d’entrée de la vidéo : elle ne peut pas être assemblée. » |
| 9 | `master_public_asset_collision` | two scenes bring different bytes at one case-folded `public/` path, or one merged path is a file another uses as a folder (detail names the path and the scene ids) | « Deux scènes utilisent le même nom de fichier « x » pour des contenus différents. » |
| 10 | `master_project_too_large` | workspace > 400 files or > 64 MiB, generated files included | « Le projet de la vidéo entière dépasse 400 fichiers ou 64 Mio. » |
| 11 | `master_too_long` | master `duration_in_frames` > `MAX_MASTER_RENDER_FRAMES` (9000) | « La vidéo entière dépasse 9 000 images (5 min à 30 i/s). » |

Codes outside the planner (HTTP envelopes and job failures; each is new, unique, and does not collide with a scene-lane code):

| Code | HTTP | Where | When |
| --- | --- | --- | --- |
| `remotion_studio_master_incompatible` | 409 | Studio `open` / `sync` / `restart` of a master target | the current plan is `incompatible`; the envelope carries `reason`, `detail`, `scene_ids`; nothing starts |
| `remotion_studio_master_stale` | 409 | Studio master `open` / `sync` / `restart` | the body's `project_key` differs from the current plan's (the variant changed since the dialog); the envelope carries the current `project_key`, `variant_revision` and scene count; nothing starts, the page re-asks the confirmation |
| `remotion_studio_publish_master_unsupported` | 409 | Studio `publish` while the target is a master | always, before the workspace is read |
| `presentation_render_master_incompatible` | 409 | render `jobs` with `scope: "master"` | the plan of the frozen package is `incompatible`; the envelope carries `reason`, `detail`, `scene_ids`; no job, no derivative |
| `presentation_render_master_scene_failed` | job failure (not HTTP) | master render job | a scene threw during the render (§ 10); `error_detail` names the scene id and its 1-based position |

The existing `remotion_studio_ack_required` (400) is reused for a master body without `acknowledge_unsandboxed_project: true`; the existing
`presentation_render_invalid` (400) for an invalid scope combination; the existing `presentation_studio_stale_revision` for a render body whose
expected revision is stale (the frozen package fixes the key, § 5).

## 4. Master video spec and timeline

- **Spec**: the `(width, height, fps)` shared by every active scene (M1). The master composition takes it as is.
- **Duration**: `duration_in_frames = Σ d_k`, `d_k` = the scene's declared `composition.duration_in_frames`.
- **Placement**: scene k starts at master frame `from_k = Σ_{j<k} d_j` and plays its local frames `0 .. d_k - 1`. Measured (AUDIT A1): inside the
  Sequence, `useCurrentFrame()` is local and `useVideoConfig()` returns the master width/height/fps and the Sequence's `durationInFrames`, i.e.
  exactly what the scene sees standalone under a common spec.
- **Media**: `<Audio>`, `<Video>`, `<OffthreadVideo>` from `staticFile()` keep their timing natively (AUDIT A3, offsets within 1 ms). A master
  never narrows what a valid scene may do (D8).
- **Residual difference, accepted**: `useVideoConfig().id` / `.props` / `.defaultProps` and `getInputProps()` belong to the master. Scenes get
  their props as React props of the mounted component; a reader of `getInputProps` is refused (`master_input_props_reader`).

## 5. `project_key` — Level 3 (Slice 03)

`project_key = "mpk_" + sha256(canonical_json(inputs))[:24]`, `canonical_json` = `json.dumps(..., sort_keys=True, separators=(",", ":"),
ensure_ascii=True)`, over exactly these inputs (decided by agent 0), written as the object
`{"generator_version": …, "spec": [w, h, fps], "scenes": [[…], …], "public_assets": [[path, sha256], …]}`:

1. `generator_version` (`MASTER_GENERATOR_VERSION`; bumped whenever the generated files change for the same inputs);
2. the master spec `[width, height, fps]`;
3. the ordered list, in variant order, of `[scene_id, prefab_id, version, source_digest, props_digest]`, where `props_digest` = SHA-256 of the
   canonical JSON of the scene's **instance** `{"props": …, "data": …}`;
4. the public-asset merge plan: the sorted list of `[path, sha256]` of the merged `public/**` of the pins (frozen `public/live/**` copies are
   not inputs: they are bound by the snapshot id, which is already the render's identity). The exclusion is by origin, not by path: a file
   that a pin's own source brings counts even under `public/live/`, so the live and the frozen plan of the same pins have the same key.

Not inputs: the Presentation title, the variant name, the variant `revision`, `presentation_id`, `variant_id`, scores, cues, art direction.
Consequences, each a planner test: a title rename or a no-op revision bump keeps the key; a repin (voice edit), a reorder, a new source version,
an instance props/data change, an added or removed scene changes it. The revision is carried beside the key as the **basis** of a plan, a
Studio target and a render.

## 6. Workspace layout, generated vs canonical files — Level 3 (Slice 04)

```text
work/
  package.json                 GENERATED  {"name": "jarvis-studio-master", "private": true, "version": "0.0.0"}
  studio-root.tsx              GENERATED  registerRoot + <Composition id="JarvisPresentation" .../>
  src/master/Presentation.tsx  GENERATED  the <Series> of § 7, one import per scene, each scene's merged props inline
  src/master/SceneBoundary.tsx GENERATED  the per-scene error boundary of § 7
  src/scenes/<scene_id>/**     the exact bytes of that scene's pinned src/** (relative imports unchanged, AUDIT A5)
  public/**                    the merged public/** of every pin (M3); render only: public/live/<name><ext> frozen copies
```

- **Generated set (path-based)**: `package.json`, `studio-root.tsx`, `src/master/**`. Read-only on disk, never listed as an edit, rewritten at
  every materialization. Everything else is a byte copy of a canonical pinned source and is **not** canonical in the workspace either: the
  canonical copy stays the immutable version in the prefab store.
- **Same plan for Studio and render**: one `plan_master_files` (Slice 04) produces both workspaces; the only difference is the render's
  frozen `public/live/**` copies. The scene lane's `plan_workspace` / `plan_files` and their pinned layout stay untouched.
- **Props**: each scene receives the same merge as `render_props` today: manifest defaults, then the scene's instance `props`; `data` (defaults
  then instance) under `props.data` when non-empty. Studio (live variant) does not resolve live Board references, as today's scene Studio; a
  render uses the snapshot's frozen copies.
- **Bounds**: the whole workspace ≤ 400 files and ≤ 64 MiB (the minimum of the Studio workspace bound `MAX_WORK_FILES` / `MAX_WORK_BYTES` and the
  snapshot package bound), else `master_project_too_large`; per-source caps of [remotion-source.md](remotion-source.md) are never relaxed.
- **Path safety**: `<scene_id>` is the scene id (`pss_…`); every planned path passes the runner's `safe_relative` rule; the top-level shape
  (`src/`, `public/`, generated files) is the one the Studio runner already admits (no shape widening).

**Implementation (Level 3, Slice 04).** `jarvis/domain/remotion_master_files.py` `plan_master_files(plan) -> {path: bytes}` (pure, sorted)
lays out a READY plan: the generated set, each scene's pinned `src/**` byte for byte under `src/scenes/<scene_id>/`, the merged `public/**`
(a frozen plan adds its `public/live/**` copies). There is no separate materialization adapter: the existing runners already take a file
map and write it, `RemotionStudioRunner.sync_work(files)` (atomic per-file rename under the Studio `work/`, Slice 05) and
`RemotionRenderRunner.prepare(job_id, files)` (the job's `work/`, Slice 06), each re-checking `safe_relative`. Before returning, the map is
checked again (`MasterFilesError`, a defence: a plan `plan_master` made ready never fails it): every path passes the snapshot package's
lexical rule (`package_path_problem`), a mount is `src/scenes/<scene id>/` with a real scene id, generated paths are only the generated set,
no path is written twice or collides by case or as file-and-folder (`path_set_problems`), the 400 files / 64 MiB bound holds, and the count
and bytes equal `plan.totals`. Marking `src/master/**` read-only in the Studio workspace is Slice 05 (today's `GENERATED_FILES` of the
runner names the two root files only). Tests: `tests/unit/test_remotion_master_files.py`; real proof below (§ 7).

## 7. Generated master composition — Level 3 (Slice 04)

- `studio-root.tsx` registers exactly one composition, `JarvisPresentation`, with the master spec and duration, `defaultProps={}`. Optional
  per-scene debug compositions are allowed only with generated unique ids (Remotion refuses duplicates and nearly every scene declares
  `id: "Scene"`) and never as a second timing system.
- `Presentation.tsx` renders `<Series>` with one `<Series.Sequence durationInFrames={d_k}>` per scene, in variant order, each wrapping
  `<SceneBoundary sceneId=… position=…><Scene_k {...props_k} /></SceneBoundary>`. `premountFor` may be set for Studio smoothness; it never
  changes render output.
- `SceneBoundary` is a React error boundary. Under `getRemotionEnvironment().isRendering` it calls `cancelRender(new Error("jarvis_master_scene_failed:<scene_id>:<position>: <message>"))`;
  otherwise (Studio) it draws a visible fallback card naming the scene (« Scène n (pss_…) : erreur — <message> »; the title is not a key
  input, so it never reaches a generated file) and the rest of the video
  keeps its timing (AUDIT A6).

**Implementation (Level 3, Slice 04).** `jarvis/domain/remotion_master_generated.py` `generated_files(...)` writes the four generated files
(no `premountFor` yet); each scene's props are the `merge_props` result (manifest defaults, then instance `props`, `data` under
`props.data`), inlined per scene. Real proof on the pinned 4.0.534 through the REAL guarded render runner (`render-host.cjs`, guard, deny
proxy, Chrome sandbox), `tests/unit/test_remotion_master_files_real.py` (opt-in `JARVIS_REMOTION_RUNTIME_DIR`), 2026-10-13: a 3-scene master
(320x180 @ 30, 30 + 45 + 30 frames; scene 1 `<Audio>` from `staticFile`, scene 2 `<OffthreadVideo>`, scene 3 relative imports
`./parts/Panel` -> `../palette`) bundles, `selectComposition("JarvisPresentation")` passes the host's declared-config check (spec and 105
frames), stills at master frames 0, 29, 30, 74, 75, 104 show exactly scene 1 local 0 and 29, scene 2 local 0 and 44, scene 3 local 0 and 29
with `useVideoConfig().durationInFrames` = the scene's own duration (~8 s for six stills); the MP4 of the whole range has 105 video frames and
an AAC audio stream (~11-14 s at scale 0.5). A scene throwing at every frame: under rendering the boundary's `cancelRender` ends the job with
`jarvis_master_scene_failed:<scene_id>:1: <message>` (the typed job failure is Slice 06); the read-only Studio of the same bundle (route
`?/JarvisPresentation`, `@remotion/studio` query-string routing) shows the fallback card « Scène 1 (pss_…) : erreur — boom in s1 » with the
master timeline intact (evidence: the handoff's `slices/04-master-workspace-materialization/evidence/studio-boundary-fallback.png`).

## 8. Security review: master root in Remotion Studio and the render host

The full review lives beside the earlier rejection in [presentation-studio.md](presentation-studio.md) › *Composition clock (Level 3)*,
*Security review (2026-10-13): master root for Remotion Studio and render only*. In short: the generated multi-scene root stays **rejected for
the Variants Player** (still one sandboxed Player per scene; a master Player is phase C, deferred) and is **accepted for Remotion Studio
(already unsandboxed under explicit acknowledgment) and for the guarded render host only**, because:

- **(a) guards**: each scene source passes its own `parse_source`, isolation and import checks; the planner re-checks every scene's specifiers
  (`master_source_import_refused`: only `SCENE_ALLOWED_IMPORTS`, relative imports stay inside the scene's own folder as mounted, no dynamic
  import, no `require` in any form, no `.context(` and no ASCII `\u` escape: the isolation guard's `LOADER_RULES`, which the per-source guard
  applies first in both lanes), since the webpack bundle used by Studio and render checks nothing (AUDIT A7); these re-checks, like the `getInputProps` one, are
  textual: defence in depth over the per-source guards, not a replacement for them;
- **(b) failure isolation**: one error boundary per Sequence; a render failure is typed and names the scene;
- **(c) budgets**: 400 files / 64 MiB combined, the same Studio guard and the same render egress guard, Chrome sandbox and deny proxy;
- **(d) pins**: each mounted folder `src/scenes/<scene_id>/` names one exact pin; the master workspace is never a hot-reload or publish source
  in A+B.

## 9. Studio master target — Level 3 (Slice 05)

**Open body** (new; the scene body `{prefab_id, version, acknowledge_unsandboxed_scene, discard_unpublished?}` is unchanged byte for byte and
keeps meaning a scene target):

```json
{"kind": "variant_master", "presentation_id": "…", "variant_id": "…", "project_key": "mpk_…",
 "acknowledge_unsandboxed_project": true}
```

plus `"discard_unpublished": true` when the user confirmed setting edits aside (as for a scene, `true` is the only admitted value).

A body mixing `kind: "variant_master"` with `prefab_id`/`version`, or `acknowledge_unsandboxed_scene` with a master body, is
`remotion_studio_invalid` (400). The same body, `discard_unpublished` included, serves `open`, `sync` and `restart`. The scene `restart`
body stays exactly `{"acknowledge_unsandboxed_scene": true}` ([remotion-studio.md](remotion-studio.md) § 2 bis: a scene restart reopens the
recorded scene, so its edits are always kept and it has nothing to discard); `discard_unpublished` there is `remotion_studio_invalid`.

- **Target**: `StudioTarget = scene(pin) | variant_master(presentation_id, variant_id, variant_revision, project_key, scenes: ((scene_id, pin), …))`.
  Target equality for a master is `(presentation_id, variant_id, project_key)`; a changed key is a different target (it goes through `sync`, with
  a new acknowledgment).
- **Acknowledgment**: `acknowledge_unsandboxed_project: true` is required by every `open`, `restart` and `sync` of a master target, and binds to
  that `project_key`. The page's confirmation names the presentation, the variant, **the scene count** (« n scènes vont tourner hors du bac à
  sable, dans Remotion Studio »), and uses the reinforced warning when any mounted version was not written by the user. Only the user's click
  sends it; no brain, MCP or agent path ever does (as today).
- **Planning at open**: Core recomputes the live plan; `incompatible` → `remotion_studio_master_incompatible`; key ≠ body key →
  `remotion_studio_master_stale`; ready and equal → materialize (§ 6) and start or sync the one process. Runner, process guard, port, loopback,
  clean environment, idle stop and egress rules are unchanged; no second Studio process.
- **`state.json`**: a scene target keeps writing `schema: 1` byte-compatible; a master target writes `schema: 2` with
  `target: {kind: "variant_master", presentation_id, variant_id, variant_revision, project_key, scenes: [{scene_id, prefab_id, version}]}`
  instead of `pin`. The reader accepts 1 (`pin` → `target.kind = "scene"`) and 2. An older Core reading schema 2 fails closed as
  `remotion_studio_state_unreadable` (the documented set-aside path; never a wrong scene, no data lost; rollback: [OPERATIONS.md](OPERATIONS.md) › *Studio Remotion optionnel*).
- **View**: the status view gains `target` (`{kind: "scene", prefab_id, version}` or the master shape plus `current_project_key` and
  `stale: bool` from the live plan); `pin` stays for a scene target and is `null` for a master target.
- **Scene listeners**: a ready master target calls the existing scene listeners once per mounted pin (today: ends the agent's
  `agent_authored_scene` permission for that pin; the user's own turns are unaffected).
- **Refresh after a voice edit**: the running Studio never follows a new key by itself. The view says `stale: true`; Variants says the video
  changed since Remotion Studio opened and offers « Actualiser » (a `sync` with the new key, after the same confirmation).
- **Unpublished master edits** (detected by `modified_work` against `work.files.json`, as today), classified:
  1. **generated** (`package.json`, `studio-root.tsx`, and any path under `src/master/**`, normally read-only; a file the user adds there is
     generated too);
  2. **per-scene**: `src/scenes/<scene_id>/**` of a mounted scene, or a `public/**` file owned by exactly one scene;
  3. **shared**: everything else: a `public/**` file owned by several scenes or by none, any other top-level file (e.g.
     `remotion.config.ts`), `src/scenes/<id>/**` of a scene that is not mounted, any other path, and the runner's unreadable-listing marker
     (`<...>`). Classification goes by path only: a link, junction or hard link counts by the path it sits at, like a file.
  A `sync`, `restart` to another key, or a switch to another target with any of them is refused `remotion_studio_unpublished_edits` (409,
  naming the files and their class) unless `discard_unpublished: true`, which sets them aside in `studio-edits/` exactly as today. Never an
  overwrite. A refused `restart` stops nothing: the edits (like a stale or incompatible key) are checked before the running Studio is closed.
- **Agent write gate** (`presentation_studio_scene_edited_in_remotion`): while a master target is recorded, a `brain` source edit of scene X is
  refused only when class-2 edits on X exist, or when the listing is unreadable. Generated or shared edits never block a voice edit (they are
  refused at the next sync instead), so an unpublishable master edit cannot block D5.
- **Publish**: refused `remotion_studio_publish_master_unsupported` before any read. The scene round trip ([remotion-studio.md](remotion-studio.md)
  § 2 bis) is unchanged for scene targets.

**Implementation (Level 3, Slice 05).** `jarvis/domain/remotion_studio.py`: `MasterRequest` (the body), `MasterTarget` (identity
`(presentation_id, variant_id, project_key)`), `StudioTarget = StudioPin | MasterTarget`, `parse_target` / `parse_restart` (the scene body
untouched), `StudioState.master` and `to_payload` / `from_payload` (schema 1 or 2; any other schema, a schema 2 with `pin`, or a malformed
`target` raises: `remotion_studio_state_unreadable`), `target_view`. `jarvis/domain/remotion_studio_master.py`: `classify_edits`
(generated / scene / shared), `MasterWorkspaceBase.edits_on(scene_id, edited)` (the write gate's view), `generated_paths(files)` (the runner
writes `src/master/**` read-only only when the map's `package.json` is `jarvis-studio-master`; a scene's own `src/master/x` stays
editable). `jarvis/core/remotion_studio_service.py`: `_resolve` / `_live_plan` (the live plan through the bound
`MasterProjectReader.live_plan`, then `plan_master_files` into the existing `sync_work`), target equality `same_target`, the scene listeners
once per mounted pin, `public/**` ownership kept from the plan and rebuilt from the immutable pins after a Core restart (unknown ownership
counts as unknown edits for the gate), `stale` / `current_project_key` recomputed by the status poll at most every 5 s with
`live_plan(..., trace=False)`. The write gate is `presentation_studio_reload._refuse_over_studio_edits`. Facts the implementation fixes: a
`sync {}` or a scene-ack `restart` while a master is recorded is `remotion_studio_ack_required`; `restart` with a master body re-plans first
(stale or incompatible: nothing stops) and checks unpublished edits before closing (`_check_unpublished`; refused: nothing stops, QA
Slice 05 polish); the largest master body (128-character ids, `discard_unpublished`) is under 450 bytes, within the
route's 1 KiB cap. Tests: `tests/unit/test_remotion_studio_master.py` (bodies, schemas 1/2 and an older state file, classes, read-only
generated files on the real runner, open / reuse / stale / incompatible / switch / discard / publish refused / restart / adoption, the write
gate on a real reload rig), `tests/unit/test_remotion_studio_master_routes.py` (Core and Control Center routes, page client). Real proof,
`tests/unit/test_remotion_studio_master_real_browser.py` (opt-in `JARVIS_REMOTION_RUNTIME_DIR`), 2026-10-13: a 3-scene variant (1280x720 @ 30,
30 + 45 + 60 frames) opens the real `remotion studio` on the master root in ~84 s cold; headless Chrome on `/JarvisPresentation` shows the
one composition, its duration `00:04.15` (135 frames), the `<Series>` with three `<Series.Sequence>` tracks, and, stepping the playhead, scene 1,
2 and 3 in turn (master frame 120 = scene 3 local frame 45); another variant's key hot-syncs the same process (~0.1 s) after its stale body
was refused 409; an edit of a mounted scene source is classified `scene` and blocks the rebuild until `discard_unpublished`; the scene target
then reopens in the same process with `state.json` schema 1 and the scene alone on the page (evidence: the handoff's
`slices/05-remotion-studio-master-project/evidence/`).

## 10. Whole-video render scope — Level 3 (Slice 06)

**Request**: the existing route and bodies (`{snapshot_id, format, settings?}` or `{presentation_id, variant_id, expected_*_revision,
authorised_boards?, format, settings?}`) with `settings.scope`:

| `scope` | Meaning |
| --- | --- |
| absent or `"scene"` | today's scene scope exactly (`scene_id` rules, `MAX_RENDER_FRAMES`, metadata, dedupe); an explicit `"scene"` is normalized away, so `render_settings_sha256` of a scene render is unchanged |
| `"master"` | the master Remotion Composition of the frozen snapshot; `format` must be `mp4` in A+B (still and pdf → `presentation_render_invalid`); `scene_id` is invalid; `frame_start`/`frame_end` are inclusive master frames within `duration_in_frames`; `scale`, `crf`, `concurrency` as today |

- **Plan**: `choose_master` + `plan_master_files` over the frozen package (each pin revalidated with `parse_source`; `public/live/**` merged under
  M3); `presentation_render_master_incompatible` when not ready. The scene path (`choose_scene`/`plan_files`) is untouched.
- **Bounds**: `MAX_MASTER_RENDER_FRAMES = 9000` on the rendered range; timeout `300 s + 1 s/frame`, capped at 3600 s (unchanged); job folder
  2 GiB and output 512 MiB (unchanged).
- **Host**: the same `render-host.cjs` + `render-guard.cjs`, deny proxy, Chrome sandbox; `selectComposition("JarvisPresentation")` and the
  declared-config check against the plan's master composition (`_composition_mismatch` otherwise).
- **Scene failure**: a `cancelRender` whose message starts with `jarvis_master_scene_failed:` ends the job as `presentation_render_master_scene_failed`
  naming the scene; no partial MP4, no fallback card.
- **Verification**: today's video checks (one h264 stream, master width/height/fps, duration = range) plus, when the rendered range overlaps a
  scene whose source plays an `<Audio>` element, an audio stream must exist (pinned ffprobe; without ffprobe the check fails closed).
  Corrected by Slice 06: a `<Video>` / `<OffthreadVideo>` alone does not require one (its clip may be silent and Remotion then writes no
  audio track), and a range that holds no `<Audio>` scene requires none. The detection is **textual** (comments stripped, `<Audio` or
  `<Html5Audio` in the scene's modules): an aliased import (`import {Audio as Sound}`) skips the check (the MP4 is verified like a scene
  render, without the audio requirement); a user component named `Audio` or a muted `<Audio>` counts, and if Remotion then writes no audio
  track the job fails `presentation_render_output_invalid` with « the whole video plays an <Audio> but the MP4 holds no audio stream »
  (the user renders a range without that scene, or removes the element).
- **Artifact**: one `presentation_video` derivative, one `rendered_from` relation to the snapshot, `render_flat: true`. Metadata for a master
  render: `render_scope: "master"`, `render_project_key`, `render_scene_count`, `render_composition: "JarvisPresentation"`, the master
  `render_fps` / `render_width` / `render_height`, the shared engine keys, and the MP4/finish keys of today; the per-scene keys
  (`render_scene_id`, `render_prefab_id`, `render_prefab_version`, `render_source_digest`) are absent. Every derivative written after Slice 06
  carries `render_scope` (`scene` or `master`); a derivative without it is a scene render. 32 keys at most, as today.
- **Dedupe**: `render_settings_sha256` of a master render = SHA-256 of the canonical resolved settings (with `scope`) + `project_key` + engine
  version + lock digest. Same snapshot + same settings → the existing job or derivative.
- **Readiness of a frozen snapshot** (for the Board, M13): a read-only route of the render family,
  `GET /v1/local-capabilities/remotion/render/master?snapshot_id=…`, relayed under `/api/local-capabilities/remotion/render/master`, returns
  the plan view of § 2 for that package (Slice 06).
- **Preview** (`render/preview`) stays scene-scoped (the author's eye).

**Implementation (Level 3, Slice 06).** `jarvis/domain/presentation_render.py`: `settings.scope` (`SETTINGS_KEYS`; absent or `"scene"` gives
the same `RenderSettings`, so a scene render's `render_settings_sha256` is unchanged), `MasterTarget`, `MAX_MASTER_RENDER_FRAMES` (9000, the
planner re-exports it), `presentation_render_master_incompatible` (409; `RenderError.extra` puts `reason`, `detail`, `scene_ids` in the HTTP
envelope beside `code` and `message`), `presentation_render_master_scene_failed`, `master_scene_failure` (reads the boundary's marker).
`jarvis/domain/presentation_render_master.py`: `choose_master(package)`, `master_files(package, target)` (re-plans the re-read package at
execution: another `project_key` is `presentation_render_snapshot_invalid`), `audio_ranges` (textual `<Audio>` check per mounted scene).
`PresentationRenderService.export` with `scope: "master"` first plans the LIVE variant (`MasterProjectReader.live_plan`, wired in
`v2_app`) and refuses an incompatible one (409 `presentation_render_master_incompatible`) before anything is frozen; once frozen, the
package's own plan is the authority. `PresentationRenderService.submit` resolves a master target before creating anything and queues it like any render (same queue, browser
slot, cancellation, restart recovery, guard, disk budgets); the job runs `render-host.cjs` with entry `studio-root.tsx`, composition
`JarvisPresentation` and input props `{}`; a master job view adds `scope`, `project_key`, `scene_count` (its `scene_id` is `null`).
`RenderRunner.verify(..., audio_required=True)` checks the audio stream. `PresentationRenderService.master_readiness(snapshot_id)` serves
`GET .../render/master?snapshot_id=` (the only render route that takes a query; the id must be a snapshot id), relayed by the Control Center
(`jarvis/runtime/presentation_render_relay.py`, the id checked before the relay). MCP `remotion_export` takes `scope` since Slice 07 (§ 12).
Tests: `tests/unit/test_presentation_render_master.py`, routes and relay tests; real proof `tests/unit/test_presentation_render_master_real.py`.

## 11. Live readiness read — Level 3 (Slice 05)

`GET /v1/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/master-project` (Core, read-only, no side effect, no process)
returns `{"master": <plan view of § 2>}` from the live variant; relayed read-only by the Control Center under
`/api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/master-project`. Studio open, Variants and the agent all read
this one view; none of them computes readiness itself (Slice 05).

**Implementation (Level 3, Slice 05).** Core route `PresentationStudioProtocolRoutes.master_project`
(`jarvis/protocol/presentation_studio_routes.py`) over `core.remotion_master_project` (`MasterProjectReader`, wired in `v2_app`, also bound
to the Studio service for its master target); the relay row `studio_master_project` of `jarvis/runtime/presentation_studio_relay.py`. An
unknown presentation or variant is the usual 404 `presentation_studio_unknown_*`; a query parameter is 400. The page client reads it with
`JarvisRemotionStudioCore.createClient(...).masterProject(presentation_id, variant_id)`. Tests: `tests/unit/test_remotion_studio_master_routes.py`.

## 12. Voice and agent — Level 3 (Slice 07)

- **Spec of new scenes (M11, Slice 07)**: authoring a scene into a variant that has scenes uses the variant's shared spec; a brand-new native
  deck uses 1920x1080 @ 30 fps (the native example). Structured and guided defaults (1280x720 @ 30) are unchanged, so a deck authored by one
  path is master-ready by construction.
- **Collision-free assets (Slice 07)**: the authoring guidance makes each scene name its `public/` files with a scene-unique stem written in
  both the path and the `staticFile()` literal (for example `public/intro-voice.mp3`); this is authoring, not rewriting. The planner still
  refuses any collision.
- **Inspect**: `presentation_inspect` gains a compact `master` block (`status`, `reason`, sentence, `project_key`, scene count, duration in
  seconds); `presentation_source` `write`/`preview` results carry the same block after the write, so the agent sees a collision or a spec
  mismatch at once. MCP budget pins (`test_mcp_catalog.py`) are updated deliberately.
- **Export**: `remotion_export` admits `scope` in its settings (`EXPORT_SETTINGS`); on the user's explicit request for "the video", the agent
  sends `scope: "master"`. When the master is incompatible it says the reason sentence and offers scene exports; it never presents a scene
  render as the whole video and never concatenates clips.
- **Re-edit refresh**: a voice edit goes through `presentation_source write` (new immutable version, repin, revision + 1): the live plan's
  `project_key` changes, an open master Studio becomes `stale`, and the next whole-video export freezes the new revision and renders the new
  key. The agent compares `render_project_key` with the current key and never reuses an older derivative as "the updated video".
- **Never**: the agent does not open Remotion Studio, does not write in a master workspace, does not claim it edited master files.

**Implementation (Level 3, Slice 07).**

- **Sentences and view**: `jarvis/domain/remotion_master_sentences.py` holds the § 3 user sentences word for word (`REASON_SENTENCES`; the
  scene position and the colliding path are filled from `detail` when it names them; an unknown reason is said as « La vidéo entière n'est pas
  disponible pour cette variante. », never re-labelled) and `agent_view(wire)`, the compact `master` block: ready → `status`,
  `variant_revision`, `project_key`, `scenes` (count), `duration_s`, `spec` (`1920x1080@30`); incompatible → `status`, `reason`, `say`
  (the sentence), `detail`, `scene_ids`. It projects the plan view; it never re-checks anything.
- **Where the agent reads it**: `PresentationTools._master_block` (`jarvis/runtime/presentation_studio_mcp_tools.py`) reads
  `GET .../master-project` (§ 11) through `LocalCoreClient.presentation_studio_master_project` and adds `master` to `presentation_inspect`
  target `variant`, to a standing `presentation_source` write (read after the write) and to a preview, and to `presentation_draft_assemble` /
  `_finalize`. A failed read never fails the call it rides: `master: {status: "unknown", error: <code>}` and a warning
  `presentation_studio.master_unread` in the journal.
- **Export**: `remotion_export` `settings.scope` (`EXPORT_SETTINGS`; the scope names are `SCOPE_SCENE` / `SCOPE_MASTER` of `jarvis/domain/presentation_render.py`). `master` with `scene_id` is `invalid_setting`, with
  `still`/`pdf` `invalid_format`, both before any Core call; an explicit `"scene"` is dropped, so a scene export's body is today's. The result
  says `video: "whole"` (« L'export de la vidéo entière (N scènes) est lancé »; the count is left out when Core's job lacks `scene_count`),
  `video: "whole_range"` when a master export carries `frame_start`/`frame_end`/`frame` (« L'export d'un extrait de la vidéo entière (images
  a–b, pas la vidéo complète) est lancé »: an extract is never announced as the whole video) or `video: "scene"` (« L'export d'une scène
  seule est lancé (pas la vidéo entière) »); job rows carry `scope`, `scene_id`, `project_key`, `scene_count`. Core's 409 `presentation_render_master_incompatible`
  becomes a refusal with the sentence, « Rien n'a été exporté ni modifié » and the scene-export offer; Core froze nothing (§ 10, live pre-check).
- **Authoring**: `NATIVE_DEFAULT_COMPOSITION` (1920x1080 @ 30, `presentation_studio_authoring_remotion.py`) fills what a NATIVE bundle leaves
  out (`generate_source(..., native=True)`); guided bundles keep `DEFAULT_COMPOSITION` (1280x720). `MASTER_HINT` (authoring guide, native
  `draft_guide` `draft.master`, and the author playbook) says: one width/height/fps for every scene (a new deck 1920x1080 @ 30, an added or
  rewritten scene keeps the variant's), `public/` files named after their scene in the path and in `staticFile()`, never `getInputProps`,
  read the `master` block. `ISOLATION_HINT` says the guard refuses the word `require` and ASCII `\u` escapes even in displayed text.
  Technical compatibility only: no content, layout or style rule is added; native warnings stay warnings.
- **Brain prompt**: `BRAIN_REMOTION_PROMPT` routes « la vidéo » / « exporte-la » to `scope master`, tells the incompatible path, and that a
  scene export is never « la vidéo » and an older export is not the updated video.
- **Re-edit**: no new code. The live plan reads the variant's current pins, so a standing `presentation_source` write (new version + repin)
  changes `project_key` with no sync call, and the next whole-video export freezes the new revision (a new snapshot, never the older
  derivative). Proof through the real studio, prefab store, source-edit service, packager and render service:
  `test_a_standing_source_edit_changes_the_key_and_the_next_whole_video_export_renders_the_new_pin`.
- The `remotion_studio` pointer wording for a master target (§ 14) came with the Variants master button (Slice 08, § 13).
- Tests: `tests/unit/test_remotion_master_agent.py`; real trace: the handoff's `slices/07-voice-generation-and-reedit/evidence/`.

## 13. Variants and Board entrypoints — Level 3 (Slice 08)

- The primary « Remotion Studio » action under the Variants video targets the **variant master** when the plan is `ready`; its state line names
  the presentation, the variant and the scene count, not one scene.
- When the plan is `incompatible`, the same button keeps today's scene door, and the line says the sentence of the reason followed by
  « « Remotion Studio » ouvre donc la scène à l’écran. » (one sentence per state, never « indisponible » twice).
- The scene-only door stays reachable as a secondary entry (« Cette scène seule dans Remotion Studio »), never as prominent as the primary one.
- One « Exporter la vidéo » action in Variants freezes the active variant and submits `scope: "master"` (format `mp4`); disabled with the reason
  sentence when not ready.
- The Board Artifacts export button (`control_center_workspace.js`, today `{snapshot_id, format}`) reads the snapshot readiness (§ 10) and adds
  `settings: {scope: "master"}` only when it is `ready` with at least two scenes; otherwise it posts today's body unchanged. A single-scene
  snapshot keeps the scene export body (`{snapshot_id, format}`, no `scope`), byte for byte as before.
- Current scene selection, Players, transport and the Variants composition clock are untouched.

**Implementation (Level 3, Slice 08).**

- **One read, no decision.** `createRemotionDoor` (`control_center_presentation_studio_explorer_remotion.js`) reads `GET .../master-project`
  (§ 11, `JarvisRemotionStudioCore.createClient(...).masterProject`) once per `(presentation, variant, variant revision)`, as soon as a Remotion
  scene is on screen (an HTML deck never asks), and again when the variant's revision changes (the Variants preview reload: hot reload, voice
  edit, publication). It keeps the same variant's previous plan on screen while the new revision is read. The page computes no compatibility:
  `doorModel` only reads `status`, `reason`, `detail`, `project_key`, `composition` and `scenes`. The § 3 sentences are
  `JarvisRemotionStudioCore.MASTER_REASONS` / `masterReasonSentence`, the table of `remotion_master_sentences.py` word for word (a parity
  test). An unreadable view (an older Core, a variant gone, a network failure) keeps the scene door and says « La vidéo entière n’a pas pu être
  lue (<code>) : « Remotion Studio » ouvre la scène à l’écran. » (logged `remotion_master_read_failed`, `warn`).
- **Primary door, master target.** Ready: the button reads « Remotion Studio » (`data-target="master"`, name « Remotion Studio, vidéo entière »),
  and its master line « Vidéo entière : « Atelier », variante 2, 3 scènes (4,5 s). » with the quiet secondary « Cette scène seule dans Remotion
  Studio » (a text button on that line in the line's muted ink and normal weight, accent and underline only on hover or keyboard focus,
  `data-act="remotion_studio_scene"`; the master line text is its own `role="status"` live region, the button outside it). A click opens ONE confirmation in Variants' layer
  (`data-target="master"`, `JarvisRemotionStudioCore.masterConfirmSpec`): « Ouvrir la vidéo entière hors du bac à sable ? », the identity
  « « Atelier », variante 2 · 3 scènes · 4,5 s (1280×720, 30 i/s) », « 3 scènes vont tourner hors du bac à sable, dans Remotion Studio … »,
  the same origin and data lines as a scene, each mounted version, their provenance; any version not written by the user (or unreadable) gives
  « Ouvrir une vidéo dont vous n'avez pas écrit toutes les scènes ? », a red button, the focus on « Annuler » and « Attention : … ». Confirming
  sends `open {kind: "variant_master", presentation_id, variant_id, project_key}` (the client adds `acknowledge_unsandboxed_project`), plus
  `discard_unpublished: true` only when the dialog said « Fichiers non publiés : … seront mis de côté (studio-edits), pas publiés. ». `open`
  also switches or refreshes a running Studio (Core's `_sync_locked`).
- **Answers.** `remotion_studio_master_stale` (409) → the readiness is read again and the dialog re-asks with « La variante a changé depuis
  votre confirmation : la vidéo entière compte maintenant N scènes. Confirmez de nouveau. » (three times at most, then said);
  `remotion_studio_master_incompatible` → the § 3 sentence of the envelope's `reason`, the readiness is read again and the button falls back
  to the scene door; `remotion_studio_unpublished_edits` not anticipated → the dialog re-asks with the discard line. Every failure:
  `remotion_studio_open_failed` (`error`).
- **States of the line** (`.jvx-rms-text`): this whole video open « Remotion Studio est ouvert sur la vidéo entière (3 scènes), dans un autre
  onglet. » + the link (button `data-state="here"`, « Remotion Studio, ouvert sur la vidéo entière », a click opens another tab without a
  dialog); an older key (Core's `target.stale`, or the page's key differs) « La vidéo a changé depuis son ouverture dans Remotion Studio
  (maintenant N scènes) : « Actualiser » l'y recharge, après confirmation. » + « Actualiser » (`data-act="remotion_studio_master_refresh"`,
  the same dialog, « Actualiser la vidéo entière dans Remotion Studio »); another variant's whole video; a scene open (« … ouvert sur cette
  scène seule (source v1) … « Remotion Studio » y affiche la vidéo entière, après confirmation. », its publish flow unchanged). Never « ouvert
  sur la scène N » for a master target. A failed read of Core's view other than `remotion_studio_unavailable` (Core stopped, network,
  deadline; Slice 09 polish) leaves nothing of the last view on screen — Core's stop closes Remotion Studio, so never « ouvert », no link,
  no publish: the line says « Core injoignable : l’état de Remotion Studio n’est plus confirmé. » (another code: « Remotion Studio illisible
  (<code>) : l’état affiché n’est plus confirmé. »), both doors are `aria-disabled` with that sentence and « Réessayez dans un instant. »,
  the view is read again every 5 s, and a click reads it first (still unreadable: nothing opens). Core back: the usual words.
- **Publish.** Edits of a whole-video workspace (`workspaceOf(...).relation === "master"`) are said « n fichiers modifiés dans Remotion Studio
  (vidéo entière), pas publiés : la vidéo entière ne se publie pas dans la variante. Pour publier une scène, ouvrez-la seule (« Cette scène
  seule dans Remotion Studio ») ; ces fichiers seront mis de côté (studio-edits), après confirmation. »; « Publier dans la variante… » stays
  hidden for a master target (Studio stopped too). The scene door then sets them aside after its own dialog says so.
- **Whole-video export.** `createVideoExport` (`control_center_presentation_studio_explorer_export.js`, `JarvisVariantsVideoExport`): « Exporter
  la vidéo » between « Remotion Studio » and « Présenter » (hidden until the whole video is asked for, during a run and in the stage
  fullscreen). It reads the door's view (`door.master()`), never a second read. Ready: `POST /api/local-capabilities/remotion/render/jobs`
  `{presentation_id, variant_id, expected_presentation_revision, expected_variant_revision, format: "mp4", settings: {scope: "master"}}`
  (Core freezes the variant at those revisions, § 10; no Board is authorised, as for the agent's export: a variant whose scenes read a live
  Board file is refused by Core, `live_ref_not_authorised`, said with its code). Its line `.jvx-vx`: « Export de la vidéo entière : demande envoyée, la variante est figée… », then « Export de la
  vidéo entière (3 scènes) — Rendu des images · 40/135 images (29 %) · 12 s · délai 7 min au plus » with « Annuler l'export », polled every
  2 s (three failed reads in a row: said and stopped; past the job's timeout + 2 min: « Aucune fin lue après … »); done « Vidéo entière
  exportée : Artefact jart_… (2,3 Mo). » + « Ouvrir la vidéo » (`/api/artifacts/{id}/payload`). A refusal is a French sentence with
  Core's code in small print (`.jvx-vx-code`, `describeExportError` / `EXPORT_ERRORS`): no render service or Remotion capability
  (`presentation_render_unavailable`, `presentation_render_runtime_unavailable`, `remotion_studio_unavailable`) → « L’export vidéo n’est pas
  disponible sur ce poste (moteur Remotion absent). »; `live_ref_not_authorised` → « Les scènes lisent en direct des fichiers d’un Board :
  lancez l’export depuis les Artefacts de ce Board. »; `presentation_render_master_incompatible` → the § 3 sentence (and a re-read);
  `presentation_studio_stale_revision` → the variant is read again; an unknown code → « Core a refusé l’export de la vidéo entière. » with
  Core's detail beside the code. « Réessayer » only for a failure another try can fix (network, deadline, Core unreachable or 5xx, a failed
  render job, a stale revision, a full queue). A failed job whose failure the same frozen variant would repeat offers no « Réessayer »
  (`JOB_FAILURES`, Slice 09 polish): `presentation_render_master_scene_failed` names the scene from Core's `error_detail` (« Export de la vidéo
  entière échoué : la scène 2 a échoué pendant le rendu, aucun fichier n’a été gardé. Corrigez la scène 2, puis exportez de nouveau. »),
  and `presentation_render_composition_mismatch`, `presentation_render_job_too_large`, `presentation_render_output_too_large` say why; any
  other job failure (crash, timeout, interruption, full disk) keeps « Réessayer ». The small print wraps inside the line at every width
  (`.jvx-vx-code`: `flex: 0 1 auto`, `min-width: 0`, `overflow-wrap: anywhere`). Not ready: `aria-disabled`, title and click say « <sentence> Exportez plutôt les scènes une à
  une depuis les Artefacts du Board. ». A running master job of this `project_key` (voice, another window) is picked up when Variants
  shows the variant. Logs `video_export_*`.
- **Board Artifacts.** `exportStart` (`control_center_workspace.js`) for `mp4` reads `GET /api/local-capabilities/remotion/render/master?snapshot_id=`
  (`PATHS.renderMaster`, allowed only with exactly that query, the render deadline) and posts `settings: {scope: "master"}` only when
  `status` is `ready` and the plan has at least two scenes (its line says « Export MP4 (vidéo entière, N scènes) en cours »); a single-scene
  snapshot keeps the scene export body, byte for byte; incompatible, unreadable (logged `workspace.export_master_read_failed`), `still` and
  `pdf` post today's body unchanged.
- **Rail and voice.** The rail's « Remotion Studio… » opens Variants then this door, which waits for the scene's and the whole video's reads:
  the whole-video dialog when ready, the scene dialog otherwise. MCP `remotion_studio` (§ 14) says « dans Variantes, clique « Remotion
  Studio » sous la vidéo et confirme ; la vidéo entière de la variante (ou la scène à l'écran si la vidéo entière n'est pas disponible) … »
  and, for a named scene, « Cette scène seule dans Remotion Studio ».
- **Unchanged**: scene selection, Players, transport, presenter, the scene strip, the stage fullscreen and the composition clock.
- Tests: `tests/unit/test_variants_master_entrypoints_js.py` (sentences parity, models, the fake-DOM flows, the Board body),
  `tests/unit/test_variants_master_entrypoints_browser.py` (real Chrome on an isolated stack; real Studio and render opt-in with
  `JARVIS_REMOTION_RUNTIME_DIR`). Real run, 2026-10-13: on a 3-scene deck (640x360 @ 30, 20 + 30 + 40 frames) the page's « Remotion
  Studio » opened the real `remotion studio` on the master in ~67 s cold (Core's view `target.kind: "variant_master"`, 3 scenes; Remotion
  Studio's page lists `JarvisPresentation` with the `<Series>` of three sequences), then the page's « Exporter la vidéo » rendered the
  90-frame whole-video MP4 in ~23 s (`render_scope: master`, 3 scenes, verified by ffprobe). Evidence: the handoff's
  `slices/08-variants-master-entrypoints/evidence/`.

## 14. Backward compatibility

| Caller | Contract |
| --- | --- |
| `presentation_render.scene_target` / `choose_scene` | unchanged: a multi-scene snapshot without `scene_id` and without `scope: "master"` still answers `presentation_render_unknown_scene` |
| `plan_workspace`, `plan_files`, their pinned root and `jarvis-studio-scene` package | unchanged; the master has its own planner |
| render route bodies without `scope` | identical meaning, identical `render_settings_sha256` |
| Studio scene body, scene ack, scene `state.json` schema 1, scene publish | unchanged |
| MCP `remotion_studio` | still a pointer, never opens; wording names the master entry « Remotion Studio » (the whole video when ready) and, for a named scene, « Cette scène seule dans Remotion Studio » (Slice 08) |
| Variants Players, composition clock, presenter, score and cues | unchanged |

## 15. Non-goals (A+B)

- **Master publish-back**: no edit of `studio-root.tsx`, `src/master/**`, shared `public/**` or any master file is published into Jarvis data;
  named here as deferred (Level 1 non-goal).
- **Master Player (phase C)**: the Variants Player stays one sandboxed Player per scene; replacing it with one master Player is deferred and
  needs its own security review.
- Making the master workspace canonical; mixed-spec mapping; rewriting `staticFile()`; concatenating pre-rendered scene clips; any widening of
  the trust policy.

## 16. Levels and owners

| Concept | Level now | Target | Owner Slice |
| --- | --- | --- | --- |
| MasterProjectPlan, readiness codes, `project_key`, asset merge | 3 (Slice 03) | 3 | 03 |
| Master workspace files, generated composition, boundary | 3 (Slice 04) | 3 | 04 |
| Studio master target, ack, `state.json` schema 2, unpublished policy, live readiness route | 3 (Slice 05) | 3 | 05 |
| Render scope `master`, bounds, Artifact metadata, frozen readiness route | 3 (Slice 06) | 3 | 06 |
| Voice spec rule, collision-free names, inspect block, `scope` in `remotion_export` | 3 (Slice 07) | 3 | 07 |
| Variants and Board entrypoints | 3 (Slice 08) | 3 | 08 |
| Master publish-back, master Player | 1 (non-goal) | 1 | — |

Conformance of this page: `tests/unit/test_remotion_master_project_docs.py` (codes, key inputs, bounds, composition id, acknowledgment, scope
key, terminology, qualified scene-lane sentences).
