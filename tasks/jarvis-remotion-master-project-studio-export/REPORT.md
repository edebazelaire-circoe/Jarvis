# Final implementation report: Remotion master project + whole-video export (A + B)

Task `jarvis-remotion-master-project-studio-export`, branch `task/jarvis-remotion-master-project-studio-export`, base `d101d887`.
Written by the Slice 09 Work Agent on 2026-10-13 and committed by agent 0, because the harness refuses `.md` writes from sub-agents.
Nothing in this report is a Human approval: the Human checks are in § 9.

## 1. Outcome

| Slice | State | Commits |
| --- | --- | --- |
| 00 Project Manager readiness | done (READY) | `4bba7217`, `495cd96d`, `65e5cf07`, baseline in `5190fe39` |
| 01 Current state and compatibility audit | approved | `88a62c5c` |
| 02 Master project contract | approved | `9c0d9d5e` |
| 03 Master project planner | approved | `c4dda62f`, polish `10598193` |
| 04 Master workspace materialization | approved after rework | `d04531bf`, rework `324e028c` (Issue 01 fix) |
| 05 Remotion Studio master project | done, polished after QA | `82bb0c7a`, polish `3cafbbca` |
| 06 Whole-variant render/export | approved after rework | `a883be40`, rework `dc79e8c9`, merge `5190fe39` |
| 07 Voice generation and re-edit | done, polished after QA | `8c7c6c4a`, evidence `7fbfb9ec`, polish `c2cb960c` |
| 08 Variants master entrypoints | done, polished after UI QA | `9b0e7185`, polish `a9aa1ccd`, `b658b4d3` |
| 09 Release and Human acceptance | machine part done; Human checks prepared | `7c416cdb` (journeys, trace, privacy), `2dc48af1` (docs), `42c7f2d2` (Human checklists, LOG), polish `7fb66c82` (R1, R3), rework `6d61861e` (sweep regression), this report |

No Slice is incomplete on the machine side. Phase C (one master Player replacing the Variants sequencer) and master publish-back are not
implemented and are documented as Level 1 non-goals (`docs/remotion-master-project.md` § 15).

## 2. What the user gets

- **One Remotion project per variant.** `MasterProjectPlan` derives, from the live variant or from a frozen snapshot, one normal Remotion
  project: each scene's exact pinned source under `src/scenes/<scene_id>/`, a merged `public/`, and a generated `<Composition
  id="JarvisPresentation">` that plays the scenes end to end in a `<Series>`. It is never persisted and never canonical.
- **Remotion Studio on the whole video.** « Remotion Studio » under the Variants video opens the whole variant when it is master-ready
  (confirmation naming the scene count). « Cette scène seule dans Remotion Studio » keeps the scene round trip with publish.
- **Whole-video export.** « Exporter la vidéo » in Variants (and the Board's MP4 export when the snapshot is ready with ≥ 2 scenes) renders
  `JarvisPresentation` through the same guarded render host: one `presentation_video` Artifact, `render_scope: master`.
- **Voice.** The agent reads a `master` block, exports « la vidéo » with `scope: master`, and a voice edit (new scene version, repin)
  changes `project_key`, so the next export renders the edit. The agent never opens Studio.
- **Legacy decks keep working.** A mixed-fps or mixed-size deck is refused for the master with a § 3 sentence; it still plays, opens a
  scene in Studio and exports scene by scene.

## 3. Release evidence (Slice 09, isolated real stack)

Runtime: `RemotionStack` (real Core, real Control Center, real `remotion studio`, real guarded render host) on free loopback ports, with a
throw-away data root and a private copy of the gate runtime (Remotion 4.0.534). The page ran in headless Chrome over CDP. The live Jarvis and
the user's own Remotion Studio were never started, stopped or contacted. Harness: `tests/unit/test_remotion_master_release_real.py`
(opt-in). Product code tested: `b658b4d3`. Evidence: `slices/09-release-and-human-acceptance/evidence/` (933 KB).

**A1. Compatible deck in Remotion Studio** (passed; `release-studio-summary.json`, `studio-master.png`)

- **Deck:** 4 scenes at 1920x1080 @ 30, lasting 30 + 45 + 30 + 45 frames. Scene 1 plays an `<Audio>` and scene 2 an `<OffthreadVideo>`.
  Scene 3 imports its own modules. Each scene paints its own colour ramp from its local frame.
- **Variants:**
  - the master line reads « Vidéo entière : « Release S09 », variante 1, 4 scènes (5 s). »;
  - the dialog says « 4 scènes vont tourner hors du bac à sable »;
  - Studio becomes ready in about 32-38 s from the click.
- **Core's view:** `target.kind: variant_master`, 4 scenes. The workspace holds `src/master/**` and `src/scenes/<id>/Scene.tsx` × 4.
- **Remotion Studio's own page:** lists `JarvisPresentation` (1920x1080, 30 fps, `00:05.00`). Its timeline shows the `<Series>`, the
  sequences and the `rel-s1-tone.wav` track. Stepping through it showed SCENE-1, 2, 3 and 4 in turn.

**A2. Whole-video MP4 exported from Variants** (passed; `release-export-summary.json`, `boundaries.png`, `export-done.png`)

- **Variants line:** « Vidéo entière exportée : Artefact jart_… (393 Ko) », about 40 s from the click.
- **Metadata:** `render_scope: master`, `render_scene_count: 4`, `render_composition: JarvisPresentation`, `render_project_key` = the plan's
  key, `render_verified_by: ffprobe`, `render_sandbox: true`.
- **ffprobe:** h264 1920x1080, 30/1, 150 frames read, 5.01 s. AAC 48 kHz stereo.
- **Boundaries:** the frames before and after every boundary (0/29, 30/74, 75/104, 105/149) each show the expected scene at local frame 0
  or at its last frame. Measured RGB values: (40,0,0) / (156,0,0) / (0,39,0) / (0,215,0) / (0,0,40) / (0,0,156) / (40,0,40) / (215,0,216).
  So no frame is substituted and nothing is truncated.
- **Audio:** −18.3 dBFS in scene 1 (the `<Audio>`) and digital silence from 2 to 5 s.

**B. Incompatible legacy deck** (passed; `legacy-summary.json`, `legacy-variants.png`)

- **Deck:** the gate's 9-scene deck at 30/25/60/24 fps.
- **Readiness:** `master_fps_mismatch`. The page shows the § 3 sentence + « « Remotion Studio » ouvre donc la scène à l'écran. ».
- **Export:** « Exporter la vidéo » is `aria-disabled`, and its title gives the sentence and the scene-export advice. A whole-video POST is
  refused 409 `presentation_render_master_incompatible`; 0 jobs were created.
- **« Lire »:** after 4.5 s the Player had moved from S1 (3 s long) into S2, at frame 39.
- **Scene door:** opened the real Studio on the scene (`target.kind: scene`).
- **Scene export:** completed, 90 frames, `render_scope: scene`. Canonical files unchanged.

**C. Failure injections.** Each run hashed every presentation-store and prefab-store file before and after. Every injection below left 0
changed files, and each one failed visibly.

| Injection | Observed |
| --- | --- |
| Unpublished master Studio files (a scene source + a top-level `remotion.config.ts`) before a switch to another variant | 409 `remotion_studio_unpublished_edits` with classes `scene` and `shared`. The files stay untouched and the master stays open. With `discard_unpublished`, both are copied to `studio-edits/<timestamp>/` and the switch happens. |
| Core outage while the master Studio is open | The page shows « Scène figée · Core injoignable. Nouvel essai automatique. » and « Rail injoignable : l'état affiché n'est plus confirmé. » (`readError: core_unreachable`). Core's stop closed the Studio, so no orphan was left. `state.json` stayed at schema 2 / `variant_master`. After the restart: status `stopped`, and the page's line clears. See risk R1. |
| Repin between plan and export | A job frozen before the repin renders the old key (`render_project_key` = the old key) while the live key changes: the frozen snapshot wins. The stale export body is refused 409 `presentation_studio_stale_revision`; a Studio open with the old key is refused 409 `remotion_studio_master_stale`, naming the new key. A re-read package whose key differs is refused `presentation_render_snapshot_invalid` (unit test). |
| Render browser unusable during the export | The job fails. The page says « Export de la vidéo entière échoué : aucun fichier n'a été gardé. » with the code in small print. The code is `presentation_render_sandbox_unavailable` (see risk R2). |
| No browser at the request | 409 `presentation_render_browser_unavailable` with its sentence. |
| A scene that throws | The job fails with `presentation_render_master_scene_failed · scene 2 (pss_…) failed while rendering: boom in the second scene`, said on the page. No MP4 is kept. |

**Path probe.** The answers of the master-project route, the Studio status, open and sync, the render jobs (including failed jobs'
`log_tail`), the frozen readiness route and the 409 envelopes carry no drive-letter path, no data root, no temp folder and no home folder.
Failed jobs' `log_tail` is already sanitized to `<path>`.

**D. Real agent trace, rerun.** Rerun because Slice 08 changed agent-facing text (`remotion_studio` wording, `_export_label`, one prompt
clause). Run `trace-t2` used claude-sonnet-5-5 on `b658b4d3` with `--strict-mcp-config`, the Slice 07 harness and six addressed turns. It
cost **USD 0.92** (budget 2).

- **Author:** a 3-scene native deck, delivered after 22 calls with no refusal. The F1 `Frame` refusal of `t1` did not recur.
- **Readiness:** read from the `master` block.
- **First export:** one `remotion_export scope master` → 450 frames, 1920x1080, key `mpk_e46b…`.
- **Voice edit:** one `scene.source_request` + 1 background agent (read → write → preview, 8 calls). The `remotion_status` call seen in
  `t1` (F2) is gone.
- **Re-export:** a new key `mpk_0ded…` → 450 frames.
- **Frame diff:** scene 1 mean 0.01, scene 2 mean 11.44, scene 3 mean 0.22. So only the edited scene changed.
- **« Deux cadences »:** the brain read `presentation_inspect` and said the cadence refusal and the scene-export offer, with no export
  call. In `t1` it had tried the export and been refused; both are acceptable.
- **Brain:** 11 calls, no Studio call, no scene export mislabelled.

## 4. Tests and validators

- **Release harness** (new, opt-in): `tests/unit/test_remotion_master_release_real.py`, 3 tests, all passed (a1 254 s, a2 200 s,
  legacy 112 s).
- **Privacy:** `tests/unit/test_master_project_evidence_privacy.py` (new, 3) runs `tests/replay/evidence_privacy.py` over the whole task
  folder. The sweep was extended:
  - it now finds a `sessionId` in camel case and JSON-escaped forms;
  - it redacts a session id's value everywhere in the file with one placeholder, so the JSON stays valid;
  - it adds the nested-JSON path spelling.
  - `test_tool_brain_evidence_privacy.py` still passes (3).
- **Directly touched areas, rerun once at the end** (one file per process):

  | Area | Files (passed) |
  | --- | --- |
  | Planner | planner 48, files 15 |
  | Studio | master 57, routes 5, studio 44, rework 43, publish 34+1 skip |
  | Render | master 22, domain 47, service 58, routes 27, relay 9, runner 42 |
  | Agent and MCP | master agent 29, remotion MCP tools 40, MCP catalog 92 |
  | Page scripts | Variants master entrypoints JS 22, Studio JS 15, publish JS 12, workspace manager 25, workspace presentations 23, Control Center Studio 26, transport JS 29 |
  | Guards and source | isolation 267, reload service 57, source edit service 36, freeze 39, artifacts 43 |
  | Browsers | entrypoints 7+1 skip, Studio door 7+1 skip, controls 8+2 skip |
  | Real runtime | scene Studio round trip 1 (publish), master render 2 |
  | Docs | 46 documentation-related files: 502 passed, 0 failed |

- **Wide sweep** (separate agent, detached worktree at `b658b4d3`, `tests/unit` + `tests/integration`, 875 files, chunked, failing
  files rerun alone): **22 112 passed, 24 failed, 0 errors, 146 skipped** (baseline 21 837 / 23 / 0 / 140; the task adds ~275 tests).
  - 22 deterministic failures, all inherited: same test ids and messages as the baseline (16 older + the 6 of Issue 03).
  - 2 load flakes in code the task does not touch (`test_memory_context` recall budget, as in the baseline;
    `test_device_playback_completion`, 25/25 alone).
  - **1 task-caused intermittent failure**, `test_variants_remotion_studio_browser.py::test_a_failed_start_is_said_with_its_code_and_retry_recovers`
    (5/10 at `b658b4d3`, 10/10 at `d101d887`). Root cause: the master line appearing under the scene row moved « Cette scène seule dans
    Remotion Studio » under the pointer aimed at « Remotion Studio », so a click could open the scene (a real misclick for a user too).
    Fixed in `6d61861e`: the line reserves its height and says « Vidéo entière : lecture en cours… » while readiness is read, the button is
    `aria-busy` and its click waits for the current revision's read, « Réessayer » retries exactly the target that failed. 10/10 alone
    (agent) + 3/3 (agent 0); the touched files rerun green, including with the real runtime.
  - **Real runtime pass** (`_remotion-runtime-gate`, one file per process): 35 of 36 real/browser/release-gate files pass, including the
    three release gates; the 36th was the flake above. Only `test_remotion_import_real.py` skips (network installs off).

## 5. Documentation (final Level 3)

The contract `docs/remotion-master-project.md` is now Level 3 (status line and release proof); `tests/unit/test_remotion_master_project_docs.py`
pins it. Other pages:

- `docs/OPERATIONS.md`:
  - master Studio workspace files and `state.json` schema 2;
  - `studio-edits/` set-aside location and rotation;
  - Core outage;
  - **rollback steps**;
  - master export failures;
  - a PowerShell master open.
- `docs/remotion-studio.md`, `docs/remotion-render.md`, `docs/remotion-source.md` and `docs/presentation-studio.md`: no « planned » master
  wording is left.
- `docs/ARCHITECTURE.md`: the row now reads Core, Level 3.
- `docs/mcp/tool-contract.md`: Slices 08 and 09.
- `docs/remotion-integration-release.md`: contract index row, and the export lines are qualified.
- Task `docs/05-documentation-levels.md`: the reality table.

A grep finds no unqualified « one scene per export » or « Studio serves only the selected scene ». The Variants composition clock is
documented as compatibility playback, separate from the master Remotion Composition (§ 0 of the contract, `presentation-studio.md`).

## 6. Reused canonical implementations

- The guarded render host (`render-host.cjs`, `render-guard.cjs`, deny proxy, Chrome sandbox), with its queue, browser slot, cancellation,
  restart recovery and budgets.
- The managed `remotion studio` runner (`sync_work`, process guard, port, idle stop) and the scene unpublished-edit machinery
  (`modified_work`, `work.files.json`, `studio-edits/`).
- The per-source isolation guard and `refused_imports` / `resolve_relative`.
- `parse_source`, the snapshot packager and the frozen package format.
- `merge_props` (extracted from the render plan).
- The Artifact service (`presentation_video`, `rendered_from`).
- The scene-lane Studio door and dialog of Variants, and `error_surface`-style reporting.

No parallel planner exists: Studio, render, UI and agent all read `MasterProjectReader.live_plan` or the frozen plan.

## 7. Residual risks and known limits

- **R1 — fixed in `7fb66c82`** (the line says « Core injoignable : l'état de Remotion Studio n'est plus confirmé. », both doors disabled until Core answers). Original finding: during a Core outage, the Variants Remotion Studio line keeps its last words (« … est ouvert sur la vidéo
  entière … »). Core's stop actually closed the Studio. The page-level notices « Core injoignable » / « Rail injoignable : l'état affiché
  n'est plus confirmé » are visible, and the line clears once Core is back. `doorModel` ignores `readError` except for
  `remotion_studio_unavailable`, in the scene lane too (behaviour of the previous task). Proposed follow-up: mark the line « non confirmé »
  while `readError` is set.
- **R2 (minor, inherited render runner):** the render host reports `sandbox_launch_failed` for any browser launch failure. A
  `JARVIS_REMOTION_RENDER_BROWSER` pointing to a non-Chrome program is therefore said as `presentation_render_sandbox_unavailable`, with
  advice to turn the sandbox off. OPERATIONS now says to check the path first. A launch/sandbox split in the host is follow-up work.
- **R3 — fixed in `7fb66c82`** (no « Réessayer » for `master_scene_failed`, `composition_mismatch`, `job_too_large`, `output_too_large`; the scene is named; `.jvx-vx-code` wraps). Original finding:
  - a failed master render caused by a throwing scene offers « Réessayer », although a retry fails the same way;
  - the small-print code line of `.jvx-vx-code` is cut at the panel's right edge at 1280x720 (see `throwing-scene.png`).
- **R4:** a Studio action that arrives while the status read holds the service lock gets a transient 409 `remotion_studio_busy`. The page
  retries through its own poll; the harness retried once per run.
- **Issue 01:** the loader-bypass fix at the per-source guard narrows text. The word `require` and ASCII `\u` escapes are refused, even in
  displayed text. The authoring guidance says so.
- **Issue 02:** the master failure marker takes the first match. A scene that calls `cancelRender` itself can be attributed to the wrong
  scene id (label only).
- **Issue 03:** the explorer autoplay was dropped by the `d101d887` merge into main (6 inherited failures). This needs a Human decision.
- **Textual detections:** `<Audio` / `<Html5Audio`, `getInputProps` and the loader rules are checked textually. An aliased `<Audio>`
  import skips the audio-stream requirement, and a computed `getInputProps` name escapes the planner check. The per-source isolation guard
  stays the boundary.
- **Master cap:** `MAX_MASTER_RENDER_FRAMES = 9000` (5 min at 30 fps). Longer variants are refused `master_too_long`, and the scene export
  stays available.
- **One-scene Board export:** a single-scene snapshot keeps the scene export body byte for byte (no `scope`).
- **Variants export without `authorised_boards`:** a variant whose scenes read a live Board file is refused `live_ref_not_authorised`.
  Export it from the Board's Artifacts.
- **No master publish-back, no master Player** (phase C).

## 8. Data, migration, rollback

- **No migration:** `git diff d101d887..HEAD` changes no `_SCHEMA_VERSION`, `sqlite_state.py`, `sqlite_scene.py` or `tests/schema/`.
  No Presentation or Variant document field changed.
- **New on-disk state** (all under the data root's Remotion capability):
  - `runtime/studio/work/` with the master layout;
  - `runtime/studio/state.json` schema 2 for a master target;
  - `studio-edits/<timestamp>/` for edits set aside after confirmation;
  - render job folders with the master layout;
  - `presentation_video` Artifacts carrying `render_scope`.
- **Rollback:** close Studio, copy any modified master workspace files out of `runtime/studio/work/` (or set them aside through the scene
  door), and move `runtime/studio/state.json` aside, never deleting it. An older Core reads schema 2 as `remotion_studio_state_unreadable`.
  Nothing else needs a downgrade (`docs/OPERATIONS.md` › *Studio Remotion optionnel*).

## 9. Human checks (after the user restarts their own Jarvis on this branch; no agent restarts it)

These are filled in the Slices' `human-validation.json`:

| Check | What it covers |
| --- | --- |
| HV-RMP-05-01 | Native Studio on the whole video: meaning and usability |
| HV-RMP-07-01 | Spoken workflow: create, export, edit, re-export |
| HV-RMP-08-01 | Variants entry points: wording and prominence |
| HV-RMP-09-01 | Final acceptance: the master project in Studio, the exported MP4 by eye and ear, and the old Variants path |

HV-RMP-00-01 is not needed: no Human decision arose during the task. The only open Human decision is Issue 03, which predates the task.
