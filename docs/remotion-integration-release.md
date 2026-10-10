# Remotion integration - release report, acceptance status and contract index

Status: **Slice 22 (QA, migration, performance and final Human sign-off)** of the handoff `jarvis-remotion-presentation-integration`, run on branch
`task/jarvis-remotion-presentation-integration-s22` (base `fb50c34f`: Slices 00-21 merged, `origin/main` unmoved since `de7b9c59`). This page says,
without rounding up, what the machine proved on this head, what only a person can prove, what is measured, what is open, and where each contract
lives. It sits beside the Studio report ([presentation-studio-release.md](presentation-studio-release.md), the old checks `H-1` to `H-11` stay there
and are **not** repaid here). Nothing in it is inferred from another document: every figure was produced by a run named in the *Evidence index*.

Environment of every measurement below: Windows 11 Pro 10.0.26200, Intel Core i7-12700H (20 threads), 16 GB RAM (about 4.5 GB free during the runs),
a disk at 97 % use (14 GB free), Node v24.18.0, npm 11.16.0, Chrome 154.0.8037.99, Python 3.14.6, Remotion 4.0.534 with React 19.3.0. **Windows and
Chrome 154 are the only combination ever exercised.** The user's live Core, Control Center and voice were never started, stopped or touched: every
real run used an isolated Core on free loopback ports with a throw-away data root.

## Verdict

- **Machine side: green, and no release blocker of ours is open.** The wide regression (all of `tests/unit`, `tests/integration`, `tests/e2e`, in
  foreground chunks) ended with only the failures of `BASELINE.md` (not ours, not fixed) and flakes that pass alone; the 15 opt-in real-runtime
  Remotion test files and the real-runtime harnesses (install, isolation, render, Player, Studio, migration, latency) pass against a private, freshly installed Remotion runtime. Exact counts: *What a machine proved*.
- **The two release blockers named by the Slice are verified, not claimed.** No fallback: no code path plays HTML for a Remotion document and no
  agent or MCP path selects an engine (`tests/unit/test_remotion_no_fallback_privacy.py`, `test_remotion_release_faults.py`, the migration probe).
  Privacy boundary: the sinks (HTTP, TCP, UDP, WebRTC) received nothing from the hardened Player and render paths in a real browser, **one channel is
  open and named** (`dns-prefetch` / `preconnect`, Player and Studio), and no committed file of the handoff keeps a home path, a user name, an address or
  a token (a sweep that found and fixed real leaks, below).
- **The end-to-end journey found three real defects, all fixed here**: the export of every authored deck failed (the render did not hand the composition
  its `data` input), the Studio work copy had the same flaw, and the engine card used a function called `confirm` that tripped the "no browser dialog"
  scan of the page. See *Defects found by this Slice*. None of them could be seen by the unit suites of the Slices (each tested its own piece).
- **Not accepted yet: the physical acceptance.** Real voice cues and audible presenting, a real projector or second screen, the Studio and the export
  played by a person, the quality of a first draft, and the **Remotion licence decision**. *Human checks* orders them. A person must also restart Core
  and the Control Center (*What the Human must restart*); nothing here did.
- **Not done, said once**: the real-model authoring and voice traces were not re-run in this Slice (they cost money; the traces of Slices 15 and 21 stand,
  with their fingerprints checked by the gate); macOS and Linux were never run; no real Core of the user, real microphone, speaker or second screen
  was involved.

## Slice status (handoff folder numbering)

Commits are the merge commits on the integration branch (`git log --first-parent de7b9c59..fb50c34f`); test counts are the number of tests collected
today in the Slice's own files, opt-in real-runtime tests included (they skip without `JARVIS_REMOTION_RUNTIME_DIR`).

| Slice | Subject | Status | Merge | Tests of the Slice (collected on this head) |
| --- | --- | --- | --- | --- |
| 00 | Project manager readiness | done | `163784b2`, `7648eba5` | READINESS in `slices/00-project-manager/` |
| 01 | Final-head conformance, measured baseline | done | `9f363475` | `BASELINE.md` (17 reds, not ours) |
| 02 | Engine semantics, forced default, no fallback | accepted | `0328007b` | engine 59, engine_docs 2, engine_tools 4 |
| 03 | Local capability host | accepted (rework) | `c085b267`, `14e6045f` | local_capability_host 80 |
| 04 | Remotion one-time provisioning | accepted (rework) | `11fea74a` | node_capability_runner 62, process_tree 14, lifecycle 8, routes 21 |
| 05 | Scene source contract, compile | accepted (rework) | `a87e82b1` | source 81, store 26, compiler 35, compiler_real 16, docs 6 |
| 06 | Source isolation | accepted (rework) | `a4b39d46` | isolation 229, isolation_real 1, sandbox_protocol_js 16, docs 7 |
| 07 | Source vs terminal Artifacts | accepted | `16735568` | presentation_artifacts 43, docs 6 |
| 08 | Board registration, derived provenance | accepted (rework) | `33694eac` | board_discovery 12, workspace_presentations_js 23 + browser 2 |
| 09 | Live references, immutable freeze | accepted (rework) | `a1dcc6b6` | live_refs 49, freeze 39, docs 3 |
| 10 | Player host, engine gate | accepted (rework) | `dcfa565d` | player 17, stage_js 26, sandbox_server 5, routes 9, relay 28, wiring 8, gate_call_sites 8, realpage 7 |
| 11 | Optional Studio process and card | accepted (rework x2) | `493c3604` | studio 42, rework 42, runner 22, guard 19, routes 19, cc 26, origin_ports 8, docs 10, real 1 |
| 12 | Score to Remotion timeline | accepted (rework) | `a556decd` | timeline 17, service 12, composition 3, js 22, child_js 8, realpage 2 |
| 13 | Typed controls bridge | accepted (rework) | `508e9044` | input_props 53, controls 42, docs 5, realpage 1 |
| 14 | Source edit, hot reload, agents | accepted | `4f2eb982` | source_edit domain 27, service 36, routes 2, docs 5, real 1, realpage 1 |
| 15 | One-shot authoring | accepted (rework) | `8659cb45` | authoring_remotion 77, browser 3, real 6 |
| 16 | Render, MP4, still, PDF | accepted (rework) | `5827d510` | render domain 47, service 58, runner 42, render_guard 10, routes 23, relay 8, docs 13, real 2 |
| 17 | Semantic prefab catalog | accepted | `2995b81c` | prefab_catalog 60, browser 1 |
| 18 | Upstream template import | accepted (rework) | `e7100b75` | upstream 123, import 71, service 29, docs 7, real 2 |
| 19 | Promotion, pins, upgrades | accepted (rework) | `122fdcfe` | template_remotion 32, template_score 16, upgrades 17, routes 9, docs 6, explorer js 8 + browser 3 |
| 20 | Engine UI policy, Slidecar experiment | accepted (rework) | `0c8cb339` | engine_human 38, migration 9, card js 11 + browser 4 |
| 21 | Voice verbs, `jarvis-remotion`, tool ownership | accepted (rework) | `174afff7` | mcp_tools 40, server 18, ownership 6, docs 4 |
| 22 | End-to-end release gate | **this page** | this branch | release_flows 1, release_faults 19, no_fallback_privacy 25, release_gate, studio_data 2, render_domain +2 |

## What a machine proved

### Wide regression on this head

Command: `python -m pytest -p no:cacheprovider -q --no-header -rfE <files>`, foreground, chunks of about 40 files (20 or 10 for the slow browser files),
the three `JARVIS_*` shell variables of the agent environment unset, no `JARVIS_LIVE_*` opt-in, the repository venv. Raw logs are not committed (they hold
local paths); the table is the record. 
The last full pass ran on head `87bfe0d4` (every product change of this Slice already in; the evidence runs of the next section ran on `b667b25b`, which
differs only by evidence files, the `verify_release` regex fix and the gate test). Baseline for "inherited" is
`slices/01-final-branch-conformance/BASELINE.md` (`de7b9c59`: 711 files, 19 087 passed, 17 failed, 50 skipped).

| Suite | Files | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| `tests/unit` | 729 | **20 683** | **15** (all in `BASELINE.md`) | 68 |
| `tests/integration` | 76 | **650** (+1 on rerun) | 2: one in `BASELINE.md`, one flake that passes alone | 26 |
| `tests/e2e` | 1 | 1 | 0 | 0 |
| **Total** | **806** | **21 334** (+1) | **17** (16 inherited, 1 flake) | 94 |

(The baseline said 79 integration files; `git ls-tree` of `de7b9c59` lists 76, as today: the baseline's count was a miscount, its 651 passed matches.)

Every failure, classified (the numbers are those of `BASELINE.md`):

| Test | Class |
| --- | --- |
| `test_app::test_the_control_center_receives_a_tools_gateway_target_built_from_core_settings` (#1) | inherited |
| `test_barehands_interaction_js` x2 (#2, #3) | inherited |
| `test_brain_capability_parity::...documented_in_the_brain_prompt` (#4) | inherited (`ui_intent_publish`) |
| `test_brain_delegation::...starts_with_the_rule...` (#5) | inherited |
| `test_control_center_voice_architecture::test_async_browser_render_does_not_restore_a_previous_panel` (#6) | inherited |
| `test_interaction_mode_hud_browser::test_le_mouvement_reduit_arrete_vraiment_le_halo` (#7) | inherited |
| `test_scene_artifacts::...byte_identical` (#9), `test_scene_query_tools::...byte_identical` (#11), `test_scene_group_drag_js` (#10) | inherited |
| `test_tool_brain_choices::...single_metadata_copy` (#12), `test_tool_brain_intents` x3 (#13 to #15) | inherited (Tool Brain `ui_intent_publish` channel) |
| `test_wake_word_settings_browser[cosmos]` (#16; the file takes 8.7 minutes alone) | inherited |
| `integration/test_settings_redesign_migration` (#17) | inherited |
| `integration/test_conversation_event_rollout_gate` | **flake, not ours**: the planted private value `4242` is a substring of a random event id (`cev-424248b0...`); passes alone (4 s) |

`BASELINE.md` #8 (`test_memory_context`, flaky) did not fail this time.

The first pass of the same suite, run before the fixes of this Slice, found what the last pass no longer shows: 2 reds that were **ours** (the engine card
`confirm` and the inspector loop bound, fixed, defects 3 and 4) and 3 failures that pass alone, classified as load-sensitive flakes, not fixed:
`test_presentation_studio_crash` (the kill-a-writer drill left a `*.tmp` once or twice in four runs; `file_presentation_studio_store.py` is byte-identical to
`main`), `test_presentation_studio_reload_browser::test_a_good_edit_reloads_only_the_affected_frame...` (23 pass alone in 4 minutes) and the
`conversation_event` id collision above.

### Real-runtime tests (opt-in) against the freshly installed private runtime

`JARVIS_REMOTION_RUNTIME_DIR` pointed at a runtime installed for this run (`scripts/remotion_install_harness.py`, below). Each file run alone.

| File | Tests | Result | Duration |
| --- | --- | --- | --- |
| `test_remotion_compiler_real.py` | 16 | pass | 8 s |
| `test_remotion_isolation_real.py` | 1 (13 hostile samples x direct/evasive, real Chrome) | pass | 445 s |
| `test_remotion_player_realpage_browser.py` | 7 | pass | 82 s |
| `test_remotion_controls_realpage_browser.py` | 1 | pass | 12 s |
| `test_remotion_timeline_realpage_browser.py` | 2 | pass | 68 s |
| `test_remotion_source_edit_real.py` | 1 | pass (after fixing the test, below) | 6 s |
| `test_remotion_source_edit_realpage_browser.py` | 1 | pass | 22 s |
| `test_remotion_studio_real.py` (real `remotion studio`) | 1 | pass | 92 s |
| `test_presentation_render_real.py` (export clicked in a real Control Center) | 2 | pass | 60 s |
| `test_remotion_import_real.py` (real GitHub, `JARVIS_REMOTION_IMPORT_NETWORK=1`) | 2 | pass | 19 s |
| `test_presentation_studio_authoring_remotion_real.py` | 6 | pass | 3 s |
| `test_presentation_studio_authoring_remotion_browser.py` | 3 | pass | 28 s |
| `test_presentation_studio_player_realpage_browser.py` | 5 | pass | 38 s |
| `test_presentation_studio_reload_real_page_browser.py` | 2 | pass | 43 s |
| `test_remotion_release_flows.py` (the journey, below) | 1 | pass | 54 s |

### The release journey (real Core, real compiler, real renderer)

`tests/unit/test_remotion_release_flows.py` lives one path on one Core: a brief becomes a 6-scene Remotion deck through the real authoring door and the
real compiler; it plays with its cue armed and a spoken-phrase report moves the run; a props edit changes a value live without republishing; a source
edit is built before it is published, a broken one is refused (`presentation_studio_source_build_failed`, file/line/column) with the pin unchanged, and
the previous source is restored byte for byte; the frozen snapshot is exported as MP4, still image and PDF by the real runner (each checked against its
payload hash, with Chrome's sandbox on); an upstream template is imported (scoped to the deck, provenance recorded) and compiles; a scene is promoted to
the library and a whole presentation as one artefact with nothing added to the shared library; a newer version of a pinned prefab is noticed and tried
in a child variant while the original file stays byte-identical. Measured steps (`evidence/release-journey.json`): assemble 0.6 s, source edit 0.7 s,
broken edit refused 0.17 s, MP4 32 s (first render, includes bundling), still 7 s, PDF 7 s, import 0.14 s, promotions under 0.1 s.

Together with `test_presentation_studio_release_flows.py` / `_release_faults.py` / `_release_gate.py` (the Studio journeys, which already run on
Remotion drafts since Slice 15), the journey proves one-shot authoring, play with cues, live edit, source edit with rollback, freeze, export,
import, explicit promotion and a newer-version trial.

### Fault injection: every fault ends in a typed, visible state, never in Slidecar

`tests/unit/test_remotion_release_faults.py` calls every door that could put something on the stage against a real Core with Remotion not installed
(all playback verbs in the three roles, the preview edit, the source edit, the render, the Studio, an agent naming Slidecar) and asserts a typed
refusal each time, an empty scene, an idle run, no Slidecar document, no `slidecar_*` event; and again after a Core restart (the document is still
`remotion`). Its table `FAULTS` maps every fault of the brief to its typed state and to the test that proves it (the test must exist). Real-runtime
reruns of the faults on this head (`evidence/`):

| Fault | Typed, visible state | Real evidence on this head |
| --- | --- | --- |
| Runtime missing | `presentation_studio_engine_unavailable` (409) + repair text; stage window says so | `player/runtime_missing_api.json`, `runtime_missing_window.json`, `unavailable.png` |
| Compile error | `presentation_studio_source_build_failed` (422) with file:line:column; stage shows the compiler message | `player/compile_error.json` + `.png`, release journey step 4b |
| Sandbox killed / frozen scene | watchdog removes the frame ("ne répond plus"), reload offered, stage survives | `player/watchdog_kill_and_reload.json`, `killed.png` |
| Hostile scene | refused by the static guard, contained by the sandbox, 0 hits at the sinks | `real-isolation.json` (44 checks) |
| Render cancelled | `presentation_render_cancelled`, derivative `failed`, no final file, tree gone in 1.3 s | `real-render-faults.json` |
| Render process killed (also Node only: orphan Chrome swept) | `presentation_render_failed`, no final file, nothing left | `real-render-faults.json` |
| Core restarts mid-render | orphan killed, derivative `failed` `presentation_render_interrupted`, no partial promoted, new render works | `real-render-faults.json` (`core_death`) |
| Second Core on the same data | `presentation_render_locked`, first Core's renders untouched | `real-render-faults.json` (`two_cores`) |
| Render bounds (time, size, disk) | killed with the stated limit | `real-render-hostile.json` |
| Chrome cannot start with its sandbox | `presentation_render_sandbox_unavailable`, never retried unsandboxed | `real-render-hostile.json` |
| Studio crashed or vanished | `failed` view with code and log, "Relancer" recovers; adopted Studio outlives its Core | `real-studio.json`, `real-studio-late.json` |
| Stale source revision | `presentation_studio_stale_revision`, snapshot `failed` | unit (matrix) |
| Agent names an engine | `presentation_studio_engine_selection_refused` (403) | unit + journey |

## Defects found by this Slice

| # | Found by | Defect | Fix |
| --- | --- | --- | --- |
| 1 | the journey (export step) | **The export of every authored deck failed** with `TypeError: Cannot read properties of undefined (reading 'body')` in the render browser: the render started from `props_defaults` + the scene's `props` and never handed the composition its `data` input, which every authored scene reads (`props.data.body`). The Player passes it. Slices 15 (authoring) and 16 (render) each passed their own tests. | the package freezes `data_defaults`, `render_props` adds `inputProps.data` (defaults under the scene's frozen `data`); 2 tests; [remotion-render.md](remotion-render.md), [presentation-artifacts.md](presentation-artifacts.md) |
| 2 | reading the code the journey pointed at | The Studio work copy had the same flaw (`defaultProps` from `sample.props` only). | `prefab_source_provider` adds the sample `data`; `test_remotion_studio_data.py` (unit only: not re-run in a real Studio on an authored deck) |
| 3 | wide regression | The Slice 20 engine card named a local function `confirm`; the page scan "never uses browser dialogs" (`test_scene_interaction_logic`) caught the call shape. | renamed `askConfirmation`; test of the card updated; engine card tests 15 pass |
| 4 | wide regression | `test_control_center_mcp_inspector_js` loop bound (24 releases) was smaller than the catalogue since `jarvis-remotion` (101 descriptors). | bound 64 |
| 5 | real-runtime tests | `test_remotion_source_edit_real` and `_realpage_browser` edited as `brain`, refused since the Slice 21 guard (a brain edit needs a pending user-turn request). | they edit as `user`, like the Control Center relay; the guard keeps its own tests |
| 6 | render harness | The `chrome://sandbox` probe read the table before Chrome filled it (cold browser: "no Renderer", flaky FAIL). | the probe waits up to 15 s for the Renderer rows |
| 7 | studio harness | The check "Fermé à votre demande" took the first `.rms-hint` of the page, which is now the engine card's. | scoped to the hint that contains the text |
| 8 | privacy sweep | `LOG.md`, the Slice 04 and 11 evidence JSON and two test fixtures kept the user's name and home path. | rewritten (`<home>`, `<user>`, a fictitious name); sweep committed and tested |

## Evidence index

All under `tasks/jarvis-remotion-presentation-integration/slices/22-end-to-end-release/evidence/` unless said otherwise. Evidence files record `head`,
`tree_dirty` and the environment; they were produced with the final product code (see *Evidence heads* in the LOG entry of this Slice).

| Evidence | Produced by | What it shows |
| --- | --- | --- |
| `real-install.json`, `perf-*.json` | `scripts/remotion_install_harness.py`, `scripts/remotion_perf_wrap.py` | install time and size; RAM and process count of each run |
| `real-isolation.json` | `scripts/remotion_isolation_harness.py` | 44 checks PASSED: hostile corpus x (direct, evasive), channel counts at the sinks, negative controls and ablations |
| `real-render-happy.json`, `real-render-faults.json`, `real-render-hostile.json` | `scripts/remotion_render_harness.py` | MP4/still/PDF verified by ffprobe, cancel/kill/Core death/two Cores, refusals, bounds, hostile egress, Chrome sandbox probe |
| `real-studio.json`, `real-studio-late.json` | `scripts/remotion_studio_harness.py` | 39 + 10 checks: real `remotion studio`, guard, HMR, UI card, crash, idle, adoption |
| `player/`, `edit/`, `controls/`, `timeline/` | `scripts/remotion_player_harness.py` | Player scenarios (7), source-edit swap latency, controls, timeline bridge |
| `migration.json` | `scripts/remotion_migration_probe.py` | pre-task roots v7 and v8, Core startup, `.bak`, legacy play, old-build behaviour (23 checks) |
| `latency.json` | `scripts/remotion_latency_probe.py` | Core-side cold and warm latencies, folder footprint |
| `release-journey.json` | `test_remotion_release_flows.py` | timed steps of the journey |
| `privacy_sweep.py` | `test_remotion_no_fallback_privacy.py` | the sweep of the handoff and of the Remotion documents, scripts and tests outside it |
| `trace-analysis.md` | `agent-trace-analysis` over the committed traces | what the traces of Slices 15 and 21 do and do not cover |
| Earlier evidence | Slices 04-21 `evidence/` folders | per-Slice real runs (older heads; superseded by the runs above where both exist) |

## Contract index

One row per contract. Docs are in `docs/`; `tests/unit/test_remotion_release_docs.py` checks that every document and test file named here exists.

| Contract | Slice | Document | Guarding tests |
| --- | --- | --- | --- |
| Engine semantics, default, no fallback, human-only selection | 02, 20 | `presentation-engine.md` | `test_presentation_studio_engine*.py`, `test_remotion_no_fallback_privacy.py` |
| Local capability host | 03 | `local-capabilities.md` | `test_local_capability_host.py` |
| Remotion install, health, repair | 04 | `remotion-runtime.md` | `test_node_capability_runner.py`, `test_remotion_lifecycle.py` |
| Scene source, manifest v2, compile | 05 | `remotion-source.md` | `test_remotion_source.py`, `test_remotion_compiler.py` |
| Source isolation, sandbox, Player protocol | 06, 10, 12, 13 | `remotion-isolation.md` | `test_remotion_isolation.py`, `test_remotion_stage_js.py` |
| Source vs terminal Artifacts, Board discovery | 07, 08 | `presentation-artifacts.md`, `artifacts.md`, `boards.md` | `test_presentation_artifacts.py`, `test_presentation_board_discovery.py` |
| Live references, freeze | 09 | `presentation-live-refs.md` | `test_presentation_live_refs.py`, `test_presentation_freeze.py` |
| Optional Studio | 11 | `remotion-studio.md` | `test_remotion_studio*.py` |
| Hot reload, timeline, typed controls, authoring, templates, upgrades | 12, 13, 14, 15, 19 | `presentation-studio.md` | `test_remotion_timeline*.py`, `test_remotion_controls.py`, `test_remotion_source_edit_service.py`, `test_presentation_studio_authoring_remotion.py`, `test_presentation_studio_upgrades.py` |
| Render and export | 16 | `remotion-render.md` | `test_presentation_render_service.py`, `test_render_guard.py` |
| Semantic prefab catalog, manifest v3 | 17, 19 | `prefabs.md` | `test_prefab_catalog.py` |
| Upstream import | 18 | `remotion-import.md` | `test_remotion_upstream.py`, `test_remotion_import.py` |
| Agent verbs, ownership | 21 | `mcp/tool-contract.md` (10.17), `tool-brain-contracts.md` (19) | `test_remotion_mcp_tools.py`, `test_remotion_mcp_server.py` |
| Security | 06, 11, 16, 18, 20 | `SECURITY.md` (18 to 20) | the isolation, studio and render guards above |
| Data layout | all | `local-data.md` | `test_schema_migrations.py` |
| Release gate (this page) | 22 | this page | `test_remotion_release_flows.py`, `test_remotion_release_faults.py`, `test_remotion_no_fallback_privacy.py`, `test_remotion_release_gate.py` |

## Operator runbook

Everything below acts on the user's machine only when the **user** asks; no agent starts, stops or restarts Core, the Control Center, the voice or the
Studio (the agent tools return where to click). Detail and PowerShell recipes: [OPERATIONS.md](OPERATIONS.md), sections "Capacité locale Remotion",
"Studio Remotion optionnel", "Édition de source", "Export d'une présentation", "Isolation du code", and "Remotion : release de bout en bout (Slice 22)".

1. **Before the first use of this build**: copy `<data root>/presentations/` and `<data root>/prefabs/` somewhere safe (see *Migration and rollback*:
   a variant saved by the new build has no backup of its previous bytes).
2. **Install, once**: Control Center, Plugins externes, card "Présentations · moteur" or the Remotion card, **Installer Remotion** (or `POST
   /v1/local-capabilities/remotion/install`). Needs Node >= 20, npm >= 9, about 1.5 GB free, `registry.npmjs.org`. Measured here: 37 s, 258 MB on disk.
   A second install is a no-op. Core start never downloads anything.
3. **Repair**: `repair` reinstalls from the shipped lock when `repair_needed` / `install_failed` / `install_interrupted`; `health` probes; `uninstall`
   empties `runtime/` and leaves every source and asset untouched. After a Jarvis update that changes `runtime-host.mjs` the card says
   `shipped_files_changed`: repair.
4. **Enable / disable the Studio**: the Studio is a separate, optional process: **Ouvrir le Studio** (explicit confirmation: the scene runs without the
   sandbox and the Studio's API can send source and props off the machine), **Fermer le Studio**, automatic stop after 30 minutes without a window
   (`JARVIS_REMOTION_STUDIO_IDLE_S`, 60 to 86400 s), fixed port with `JARVIS_REMOTION_STUDIO_PORT`. The capability itself is `disable` / `enable` on the same
   route family. Only open it on a scene you know.
5. **Export**: Board, Artefacts view, under a frozen copy, "Exporter cette copie" (MP4, image, PDF). One scene per export (`settings.scene_id` when a
   deck has several). Needs Chrome or Edge installed (`JARVIS_REMOTION_RENDER_BROWSER` to name one; one is never downloaded) and 1.5 GB free. The PDF is
   flat page images. Chrome runs with its process sandbox ON; `JARVIS_REMOTION_RENDER_NO_SANDBOX=1` is the explicit opt-out for a machine that cannot
   create it. Retention: the 20 newest renders of a snapshot keep their files.
6. **Import an upstream template**: only on the user's request, only from GitHub with a full commit SHA, only from an allowed owner: the list is
   `remotion_import.allowed_owners` in `control-center-settings.json` (default `remotion-dev`, re-read at every import; the official `remotion-dev`
   templates are `UNLICENSED` and are refused, so the default imports nothing until an owner is added). Licence and dependencies are audited; the result
   is private to the presentation until promoted.
7. **Choose Slidecar** (experiment): card "Présentations · moteur", zone "Expérimental : Slidecar", confirmation. The engine of a document never changes;
   old documents stay Slidecar and keep playing.
8. **Read a failure**: every state is typed and shown (card, stage window, export panel): `engine_unavailable` -> install/repair; `source_build_failed` ->
   the diagnostics name file:line:column; `render_*` codes in `remotion-render.md` section 8; Studio `remotion_studio_*` in `remotion-studio.md` section 4.
9. **Replay the proofs** (isolated, never the live profile): the commands are in the headers of `scripts/remotion_*_harness.py`,
   `remotion_migration_probe.py`, `remotion_latency_probe.py`, `remotion_perf_wrap.py`; the opt-in tests need `JARVIS_REMOTION_RUNTIME_DIR=<runtime/>`.

## Performance

Measured on the machine above, with `scripts/remotion_perf_wrap.py` (working set of the whole process tree, sampled every 2 to 3 s; working set counts
shared pages once per process, so it is an upper bound on the footprint, not private memory) and the probes in `evidence/`. One run each unless said:
the numbers show the order of magnitude on this machine, not a benchmark.

| Measure | Result | Documented bound |
| --- | --- | --- |
| Install, once (fresh `npm ci --ignore-scripts`, 297 locked packages) | 36.8 s in the install harness; 24 to 53 s in the four other fresh installs of this Slice's runs (earlier Slices: 17.6 to 43 s); a second install 0 s | "about 270 MB", "1.5 GB free" required |
| Disk of the runtime | 258 MB in 15 299 files (`node_modules` 204 MB, npm cache 53 MB) | about 270 MB |
| Player cold start, Core side (compile `host.js` + `scene.js`, empty cache) | 0.77 s (three runs: 0.76, 0.77, 1.47) | scene compile limit 60 s, host 120 s |
| Player warm (cache hit) | 0.03 s | - |
| Props edit round trip while playing (`playback/edit`, `control.set`) | median 0.04 to 0.06 s (n=5 per run, max 0.07) | - |
| Source edit, warm (build `scene.js`, publish, repin) | median 0.65 to 0.77 s (n=5 per run, max 0.79) | 60 s compile, 75 s wait behind another edit |
| Source edit to new pixels in a real page (frame swap, no page reload) | 0.18 to 0.44 s (`edit/source_edit_hmr.json`) | - |
| Studio cold start (`remotion studio` ready) | 48.7 s and 65.3 s (two runs; 30 to 50 s documented, so the upper end is exceeded under load) | 120 s start timeout |
| Studio HMR after a scene sync | sync call 0.14 s, visible 0.93 s | - |
| Render MP4 (60 frames 720p h264, 2 s) | 12.6 s alone; 32 s as the first render of a cold journey | job limit 600 s |
| Render still / PDF (3 pages) | 7.3 s / 8.1 s alone; 7.2 s each in the journey | - |
| Peak RAM and processes, render (Core-less runner, Chrome + ffmpeg + node) | 1 355 MB, 15 processes | one render at a time (concurrency 1, at most 2) |
| Peak RAM and processes, Core + Studio (no browser of ours) | 951 MB, 8 processes | - |
| Peak RAM and processes, Studio harness with a Chrome for the card | 2 235 MB, 31 processes | - |
| Peak RAM, isolation harness (Chrome, hostile corpus) | 1 140 MB, 17 processes | Chrome heap cap 512 MB per probe |
| Peak RAM, release journey (Core, compiler, renders) | 1 312 MB, 18 processes | - |
| Output sizes of the test scene | MP4 24.7 KB, PNG 26 KB, PDF 54 KB | MP4/still/PDF bounds in `remotion-render.md` |
| Compile cache / data root after the journey | `compiled/` 570 KB (the shared host bundle is 567 KB), `runtime/` small files 149 KB | cache prune at 64 entries or 1 GiB |
| Render job folders | cleaned at the end (a few KB of `job.json`, `render.log`, `result.json`, `egress.json` stay) | retention 20 renders per snapshot |
| Studio work copy | the scene's `src/` and `public/` only; the webpack cache is erased at each launch; at most 5 saved-edit folders | `MAX_SAVED_EDITS` 5 |

Reading: nothing exceeded a documented limit (timeouts, caps); one expectation was exceeded once (the Studio cold start, 65 s against the 30 to 50 s the docs expect, limit 120 s). The cold render is dominated by bundling and the browser start. The Studio's 49 to 65 s cold start is the largest
wait a person sees; the card shows a live counter and a way out. Peak figures include the harness's own Chrome where noted.

## Migration and rollback

`scripts/remotion_migration_probe.py` builds two throw-away "before the task" data roots from the committed fixtures (a `jarvis.sqlite3` at schema 7 and
the same at schema 8 with rows, a `scene.sqlite3` at schema 1, four presentations with manifests v1 and v2 and variants v1 to v4 with HTML scenes, a
user HTML prefab, a score and an art direction), starts a real isolated Core on each, and records (`evidence/migration.json`, 23 checks PASSED):

- **No schema change**: `jarvis.sqlite3` stays at 8 and `scene.sqlite3` at 1 in this task. A root already at 8 starts with no migration and no
  `.bak`; the old v7 root migrates to 8 with exactly one backup `jarvis.sqlite3.v7.bak` (old schema 7, old row counts) and loses no row. No
  `_MIGRATIONS` step was added by this task; the new Artifact kinds are values of an existing text column.
- **Legacy presentations are read as `slidecar` and still play** (an HTML prefab on the stage), nothing is converted, no presentation file or
  prefab file changed byte for byte by reading and playing them. The Slidecar usage ledger stays at 0 until a Slidecar document is used.
- **A brand-new document is `remotion`** and, with no runtime, is refused at play with `presentation_studio_engine_unavailable` (409): never replayed
  as HTML.
- **Rollback, said honestly.** What the new build writes and the build before it (`main` `de7b9c59`, extracted from git and run on a copy) does with it:
  - A presentation **saved** by the new build is rewritten as manifest schema 3 and variant schema 5; the old build **refuses both**
    (`presentation_studio_unsupported_schema_version`: "reads up to 2" / "up to 4"). Documents never saved by the new build still read in the old one.
  - The first save keeps `presentation.json.v2.bak` (the old manifest bytes). **A variant keeps no backup of its previous bytes** (Issue 05): to go
    back, restore `presentations/` from the copy taken before first use.
  - A database holding **new Artifact kinds** (`presentation_snapshot`, `presentation_video`, `presentation_still`, `presentation_pdf`) opens in the old
    build, but its Artifact query **fails** on those rows (`kind is not a ArtifactKind`): the old build cannot list Artifacts until those rows are
    removed. Rolling back after a freeze or an export needs that database restored from before.
  - So: **a roll-back is safe only if nothing was saved, frozen or exported by the new build, or if `state/` and `presentations/` are restored from a
    copy made before.** The `jarvis.sqlite3.v7.bak` style backups exist only for SQLite migrations.

## No fallback and privacy boundary

**No fallback (verified).** The engine is a durable, immutable field of the document (legacy = `slidecar`, new = `remotion`). The scene gate refuses the
other engine's scenes in both directions (409 `engine_unsupported`, nothing stored). The names of the Slidecar engine in `jarvis/` are an enumerated list
of 7 files, none inside an error handler, and `resolve_engine` reads only the asked engine. No tool of any of the 11 declared MCP servers exposes an
engine, an actor, an experiment or a fallback parameter, and Core refuses an agent that names an engine, even the default, or forges a human
(`test_remotion_no_fallback_privacy.py`, `test_remotion_release_faults.py`, the player runs above: 0 `iframe[srcdoc]` for a Remotion window). The
only way to a Slidecar document is a human action with an explicit confirmation, and it never converts or substitutes.

**Privacy boundary (verified where claimed, with the open channel named).**

| Path | What was measured (real Chrome, sinks listening on loopback) | Verdict |
| --- | --- | --- |
| Player sandbox (`127.77.0.2`, `sandbox="allow-scripts"`, CSP) | `fetch`, XHR, WebSocket, beacon, image, CSS `url()`: 0 requests at the HTTP sink; WebRTC: 0 UDP packets with the hardening, 10 without (negative control sees the leak); storage, cookies, parent access, navigation: blocked | closed |
| Player sandbox, `dns-prefetch` / `preconnect` link hints | 1 TCP connection and 29 DNS lookups reached the sink even with every layer on (`X-DNS-Prefetch-Control`, meta, CSP, `allow=""` have no effect) | **OPEN, best effort** |
| Render (Chrome behind the render guard) | local HTTP service 0 requests, TCP sink 0, UDP sink 0 on fetch, XHR, WebSocket, beacon, image, CSS, `preconnect`, WebRTC; denied requests are counted on the derivative (`render_egress_denied` 13 to 51 per honest render: browser noise); negative control without the guard: sinks receive traffic | closed on this machine |
| Studio (`remotion studio` + in-process guard) | listens on `127.0.0.1` only; child processes, DNS, UDP refused by the guard; the Control Center refuses its origin; **the scene runs in the Studio tab without the Player's sandbox and on the Studio API's origin** | **not a sandbox**: explicit confirmation required |
| Upstream import | one HTTPS host family, redirects never followed blindly, archive and decompression bounded, commit echo checked | owner allowlist, not commit reachability (Issue 04) |

`data` and props: everything given to a scene (props, `data`, theme, live Board copies placed under `public/live/`) is **readable by the scene's code**.
The closed channels stop it leaving; the open one (`dns-prefetch` / `preconnect`) lets a hostile scene encode low-bandwidth data (a few hundred bytes)
in a hostname it asks the browser to resolve. So: put no secret in a scene's props or `data`; live references are limited to Boards the user authorised
and are refused by default; a note a person wrote into a Board is copied as is (the protection covers Jarvis secrets and paths, not what a person typed).
Secrets and paths: no committed file of the handoff, its documents, scripts or tests keeps a home path, a user name, an address or a token (a
sweep). The 88 screenshots of the evidence
are not readable by that sweep and were not reviewed one by one.

## Residual risks

Consolidated from the Slices; none waived, none repaid by this one.

1. **Sandbox and egress limits.** `dns-prefetch` / `preconnect` are open on the Player and the Studio (best effort); WebRTC is removed by a prelude
   inside the scene's own frame (best effort, a scene that regains the API is outside it); no OS-level sandbox; Chrome 154 on Windows only.
2. **The Studio is not a sandbox** (same origin as its API, no frame sandbox); its guard is JavaScript inside the process (native modules,
   `process.binding` and non-JavaScript code are outside it). A scene the user knows runs there as them.
3. **Guards are filters, not walls**: the static source guard and the authoring lint are pattern based and bypassable by construction; the
   frontier is origin + frame sandbox + CSP (Player) and the process guard (render, Studio).
4. **Render**: Chrome runs with its process sandbox on, but the network service is outside it on Windows; the Node render guard is JavaScript;
   one scene per export; a PDF is flat images; an MP4 is not byte-reproducible across machines; a render of a scene with live Board data does not
   announce that data to the scene; audio never listened to.
5. **Attested-turn limits (Slice 21)**: the attestation says "a user turn is in progress", not that the user's sentence asked for the gesture; a
   sub-agent that the brain launches on its own with the token could still call the source-edit route (the prompt forbids it; Core refuses a brain
   edit without a pending request, not a sub-agent that forges one).
6. **The token holder can claim any actor**: the actor is declared, not authenticated; the same-origin header check on engine selection is an
   occasional-access barrier, not a boundary.
7. **Provenance**: an import proves a SHA echo, not reachability from the branch (Issue 04); licence detection is text matching, not legal advice; an
   asset has only the repository's licence.
8. **Rollback** is partial after any save, freeze or export (above); variants keep no `.bak`.
9. **Platforms**: Windows 11 and Chrome 154 only; macOS and Linux never run; Edge never exercised for renders.
10. **Memory and disk**: working sets of 1 to 2.2 GB (Studio with a browser) during a render or a Studio run on a 16 GB machine with 4.5 GB free; a render wants 1.5 GB free.
11. **Quality is a person's judgement**: a first draft passes a gate floor (64 rules), real-model traces show 1 gate round per scenario, but whether a
    deck is presentable is `H-12`; the reduced-motion preference is not judged for Remotion scenes.
12. **Remotion's licence is unexamined** (below).
13. **The wide regression carries 15 inherited reds** that predate the task (listed in `BASELINE.md`) and several load-sensitive browser tests that pass
    alone (listed below).

## Human checks

Ordered. Each one needs a person at the real workstation and cannot be replaced by anything above. The old Studio checks `H-1` to `H-11`
([presentation-studio-release.md](presentation-studio-release.md)) **stay open and are not repaid**; the ones that overlap are marked.

| # | When | Check | Id | Why a machine cannot |
| --- | --- | --- | --- | --- |
| 0 | before anything | Copy `presentations/`, `prefabs/` and `state/` of the data root; decide the **Remotion licence** (below) | HV-22-02 | a business decision; the rollback needs the copy |
| 1 | after the restarts | Install Remotion from the card, read the states, try the repair, confirm the install UX differs clearly from remote MCP plugins | HV-03-01 | the user's network and judgement of the UX |
| 2 | | Play a real Remotion scene in a real Jarvis scene, windowed then fullscreen **on the real second screen or projector**, Escape restores the workspace | HV-10-01, H-1 | window placement, permission prompt, the display |
| 3 | | Say a real presentation with the microphone: the cues follow the spoken phrases, the pause/recovery behave | HV-12-01, H-3 | the ambient stack and the room |
| 4 | | Hear Jarvis present a locked sequence; PRESENTATION mode stays silent unless addressed | H-4, H-5 | nothing here produces sound |
| 5 | | The spoken verbs: "installe Remotion", "exporte en MP4", "ouvre le Studio sur la deuxième scène", "passe en Slidecar": only the first two start visible work, the Studio waits for your click, the engine does not change | HV-21-01 | the real voice and brain |
| 6 | | Open the Studio beside Jarvis, edit, close without losing live edits; read the confirmation dialog | HV-11-01 | window management, feel |
| 7 | | Export an MP4, an image, a PDF from a Board copy; **play the MP4 with sound if the scene has any**, open the PDF, follow "Ouvrir la source" back | HV-16-01 | sound and reading were never done by a machine |
| 8 | | Ask the agent for a real deck on your own brief; judge layouts, colours, motion; edit the accent from the inspector | HV-15-01, H-12 | a first draft being respectable is a person's judgement |
| 9 | | Browse the prefab shop (taxonomy, parameters), promote a deck, compare a newer version, try it in a variant | HV-17-01, HV-19-01 | usability |
| 10 | | Confirm the source appears as the parent in the Board manager | HV-07-01 | UX |
| 11 | | The engine card: normal Remotion, an intentional Slidecar experiment, a visible failure with no automatic fallback | HV-20-01 | judgement of the wording |
| 12 | last | **Full dry run** on the intended installation: spoken edit, scene preview, Board assets, export | HV-22-01, H-9 | the acceptance criterion of the Slice |

Left open, not repaid: `H-2`, `H-6` to `H-8`, `H-10`, `H-11` of the Studio report (inspector feel, rehearsal recall by voice, explorer legibility, compare/mix,
screen reader and reduced motion, toasts in fullscreen).

## What the Human must restart

Nothing was restarted, started or stopped by this Slice. After merging, **the user** restarts, in this order:

1. **Core** (it carries the routes `local-capabilities`, `remotion/render`, `remotion/imports`, `presentation-studio/templates`, `.../upgrades`,
   `.../source-edits`, the engine gate, the render and Studio runners, the importer). No SQLite migration is expected on a database already at schema 8
   (measured: none); on an older database the automatic `.v<old>.bak` backup is made.
2. **The Control Center** (cards, the stage document `/remotion-stage`, the export panel, the engine card, the new relays).
3. **The brain session / agent** so it receives the new `jarvis-remotion` MCP server (declared with `jarvis-presentation`; 6 tools, 5 178 bytes of
   context) and the new prompt step.
4. **The voice** only if it is restarted together with Core by the user's own procedure; the voice code did not change in this task.

Then install Remotion explicitly (it is never installed by starting Core).

## Remotion licence

**Unexamined, and a decision for the Human.** Remotion's licence depends on who uses it and how (its public pricing page, to re-read, describes a
company licence for some organisations); the repository records it as a separate constant (`catalog.runtime_license`, never deduced from a template's own licence) and
every import and promotion shows it, but nobody here has read it against this installation's use, nor the licences of the npm packages in the 297
locked entries (`jarvis/capabilities/remotion/package-lock.json`). The official `remotion-dev/template-*` repositories are `UNLICENSED`, which is
why the default import allowlist imports nothing. **Do not distribute or sell an installation that bundles Remotion before the licence is read and a
decision is recorded.** Sources: <https://www.remotion.dev/docs/license/pricing>, <https://www.remotion.dev/docs/license/faq>.

## Known issues

[Issues/](../tasks/jarvis-remotion-presentation-integration/Issues/): 01 inherited debt of the Studio task, 02 local capability wiring (closed by Slice 04 for the
host, the Control Center card exists), 03 prefab library overflows at 360 px, 04 commit reachability of imports, **05 (opened here)**: a first save keeps
no backup of the variant it rewrites.
