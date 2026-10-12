# Slice 09 evidence — retire the legacy floating presentation viewer

Base `1793ad6e`. Commits: `1bb798c0` (Core), `bf676045` (page, MCP), `cd1a7815` (release gate), `ece92dc3` (browser proofs, docs),
`5bedcf7c` (regression fixes), `5870c17b` (one « Arrêter »). Final code: `5870c17b`.
Everything ran in headless Chrome through the test harnesses, on isolated Cores (free loopback ports, throw-away data roots), with the
read-only Remotion gate runtime. The live Jarvis was never started, stopped or contacted; its trace and scene base were read from copies.

Contract: `docs/presentation-studio.md` › *Variants run surface (Level 3, Slice 09)* (UI ownership / retirement map, Level 3
conformance, limits). Human recipe: `docs/OPERATIONS.md` › *Une présentation dans Variantes … (HV-RFX-09-01)*.

## 1. Inventory of the old viewer's entry points and where each went

Old locations are the audit's (`slices/00-project-manager/blind-audit.md` § 7, `slices/01-…/AUDIT.md` § 2) at `1793ad6e`; new owners
are at `5870c17b` (line numbers moved by at most a few lines in the last two commits).

| Entry point / capability (old file:line) | Migration target (new file:line) | Proof |
| --- | --- | --- |
| Run stage Board window `studio-stage-<run_id>` begin/show/release/retire (`core/presentation_studio_stage.py:44-276`, `playback.py:748,879,823,815,1016`) | memory surface `RunSurface` `variants-run-<run_id>` (`core/presentation_studio_run_surface.py:67`, `begin :154`, `show :158`, `release :179`) mounted by Variants | `test_presentation_studio_run_surface.py`, `_playback_service.py::test_start_shows_one_stable_run_surface_and_next_patches_it_without_any_board_object` |
| Band `#jvStudioBand` (`player.js:215-263`), its buttons and keys (`player.js:568-653`), item clock | presenter strip `.jvx-presenter` + Variants transport (`control_center_presentation_studio_explorer.js:1664 renderRun`, `:1695 buildPresenter`); model `control_center_presentation_studio_run.js:136 presenterModel`, keys `:191 keyCommand` | `test_presentation_studio_presenter_js.py`, `test_variants_run_js.py`, `test_variants_run_browser.py`, `test_presentation_studio_presenter_browser.py` |
| Band poll / `JarvisStudioPlayer.view/command/startRun` (`player.js:40-46,492-498,701`) | playback client without DOM (`control_center_presentation_studio_player.js`) | `test_presentation_studio_player_js.py` |
| Band fullscreen + fullscreen `onNavigate` (`player.js:249,395,628-655`; `fullscreen.js:158-163,445-461`) | Variants stage fullscreen (`F`, header « Plein écran ») | `test_variants_run_browser.py::test_f_puts_the_variants_stage_in_fullscreen…` |
| Window host `JarvisPresentationWindow` (`control_center_presentation_window.js`, whole file) — « Jouer », « Studio », ◀ ▶ | **deleted**; rail opens Variants (`control_center_presentation_rail.js:82-84` « Ouvrir les variantes » / « Présenter ») | `test_control_center_presentation_rail_js.py`, `test_variants_run_surface_docs.py` (file gone, no page code builds it) |
| Explorer « Jouer cette slide / Tout jouer » that closed the explorer (`explorer.js:489-512`) | « Présenter ▾ » in Variants (`explorer.js:1765 startPresenting`); a run never closes Variants | `test_variants_run_js.py::test_presenter_starts_a_run_here…`, `test_presentation_studio_explorer_browser.py::test_a_run_shows_in_variants…` |
| Rail menu « Jouer » (`rail.js:416-421,445`), rail auto-focus (`rail.js:357-369`) | « Présenter » (rail starts a run, Variants hosts it); auto-focus retired | `test_control_center_presentation_rail_js.py` |
| Scene page timeline/segment bridge + `swapPrefix` (`scene_page.js:1757-1809`) | `JarvisVariantsRun.createRunAdapter` (`run.js:32`) on the Variants host (`autoplay:false`, `embed:'variants'`, `swapPrefix`) | `test_variants_run_js.py`, `test_remotion_timeline_realpage_browser.py` |
| Scene page draws `studio_stage` / `studio_aux` | never drawn (`control_center_scene_layout.js:46,1718` `RETIRED_CATEGORIES`) | `test_variants_run_js.py`, realpage proofs (`board:false`) |
| MCP `presentation_play start` (`mcp_tools.py:706-764`) | opens Variants via the explorer channel; no visible page → paused + `surface_unavailable` (`mcp_tools.py:781-801`) | `test_presentation_studio_mcp_ops.py::test_a_start_is_shown_in_variants…`; § 4 below |
| MCP `presentation_view stage_fullscreen_enter` (`mcp_tools.py:622-629`) | opens Variants on the run, arms `studio-explorer-stage` (`mcp_tools.py:631`) | `_mcp_ops.py::test_stage_fullscreen_needs_a_run…` |
| MCP `presentation_view window_open/close` → rail screen requests (`mcp_tools.py:610-656`, `core/presentation_studio_rail.py:48,336-366`) | explorer open/close windowed with the page's receipt (`mcp_tools.py:615,619`); rail `UI_ACTIONS` = show/hide rail only (`rail.py:50`), display-state `variants_open` (`rail.py:345-348`) | `_mcp_ops.py::test_window_ops_open_and_close_variants…`, `test_presentation_studio_rail.py` |
| MCP `presentation_inspect playback` `stage_object_id` | keeps its name, carries `variants-run-<run_id>`; view adds `surface {id, rev}`, `timeline_unresolved` | `_playback_routes.py`, `_run_surface.py::test_the_view_names_the_surface…` |
| Prompt (`claude_local.py:186-191`) | rewritten: a run shows in Variants, `surface_unavailable` said (`claude_local.py:186-191`) | `test_presentation_studio_mcp*` prompt checks |
| Voice cue follower (`cue_follower.py:325`) / Jarvis presenter (`presenter.py`) | unchanged (they move the run, the surface follows) | `_release_flows.py`, `_presenter_routes.py`, presenter browser |
| Hot reload binding (`reload_stage.py:48-132`, `playback.py:958-977`, page `reload.js:215-239`) | `StageWindows(surface)` reads / compare-and-set repins the surface (`reload_stage.py`); page mount report from the Variants host | `test_presentation_studio_reload_{integration,service,routes,crash}.py`, `test_presentation_studio_reload_real_page_browser.py` |
| Scene-variant preview on the stage (`preview.py:39-109`) | shown on the run surface (`preview.py:39 show_preview`, `show(…, scene_id=)`) | `test_presentation_studio_scene_variants_playback.py` |
| `scene_variants.bind_playback` (`v2_app.py:499`) | unchanged binding (`v2_app.py:510`) on the new playback | same |
| Pins protection (stage scene as pin source, `v2_app.py:455,518`) | pins source `variants_run` = `RunSurface.pins()` | `_run_surface.py::test_overlays_…pinned` |
| Detours / aux windows `studio-aux-*` (`playback.py:987-1008`, `stage.py:252-276`) | overlays inside the Variants stage (`run_surface.py:187 stage_aux`, `:203 reveal_aux`, max 8) | `_playback_service.py::test_stop_in_the_middle_of_nested_detours…`, `test_variants_run_js.py::test_the_adapter_mounts_overlays…` |
| Frame events of the stage window (prefab events) | `PrefabEventService(surface=)` writes the surface; host `posts(objectId)` | `test_variants_run_js.py::test_the_runs_frame_posts_its_events…` |
| Tool Brain guard on `studio_stage`/`studio_aux` (`tool_brain_executor.py:120-176`) | kept as a reservation of the retired categories (`tool_brain_executor.py:131 LEGACY_CATEGORIES`) | `test_tool_brain_studio_ownership.py` |
| Ledger + reclaim (`stage.py:77-157,290-306`; ledger file) | `LegacyStageReclaimer` (`stage.py:102,109`) at start and before each run; ledger read then kept aside `.retired-<ts>`, unreadable `.corrupt-<ts>` | `test_presentation_studio_stage.py` (7) |
| `STUDIO_STAGE_PREFIX` unused (`explorer_core.js:49,625`) | deleted | — |

## 2. Persisted state migration

Only one persisted artefact belonged to the viewer: the stage ledger `<data_root>/state/presentation-studio-stage-ledger.json`, plus
any `studio_stage` / `studio_aux` objects an older Core left in `scene.sqlite3`. No schema change (no migration step): the
`LegacyStageReclaimer` archives (never deletes) leftover objects through the scene's normal archive path, by ledger id and by a
namespaced scan (`studio_stage` + `studio-stage-*`, `studio_aux` + `studio-aux-*`, bounded), then keeps the ledger aside as
`.retired-<UTC>`; a foreign or corrupt ledger is kept aside as `.corrupt-<UTC>` and said (error row), never read as empty. A refused
archive is said and never blocks a run. `rail.json` and `jarvis.presentationRail.v1` held no viewer state.

Live check (read-only copy of the live `scene.sqlite3` + `-wal` + `-shm`, 2026-10-12): 0 `studio_stage`/`studio_aux` objects, 0
tombstones, 0 history rows; no ledger file. The first start of the new Core on this PC is a no-op reclaim.

## 3. Defects fixed, each with its regression test

| Defect | Fix | Test |
| --- | --- | --- |
| Finding 7 (Slice 07): the stage host played its own grace play before Core's order, then Core's order replayed the entry (78 → 0) | host `autoplay:false`, `embed:'variants'`: nothing plays before Core's order (impossible by construction); whole-scene timeline in every run | `test_variants_run_js.py::test_finding_7…` (node, real host), release gate `finding7_next_by_core_route_in_variants` (real Chrome, `gate/finding7_next_by_core_route_in_variants.json`: one order, first play at frame 0) |
| Stuck show: a stage sync that never resolved held the lock, so even `stop` waited | bounded sync `STAGE_SYNC_TIMEOUT_S`=20 → `stage_timeout` (run pauses, said); `stop` pre-empts a sync in flight → `stage_preempted` | `_run_surface.py::test_a_show_that_never_resolves…`, `::test_a_stop_pre_empts_a_sync…` |
| `rs-bar` / play-on-ready on the run stage | the run no longer uses the Board stage page; the Variants host never plays on ready | `test_variants_run_js.py`, gate `presenter_entry_reveals_anchor_S2.json` |
| A run started from the explorer closed the explorer | Variants hosts the run; another presentation is refused `explorer_run_in_progress` | `test_presentation_studio_explorer_browser.py::test_a_run_shows_in_variants…` |
| Hot reload during an entry replayed the entry | reload repins the surface by compare-and-set; the mount report comes from the Variants host; the run is not paused nor replayed | `test_presentation_studio_reload_integration.py`, `test_presentation_studio_reload_real_page_browser.py` (only the run frame replaced, user windows untouched, bad edit rolled back) |
| Sound / keys of the band (keys only on the stage host, `P`/`Échap` pause) | one key map (§ 4.15 « Presenter run » column) on the Variants stage; `F`, `M`, `Échap` are Variants' | `test_variants_run_browser.py` (keys once each, other fields untouched, fullscreen, Échap closes and pauses) |
| Stale surface after a Core restart with no run | `start_service` releases a surface no run owns | `_run_surface.py::test_core_start_releases_a_surface_no_run_owns…` (mutant without the release: fails) |
| Release gate xfail `a_presenter_run_scrubber_is_read_only` | read-only slider in run mode | release gate (xfail removed, passes) |

## 4. Agent-trace analysis (MCP routing changed)

**Live traces.** `runtime/trace.jsonl` of the live Jarvis (copy read on 2026-10-12; 70 022 rows, 2026-09-03 → 2026-10-09): no
`presentation_play`, `presentation_view` or `presentation_inspect` call and no `studio_stage` / `studio-stage-*` object anywhere (the only
presentation rows are `voice.speech.presentation_decided` 923, `core.brain.presentation_delivered` 125, `presentation.runtime.*` 8, which
belong to the voice presentation runtime and are untouched). The live usage therefore cannot regress through these verbs, and there is
no live call to compare with: flagged for agent 0 — the first real voice/MCP presentation after merge should be traced (HV-RFX-09-01
step 3 produces one).

**Real Core traces of the changed verbs** (`agent-trace-mcp-routing.json`): the `jarvis-presentation` tools against a real isolated Core,
the Control Center answering like the page:

| Verb | Result | What went to the page |
| --- | --- | --- |
| `presentation_view window_open` | `opened` (windowed) | one `POST /explorer/commands {action: open, fullscreen: false}`; no rail screen request |
| `presentation_play start rehearsal` | `applied`, `surface: variants` | `GET explorer/state`, attested user turn, one explorer `open` on the run's variant; `stage_object_id` = `variants-run-…`; Board objects: none |
| `presentation_view stage_fullscreen_enter` | `needs_gesture` (said) | explorer `open` then `fullscreen enter {object_id: studio-explorer-stage, keys: none}` |
| `presentation_play next` / `stop` | `applied` | nothing (the page follows Core's view) |
| `presentation_view window_close` | `closed` | explorer `close` |
| `presentation_play start` with no visible page | `surface_unavailable`, run `paused` | explorer `open` answered 504 `explorer_no_visible_page` |
| `explorer_open` of another presentation during a run | `explorer_run_in_progress` (typed, cause in words) | explorer `open` refused by the page |

No redundant call (one page request per verb, none for transport verbs), no retry loop, every refusal typed with its cause. Core's own
playback diagnostics are in memory in this rig (its `runtime/trace.jsonl` holds 3 boot rows); the Core-side kinds are proven by the
Core tests (`legacy_stage_reclaimed`, `stage_ledger_*`, `stage_timeout`).

## 5. Real-runtime evidence (headless Chrome)

- `gate/` — release gate on `5870c17b`: 14 passed with `-k "not play_all_shows"` (236 s), play-all passed first try (90 s);
  `play_all.json` (9 scenes hosted in Variants, no Board stage), `presenter_S3.json` (read-only scrubber),
  `presenter_entry_reveals_anchor_S2.json`, `finding7_next_by_core_route_in_variants.json`.
- `screens/` — before (`1793ad6e`: a run in a Board window `studio_stage` under the floating band) and after (`5870c17b`: the same
  run inside Variants, presenter strip, no Board window, no band) at 1280x720; `screens/SHA.txt` says how each was made.
- `agent-trace-mcp-routing.json` — § 4.

## 6. Decisions

- Detours render as overlays inside the Variants stage — **decided by agent 0 (Human delegated autonomy)** (AUDIT § 9 recommendation,
  LOG 2026-10-11).
- Rail auto-focus retired, no auto-opening full-page surface — **decided by agent 0 (Human delegated autonomy)** (AUDIT § 9, LOG
  2026-10-11); Slice 11 designs the indicator.
- « Ouvrir le Studio » removed from the rail (it duplicated Variants once the window was gone) — follows AUDIT § 5 (window host
  removed); Slice 11 adds « Remotion Studio… ».
- **Flag for agent 0:** the Tool Brain guard is kept as a reservation of the retired categories instead of being dropped (AUDIT § 2.1
  said "drop with the category"): an older Core's leftover objects stay protected until reclaimed. Deviation from the audit.
- **Flag for agent 0:** closing Variants during a playing run pauses it (never stops it, never reopens Variants by itself). Not in the
  contract text before Slice 09; now documented.
- **Flag for agent 0:** Variants is a modal dialog, so the interaction-mode HUD is under it while a run shows (the old band left it
  clickable). The strip never overlaps it; closing Variants gives it back. Documented in *Limits*.
- **Flag for agent 0 (Slice 15):** `rs-bar` still exists on generic Board Remotion windows (not presentation runs).
- **Flag for agent 0:** a run started by a direct Core call with no page action waits for the page's next poll (≤ 5 s at rest) before
  Variants opens; voice/MCP open it at once.
- **Flag for agent 0 (Slice 10):** during a run the explorer's actions (« Activer », « Brancher d'ici… », « Renommer… ») are inert but not
  visibly dimmed (after screenshot); the tree is inert too. Control audit.
- One « Arrêter » during a run: the transport's (it stays in the stage fullscreen); the strip's duplicate was removed after the
  after-screenshot showed two.
- Test change: the anchorless-scene realpage case now expects a whole-scene timeline (Variants never self-plays); the continuity
  realpage case accepts a handover within the follower's `END_SLACK_FRAMES` (2) for non-final scenes (the next scene, preloaded in
  Variants, takes over at once; seen flaky 1 run in 3 before the change), the last scene must still hold 149.

## 7. Human check — HV-RFX-09-01

Recipe: `docs/OPERATIONS.md` › *Une présentation dans Variantes (native-studio-playback-fix Slice 09) : vérification humaine
(HV-RFX-09-01)*. Short form, after the user restarts Jarvis themselves:

1. Click a presentation in the left rail: Variants opens windowed. No floating window, no band at the bottom.
2. Rail right-click › « Présenter » (or Variants « Présenter ▾ » › « Vous présentez »): the run plays inside Variants; the presenter
   strip under the video says who presents and where; the slider does not move under the mouse.
3. Say « présente <nom> » (voice): Variants opens on it (windowed); no window appears on the Board.
4. → ← Début Fin Espace act once each; `F` fullscreen shows only the slide; Échap leaves fullscreen, Échap again closes Variants and
   the run pauses.
5. « Arrêter »: the video is yours again; nothing remains on the Board.
6. Confirm the screenshot-1 experience (floating viewer + band) never appears.

## 8. Tests

Regression across the presentation / Remotion domain, one file per process, fresh data root each (`test_presentation*`,
`test_remotion*`, `test_variants*`, `test_prefab_host*`, `test_continuous_sequencing*`, `test_scene_variant*`, every file naming
`presentation_play` / `studio_stage`, `test_control_center_presentation*`, `test_tool_brain_studio*`, `test_fullscreen*`,
`test_scene_layout*`, `test_mcp_catalog*`): 274 files, 6 638 passed, 5 skipped in the batch run at `ece92dc3`. Failures in that
batch and what became of them:

| File | Batch | Cause | Now |
| --- | --- | --- | --- |
| `test_control_center_presentation_rail_browser.py` | 13 errors | harness scripted the retired window | retargeted, 13 passed |
| `test_presentation_rail_e2e_browser.py` | 1 failed | window host, « Studio » menu entry | retargeted, 3 passed |
| `test_variants_transport_browser.py` | 3 failed | « Présenter » made the row overflow at 800x600 (a real defect) | CSS fix, 5 passed |
| `test_remotion_release_flows.py` | 1 failed | read the Board stage | reads the run surface, 1 passed |
| `test_remotion_player_realpage_browser.py` | 1 failed | band fullscreen, click-in-frame sound, preloaded frame counted | Variants « Plein écran » / « Son », shown frames; 7 passed |
| `test_remotion_release_docs.py` | 1 failed | report named the deleted band proof | report annotated, 4 passed |
| `test_presentation_studio_reload_browser.py` | 1 failed | load (passes alone, 2/2) | 23 passed in br runs |
| `test_presentation_attention_browser.py::test_ecarter_l_avertissement_n_emet_aucune_requete` | 1 failed | Chrome's lazy `/favicon.ico` between the marks | **pre-existing flake**: 2/4 failures at `1793ad6e` too; not fixed |
| `test_presentation_studio_explorer_upgrades_browser.py::test_the_zone_tells_the_newer_version…` | 1 failed | activation picks another variant | **pre-existing**: fails at `1793ad6e` too; not touched (Slice 10 control audit) |
| `test_remotion_isolation_real.py` | interrupted | the batch was reaped for low memory (orphans stopped) | 1 passed alone |

Retargeted earlier in the Slice and green: `test_presentation_studio_explorer_browser.py` 18, `_inspector_browser.py` 16,
`_presenter_browser.py` 2, `_reload_real_page_browser.py` 2, `test_remotion_timeline_realpage_browser.py` 2,
`test_remotion_continuity_realpage_browser.py` 1, `test_presentation_continuous_playback_browser.py` 2, `test_variants_run_browser.py` 6,
`test_variants_run_surface_docs.py` 4, `test_presentation_experience_contract_docs.py` 9, `test_presentation_studio_playback_docs.py` 9,
`test_presentation_studio_run_surface.py` 10. Release gate: 14 + 1 passed on `5870c17b`.

The 16 inherited failures of `slices/00-project-manager/READINESS.md` are outside this list and were not touched.
