# Slice 01 — Independent intent vs implementation audit

- **Branch / HEAD audited:** `task/jarvis-remotion-native-studio-playback-fix` at `a8377529` (= `origin/main` `d2332e61` + the S0 handoff mirror). Worktree `brn`.
- **Builds on:** `../00-project-manager/blind-audit.md`. Its owner map was spot-checked and holds (every file:line cited below was re-read at `a8377529`). This document only covers the gaps the blind audit left.
- **Nothing here was runtime-reproduced.** "code-read" = mechanism proven by reading the code, not observed in a browser. Live Jarvis was not started, stopped or queried.
- Paths are relative to the repo root; `runtime/` = `jarvis/runtime/`.

---

## 0. Where the screenshots come from (changes how to read them)

| Fact | Evidence |
| --- | --- |
| Both screenshots show the presentation rail and « Jouer cette slide » / « Tout jouer ». | `evidence/*.png` |
| Neither exists in this host's live checkout (`main` = `df642ce5`): no `control_center_presentation_rail.js`, 0 hits for « Jouer cette slide » in the Explorer. | `git show df642ce5:…` |
| They arrive with `0a5adaaf`/`4288e735`/`55039c2d`/`d2332e61` (2026-10-10 21:03–21:13), authored under a **different git identity** than this host's, and pushed to `origin` — this host's `main` never pulled them (reflog). | `git log df642ce5..d2332e61`, `git reflog main` |
| No Jarvis Core/Control Center is listening on this host now (ports 17653/17654 free). | `Get-NetTCPConnection` |

**Conclusion:** the screenshots were taken on the machine (or checkout) that produced those commits, running **at least** `4288e735`, **plus code that was never pushed**. Screenshot 1's Board even shows that machine's agents working on the player at the time (« Corriger l'UI du lecteur… », « Diagnostic : la vidéo ne… », « Assembler les 7 clips en… »). Any element absent from `d2332e61` must be treated as unpushed local work, not as a product owner.

---

## 1. Owner of every visible control and time indicator

### 1.1 Screenshot 2 — Variants screen

| # | Visible element | Owner (file:line) | Notes |
| --- | --- | --- | --- |
| 1 | Left rail « PRÉSENTATIONS », items, ○ ◉ ‹ | `runtime/control_center_presentation_rail.js` | uppercase via CSS |
| 2 | Title « Variantes », subtitle « … · 1 variante » | `runtime/control_center_presentation_studio_explorer.js:278` | |
| 3 | « Fenêtré » mode chip | `explorer.js:395,400` | |
| 4 | « Plein écran » (top) | `explorer.js:285,403` → fullscreen of the Explorer host | 1st fullscreen control |
| 5 | « Fermer » | `explorer.js` top bar | |
| 6 | « ÉVOLUTION 1/64 », tree row `#1 … ACTIF`, hint « ↑ ↓ → ← parcourir · … » | `explorer.js:300-319`, `explorer_widgets.js` tree | |
| 7 | « Archivées (0) » | `explorer.js:307-317` | |
| 8 | Preview frame (scene image) | Explorer preview prefab host `mode:'preview'`, `explorer.js:597-607`, mount `:716` → `runtime/control_center_prefab_host.js:632-682` → `/remotion-stage` page → sandbox Player `runtime/remotion_sandbox_child.js:116-121` | remounts per slide (no `swapPrefix`) |
| 9 | **Inner bar inside the frame**: « Lecture » toggle, scrub slider, faded `x.x s / 30.0 s · Son coupé…` | `runtime/control_center_remotion_stage.js:118-131` (build), `:440-449` (text; `toFixed(1)`), `:127` (scrub → local `seek` only), redraw every 500 ms `:477` | transport #1. « Lecture » label = Player **paused** (`:444`) |
| 10 | ‹ › scene prev/next | `explorer.js:333-334` (`browseScene`) | |
| 11 | Scene title « Mode Présentation : slides, variantes, export » | `explorer.js:335,725` | |
| 12 | « Scène 6 sur 9 » | `explorer.js:339,730` | |
| 13 | « Jouer cette slide » / « Tout jouer » | `explorer.js:341-344`, handler `:489-512` | both start a **manual** rehearsal (no `scope`), then close the Explorer → floating stage appears |
| 14 | **Lower transport row**: `\|◀ ◀◀ ▶ ▶▶ ▶\|`, progress bar, `6/9 · 2 s / 8 s`, « 8 s par slide » selector, loop/repeat, fullscreen, hint « → suivante · ← début · ←← précédente · Espace lecture · F plein écran » | **UNKNOWN — not in any code reachable from this host.** See §1.3. | transport #2 (screen-only); its ▶ shows paused and the inner Player is paused at ~2.6 s too, so it [inferred] drives the preview Player |
| 15 | Scene strip `01 … 09` (06 selected) | `explorer.js:346-347`, `:736-754` | |
| 16 | `#1 JARVIS en diapositives…`, « Racine de l'arbre », « Créée hier par Jarvis », « 9 scènes » | `runtime/control_center_presentation_studio_explorer_widgets.js:511` (and neighbours) | |
| 17 | Chips « Variante active », « Partition liée », « Diaporama net… · générée » + swatches | `explorer_widgets.js:536,548` + art-direction palette | |
| 18 | « first draft (directed) » | variant note, `explorer_widgets.js` meta | |
| 19 | « Activer », « Brancher d'ici… », « Renommer… », « Archiver… » | `explorer.js:562` (actions), `:350` toolbar | |

Time indicators on screen 2: **three**, from three owners: inner `x.x s / 30.0 s` (#9, composition length), lower `2 s / 8 s` (#14, unknown — a per-slide dwell), and none from Core (Explorer previews never talk to playback).

### 1.2 Screenshot 1 — floating viewer

| # | Visible element | Owner (file:line) | Notes |
| --- | --- | --- | --- |
| 1 | Board window « STUDIO_STAGE », title « Vue d'ensemble : de la parole à l'action » | Board window category `studio_stage`, id `studio-stage-<run_id>`: `jarvis/core/presentation_studio_stage.py:44,50,194-240`; header `runtime/control_center_scene_page.js:1721`; uppercase by CSS `.sc-cat{text-transform:uppercase}` `scene_page.js:857` | blind audit's "[inferred]" now confirmed |
| 2 | Scene inside it + inner bar « Lecture » / scrub / faded time | same as 1.1 #8-#9 but host = scene page prefab host `scene_page.js:1757-1809` (with `swapPrefix`, `onLive`, `onClock`) | « Lecture » = Player paused while the band says « En cours » |
| 3 | Band header « Vous présentez » + « En cours » | `runtime/control_center_presentation_studio_player.js:56-57` | |
| 4 | `00:10 / 00:15` | `player.js:363-366` (item elapsed / `item_target_ms`, mm:ss, local 1 s tick) | transport #3 clock = score item, not media |
| 5 | « Scène 3/9 · … — élément 5/16 » | `player.js:342` | |
| 6 | « Élément · vous », « Ensuite : … » | `player.js:360-362` | |
| 7 | Orange « Suivi vocal indisponible : … » | `player.js:106` (`FOLLOWER_ABSENT`) | |
| 8 | ◀ Précédent, Pause, Suivant ▶, ▶ Slide, ▶▶ Tout, Plein écran, Arrêter | `player.js:241-252` | « Sortir de la séquence » `:250`, « Fermer » `:253`, « Ouvrir l'explorateur de variantes » `:255` are conditional |
| 9 | Hint « ← → Espace : naviguer · P ou Échap : pause · Début / Fin · S : … » | `player.js:259` | keyboard capture `:568-653` |
| 10 | Rail, Board, mode box « PRESENTATION », dock | rail / Board / mode modules (out of scope) | |

### 1.3 The lower transport row of screenshot 2 — search record

Owner: **unknown; not present in any code on this host.** Searched (all negative):

- Plain and escaped strings (« par slide », « Espace lecture », « ←← », « ← début », `\u2190\u2190`, `perSlide`, `per_slide`, `dwell…`) over the whole worktree incl. docs, tests and the handoff folder.
- `git log --all -S'par slide'` / `-S'Espace lecture'`: no commit ever added them.
- 164 unreachable commits (`git fsck --unreachable`), every fetched remote ref, and `refs/pull/7/head` (fetched for this audit; the only remote ref not yet local).
- `jarvis/runtime` of every other worktree on this host (read-only grep).
- The live instance data root under `~/.jarvis/instances/` (text and binary grep: no prefab, scene, or stored HTML carries the strings).
- Google Drive search: only the screenshot itself matches.

Positive evidence that it is foreign to `d2332e61`:

- Its keyboard semantics contradict the Explorer's: the hint says `←` = « début » (restart the slide) and `←←` = previous; the Explorer's `onSceneKey` (`explorer.js:774-784`) maps `←` to *previous scene* and handles neither Space nor F.
- Its DOM position (between the scene line `note` and the `strip`) is not built by `explorer.js:321-354` (`vbar, wrap, note, strip, bottom, upgrades`).
- No "global seconds per slide" setting exists anywhere: the only per-item time is the score's `target_duration_ms` (blind audit §2).

**Plan impact:** Slices 04 and 10 must not try to "fix" or "remove" this row in code — there is none at `d2332e61`. The product decision (Slice 02) should state explicitly that a deck-level dwell selector and its second transport must not exist. **Open question for the Human:** confirm which machine and code took screenshot 2, and whether that unpushed work should be discarded (recommended) or pushed for review.

---

## 2. Client inventory — floating viewer and presentation window

### 2.1 Run stage window (`studio_stage`, `studio-stage-<run_id>[-<n>]`) + band `#jvStudioBand`

Defined in `jarvis/core/presentation_studio_stage.py` (`:44,50,179,218`; reopened under a new generation if the user closes it, `stage_closed` after 3 reopens `:213-227`). Band built at `player.js:215-263`; API `window.JarvisStudioPlayer` `player.js:701-702`. **The band is used by any active run only** (voice, MCP, rail, window, Explorer); after a run it stays as a "stopped" notice with « Ouvrir l'explorateur de variantes ».

| Client | file:line | Unique capability it needs from the stage | Migration target |
| --- | --- | --- | --- |
| Playback run lifecycle (begin/show/release/retire) | `core/presentation_studio_playback.py:748,879,823,815,1016` | one stable, patched (not recreated) surface per run | Variants embedded Player bound to the run |
| Score reveals / anchor overlay | `playback.py:603-606,858-886` | **a visible surface where anchor reveals render** | same Player, reveal = frame seek / prop |
| Edits during a run (inspector/undo) | `playback.py:1102-1108,1137-1147` | repaint of the visible scene | Player props refresh |
| Detours / aux windows `studio-aux-*` | `playback.py:987-1008`, `stage.py:252-276` | a second hidden-then-revealed Board window | **open decision** (Variants overlay or keep aux as Board windows) |
| Ledger + reclaim after Core crash | `playback.py:216-225,780-791`; `stage.py:77-157,290-306` | on-disk id ledger | remove with the stage; ledger file becomes dead data |
| `stage_object_id` in the view | `playback.py:287,1214`; protocol `:93-111` | a Board object id every client can target | replace with a Variants surface id (or drop) |
| Presenter (Jarvis presents) | `core/presentation_studio_presenter.py:420-431,577,718` | indirect (via `playback.notify`) | unchanged; renders through the Player |
| Voice cue follower | `runtime/presentation_studio_cue_follower.py:436` | indirect (Core applies cue) | unchanged |
| Scene-variant preview on stage (paused run) | `core/presentation_studio_preview.py:39-66,96-109`; `presentation_studio_scene_variants.py:134-144` | show an in-memory scene on the run surface, then restore | Player shows preview pin, then restores |
| Hot reload | `core/presentation_studio_reload_stage.py:48-132`; `playback.py:958-977`; `reload.py:578,628-631,769,866`; page `control_center_presentation_studio_reload.js:215-239` | object id → scene binding + mount-outcome waiter | rebind to the Variants Player's frame id (**riskiest coupling**) |
| Pins protection | `core/v2_app.py:455,518-519` | stage scene as a pin source | rebind to the Player's mounted pins |
| Tool Brain guard | `tool_brain_executor.py:120-152,174-176` | category `studio_stage`/`studio_aux` = refused to the brain | drop with the category |
| Document hygiene | `domain/presentation_studio_checks.py:22`; `presentation_studio_template_sanitize.py:54` | forbids stage handles in documents | keep regex until legacy data is gone |
| Band keyboard capture | `player.js:568-653` (filter on `data-object-id`) | host keyboard (sandbox relays no keys) | Variants Player keyboard (one map) |
| Band fullscreen / fullscreen `onNavigate` | `player.js:249,395,628-646,654-655`; `control_center_fullscreen.js:158-163,445-461` | object id for fullscreen + nav keys | Variants preview fullscreen (one button) |
| Scene page timeline/segment bridge | `scene_page.js:1757-1809`; `player.js:435-444,562-566`; `remotion_frame.js:164-167` | drives/preloads that frame | becomes the single Player adapter (Slice 04-06) |
| Generic Board menu → fullscreen | `scene_page.js:3235-3251` [inferred applies to stage] | — | disappears with the window |
| MCP `presentation_view stage_fullscreen_enter` | `runtime/presentation_studio_mcp_tools.py:622-629`; schema `presentation_studio_mcp.py:190-201`; meta `mcp_tool_meta.py:554-558` | `stage_object_id` | retarget to Variants fullscreen (keep op name or deprecate; MCP contract change) |
| MCP `presentation_play` | `mcp_tools.py:706-765` | the run (not the window) | unchanged |
| MCP `presentation_inspect playback` | `mcp_tools.py:405-414,466-478` | reads `stage_object_id`, fullscreen id | field change |
| Explorer « Jouer… » | `explorer.js:489-512` | starts a rehearsal whose stage **replaces** (closes) the Explorer | play inside the Explorer, never close it |
| Explorer / Inspector / Rail "run active?" guards | `explorer.js:76-79,222-225,1220,1334-1357`; `inspector.js:56-59,1201-1209,1246,1286`; `rail.js:209-216,468` | `JarvisStudioPlayer.view()` + `jarvis:studio-playback` event | keep the run-state API, minus the band UI |
| Prompt | `runtime/claude_local.py:186,191` | text | rewrite |
| Unused | `explorer_core.js:49,625` `STUDIO_STAGE_PREFIX` | none | delete |

### 2.2 Presentation window host (`runtime/control_center_presentation_window.js`, `JarvisPresentationWindow`)

DOM-only non-modal viewer (not a Board object; `data-object-id='jv-presentation-window'` only for fullscreen, `:20,116`). Third preview host (`mode:'preview'`, no `swapPrefix`, `:155-184`) with its own ◀ ▶ / strip / count / « Plein écran » / « Jouer » / « Studio » / « Fermer » (`:119-126`). **It starts runs**: `startRun` posts `/api/presentation-studio/playback/start` directly (`:292-311`) — the shared start route that keeps Core's refusal reason; « Jouer » = `user_presenter`, then closes (`:312-316`).

| Client | file:line | Unique capability | Migration target |
| --- | --- | --- | --- |
| Rail click / « Ouvrir » / « Éditer » | `rail.js:266,391-397,405-415,442` | lightweight viewer of the active variant, refreshed every 5 s | open the Variants screen (Explorer) instead |
| Rail « Jouer » | `rail.js:416-423` | `startRun` with refusal reason | move `startRun` into a shared playback client module |
| Rail auto-focus when an agent works | `rail.js:357-369` | auto-open without stealing | Variants (or a rail-only indicator) — **open decision** |
| Brain screen requests `open_window`/`close_window` | `rail.js:342-355`; MCP `presentation_view window_open/window_close` `mcp_tools.py:610-611,643-656` → `core/presentation_studio_rail.py:48,336-366` | remote open/close | retarget to Variants open/close (MCP contract change) |
| Rail status/visibility/report | `rail.js:211,220-222,256-257,334,380-387,574`; `window.js:273-278` | `pid()`, `jarvis:presentation-window` event (`window_open` in MCP inspect `mcp_tools.py:434-445`) | rename to Variants open state |
| Explorer `playFromStudio` | `explorer.js:499-501` | shared `startRun` | shared playback client |
| Window → Explorer (« Studio ») / fullscreen | `window.js:121,279-288,317-324` | — | gone |
| Prompt | `claude_local.py:187` | « affiche / ouvre X » → `window_open` | rewrite |

**Persisted state:** stage ledger `<data_root>/state/presentation-studio-stage-ledger.json` (`adapters/file_presentation_studio_stage_ledger.py:3,25-29`) is the only persisted artefact of both surfaces. `rail.json` holds only `hidden`/`archived` (`core/presentation_studio_rail.py:5-10,53-58`); localStorage `jarvis.presentationRail.v1` holds rail prefs only (`rail.js:37,173-180`); window position is inline only. Everything else (run, stage id, `StageWindows` bindings, rail screen requests) is memory.

**Tests touching them (≈25 files):** stage/Core — `test_presentation_studio_stage` (10), `_playback_service` (39), `_playback_rework` (16), `_release_faults` (14), `_scene_variants_playback` (10), `_reload_integration` (16) + reload routes/crash/core/service, `test_tool_brain_studio_ownership` (4), `_mcp_ops` (21), `_playback_docs` (9); band — `_player_js` (30), `_player_chain_js` (4), `_player_browser` (4), `_player_realpage_browser` (4), `_presenter_browser` (2), `test_remotion_timeline_js` (22), explorer/inspector tests stubbing `JarvisStudioPlayer.view`; window — `test_control_center_presentation_rail_js` (7), `_rail_browser` (13), `test_presentation_rail_e2e_browser` (3), `test_presentation_studio_rail` (17). **No test is dedicated to the window host.**

---

## 3. Roles, score, variants, sources, native Studio (facts for Slices 04-13)

**Roles** — `StudioRole` = `user_presenter | jarvis_presenter | rehearsal` (`jarvis/domain/presentation_studio_roles.py:53-58`); pure policy `requirements()` `:105-126`; never persisted, lives in `PlaybackState.role` (`domain/presentation_studio_playback.py:180`).

**Score** (`jarvis/domain/presentation_studio_score.py`)
- Items are a `next_item_id` chain, not a wall clock; durations are soft (`:4-7`). `ScoreItem` `:528-554` has `scene_id`, `cue_id`, reveal/hide actions, `target_duration_ms` (1..3 600 000), `timing` soft/locked.
- Anchors live on the scene (`ScoreAnchor`, optional `at_ms`, `domain/presentation_studio_scene.py:225-261`).
- Stored at `presentations/<pid>/scores/<score_id>.json`, referenced by `variant.score_id` (`adapters/file_presentation_studio_store.py:9,63`).
- `target_duration_ms` is read at playback in exactly three places: autoplay dwell for an item **without a Remotion segment** `max(1500, target or 4000)` (`core/presentation_studio_autoplay.py:112`); silence items in the presenter (`core/presentation_studio_presenter.py:521,783`); the band's `elapsed/target` display (`domain/presentation_studio_playback.py:935-937`). Remotion segment timing never reads it.
- Cue path: `POST /v1/presentation-studio/cues/satisfied {run_id, generation, cue_id}` (`protocol/presentation_studio_playback_routes.py:105-107`) → `report_cue` (`core/presentation_studio_playback.py:440-474`).

**Variant graph** — `Presentation` / `PresentationVariant` (`domain/presentation_studio.py:253-320`); graph rules `domain/presentation_studio_variants.py:1-20` (immutable display numbers, archive = move); service `core/presentation_studio_variants.py` (`create_branch :293`, `switch :401`, `archive :479`, `restore :539`); routes `protocol/presentation_studio_variants_routes.py:51-58`. Scene-local variants `psx_*` on `StudioScene.scene_variants` (`domain/presentation_studio_scene_variants.py`).

**Pins / sources**
- Each scene pins `prefab: PrefabRef(id, version)` + `source_revision` + `last_valid_pin` (`domain/presentation_studio_scene.py:314-339`). "Source pin" = that scene pin; "variant pins" = `variant_pins(scenes)` (`core/presentation_studio_service.py:85`), protected by `StudioPinRegistry`.
- Scene source = immutable prefab version, `src/**` + `public/**`, no `package.json` (`domain/remotion_source.py:4-62`); id `presentation-studio.p<12hex>.s<12hex>`, shared by all variants of a scene (`domain/presentation_studio_reload.py:189-193`).
- Only `PrefabService` writes sources: source-edit coalescer `core/presentation_studio_reload.py:532-554` or authoring `core/presentation_studio_authoring.py:303`.

**Editable source API** — read `GET …/variants/{vid}/scenes/{sid}/source`; write `POST …/variants/{vid}/source-edits` (`protocol/presentation_studio_routes.py:30-31,111-112`) → `apply_source_edit` (`core/presentation_studio_reload.py:252-279`) → gate `_gate` `:409-469` (engine match, compose, validate, value carry-over, **no new score problems**, real esbuild build) → new prefab version, repin, hot swap. Brain path: `scene.source_request` (attested user turn, `runtime/presentation_studio_mcp_tools.py:843-850`) then a sub-agent posts with `request_id` (30 min), 10 edits/scene/min. `authoring_gate.py` is **not** on this path (first drafts only).

**Native Remotion Studio**
- One process per profile, explicit user click only, requires `acknowledge_unsandboxed_scene:true` (`domain/remotion_studio.py:115-117`, `protocol/remotion_studio_routes.py:9-12`). Opens **one scene pin** (`StudioPin(prefab_id, version)`, `:93-112`), never the whole presentation.
- Working copy = scene `src/**`/`public/**` + generated `studio-root.tsx` registering ONE `<Composition>` (`domain/remotion_studio.py:164-189`), written read-only (`adapters/remotion_studio_runner.py:211-257`).
- `studio/edits/<ts>/` is a **backup before overwrite** (≤5 folders, `runner.py:269-288`), not a staging area: no code ever reads it back into the library.
- Only UI entry: the « Remotion · Studio » card in the MCP dialog « Plugins externes » (`runtime/control_center_remotion_studio.js`, `control_center.html:1739`).

**Whole-deck composition** — none exists: no `Series` / `TransitionSeries` / `<Sequence>` anywhere in `jarvis/`. Player, Studio and render all target one scene's composition; export renders one scene per job (`domain/presentation_render.py:5,288-311`, `capabilities/remotion/render-host.cjs:44-99`); no concatenation step. A canonical composition clock (Slice 04) is **new work**; natural seams: a generated root beside `plan_workspace`/`studio-root.tsx` and `scene_target`.

---

## 4. Baseline — personally rerun

Agent 0 measures the wide suite separately. Commands below were run by this Slice, one file at a time, from `brn`, with `JARVIS_DATA_ROOT` set to a fresh scratch folder, at HEAD `a8377529`:

`C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider <file>`

| File | Covers | Result (personally rerun) |
| --- | --- | --- |
| `tests/unit/test_remotion_continuity_js.py` | follower `swap_wait`, `started/done`, no replay | 11 passed |
| `tests/unit/test_remotion_stage_js.py` | stage page, `rs-bar`, control | 26 passed |
| `tests/unit/test_presentation_studio_autoplay.py` | Core deadline/dwell | 13 passed |
| `tests/unit/test_presentation_studio_player_chain_js.py` | band ▶ Slide / ▶▶ Tout | 4 passed |
| `tests/unit/test_remotion_sandbox_child_js.py` | Player `until` stop, clock | 8 passed |
| `tests/unit/test_presentation_studio_playback_docs.py` | rerun after this Slice's one-sentence doc fix (§7) | 9 passed |

All green: the defects below are **not caught by existing tests**, which is itself a finding (the tests assert the stage-window path only; nothing asserts the preview hosts, `manual` « Tout jouer », or a single clock).

---

## 5. Remove / keep / merge / refactor

Decisions are recommendations for Slices 02/04-10 (Slice 02 locks them). Data impact "none" = memory only.

| Surface / control / clock | Decision | Code owner | Test owner | Data / persisted-state impact |
| --- | --- | --- | --- | --- |
| Run stage Board window `studio_stage` (+ `studio_aux`) | **Remove** (migrate clients, §2.1) | `core/presentation_studio_stage.py`, `scene_page.js:1757-1809`, `v2_app.py:474-480` | `_stage`, `_playback_service`, `_release_faults`, `_reload_*`, `test_tool_brain_studio_ownership` | stage ledger JSON becomes orphan: one last reclaim pass must archive leftover `studio-stage-*` Board objects, then retire the file (keep a copy per repo rules); `stage_object_id` leaves the playback view and MCP inspect |
| Band `#jvStudioBand` | **Remove UI, keep run-state API** (`view/refresh/command/startRun`, `jarvis:studio-playback`) | `player.js` | `_player_js`, `_player_chain_js`, `_player_*browser` | none (dismissal in memory) |
| Band keyboard / fullscreen / `onNavigate` | **Merge** into one Variants key map + one fullscreen | `player.js:568-653`, `fullscreen.js:158-163,445-461` | `test_fullscreen_*` | none |
| Presentation window host | **Remove**; move its `startRun` to a shared playback client | `control_center_presentation_window.js` | rail JS/browser/e2e tests | none persisted; `window_open` field in rail report / MCP inspect changes |
| MCP `window_open/close`, `stage_fullscreen_enter` | **Refactor** to target Variants (contract change, version it) | `mcp_tools.py:610-656,622-629`, `core/presentation_studio_rail.py` | `_mcp_ops`, `test_presentation_studio_rail`, `test_mcp_catalog` (budget) | MCP catalog size budget |
| Stage-page inner bar `rs-bar` (Lecture/scrub/time) | **Remove as a user transport**, or make it the single transport fed by the canonical clock (Slice 06 choice) | `remotion_stage.js:118-131,440-449,477` | `test_remotion_stage_js` | none |
| Stage page `control('play')` on ready | **Refactor** (host decides; start paused) | `remotion_stage.js:352` | `test_remotion_stage_js`, `test_prefab_host_js` | none |
| Sandbox Player `loop:true` + `until` stop | **Refactor** (`loop:false`, hold last frame) | `remotion_sandbox_child.js:78-103,119` | `test_remotion_sandbox_child_js` | none |
| Explorer preview host (no `swapPrefix`, free-running loop) | **Keep and promote** to the single Variants Player; gains swap/preload and the canonical clock | `explorer.js:597-607,716` | `_explorer_*` (≈156) | none |
| Inspector preview host | **Keep** (editing preview), no transport | `inspector.js:1124` | `_inspector_*` | none |
| Explorer ‹ › + strip + `onSceneKey` | **Merge** into one scene navigation that seeks the canonical clock | `explorer.js:333-334,736-784` | `_explorer_view_js`, `_explorer_browser` | none |
| « Jouer cette slide » / « Tout jouer » | **Merge** into the Player's play (scope from the control, never default `manual`); must not close the Explorer | `explorer.js:341-344,489-512` | `_explorer_actions_js`, `_explorer_browser` | none |
| Explorer top « Plein écran » | **Keep** (single fullscreen) | `explorer.js:285,395-403` | `_explorer_browser`, `test_fullscreen_*` | none |
| Unknown lower transport row (« 8 s par slide », loop, ▶, hint) | **Do not adopt**; not in repo — Human to discard the unpushed work | unknown (§1.3) | none | none here |
| Clock: Core `SegmentClock` + autoplay deadline | **Refactor** under one composition clock (Slice 04/05) | `domain/remotion_timeline.py:174-208`, `core/presentation_studio_autoplay.py:97-129` | `test_remotion_timeline*`, `_autoplay` | none |
| Clock: follower drift/stall loop | **Refactor/shrink** (no fighting a user seek) | `remotion_frame.js:104-275` | `test_remotion_timeline_js`, `test_remotion_continuity_js` | none |
| Clock: band item clock `00:10/00:15` | **Remove** from media UI; score item time stays a presenter-only notion | `player.js:363-366` | `_player_js` | none |
| Clock: band poll (500 ms–15 s) | **Refactor** into the shared playback client | `player.js:40-46,492-498,657` | `_player_js` | none |
| Autoplay dwell from `target_duration_ms` | **Keep only for non-media items**; never cut a Remotion scene | `autoplay.py:112` | `_autoplay` | score files unchanged (field stays, meaning narrowed) |
| Native Remotion Studio card (MCP dialog) | **Refactor/promote** to a Presentation workspace destination (Slice 11/12); trust boundary unchanged | `control_center_remotion_studio.js`, `core/remotion_studio_service.py` | `test_remotion_studio*`, `test_control_center_remotion_studio` | `studio/edits/` backups: define a publish path (Slice 12) or keep as backup |
| Word « Studio » for the Variant Explorer | **Rename** (copy only) | `rail.js:86`, `window.js:121`, `explorer.js` copy | rail/explorer copy tests | none |

---

## 6. Intent vs implementation per defect (A–H)

| Defect | Code-read mechanism (not runtime-reproduced) | Status |
| --- | --- | --- |
| **A** Full playback sometimes does not start/continue | (1) **« Tout jouer » / « Jouer cette slide » start a `manual` run** — `explorer.js:501` calls `startRun(pid,'rehearsal',{variant_id})` with no `scope`; Core defaults `Scope.MANUAL` (`domain/presentation_studio_playback_requests.py:88,123`); `_auto_eligible` is false in manual (`core/presentation_studio_autoplay.py:93-95`) → after the first segment nothing advances. Same for window « Jouer » (`window.js:312-316`, `user_presenter`). (2) Even in `scene/all`, autoplay is off while `sequence`, `aux`, `jarvis_speaks` or `pending` (`autoplay.py:93-95`). (3) `done` needs `clock.frame === until_frame && !playing && sawPlaying` (`remotion_frame.js:232`); a Player that wraps (`loop:true`, `sandbox_child.js:119`) past `until` without a `frameupdate` at/after it never halts → no `done`, Core waits `remaining + 3 s grace` (+45 s until `started`) (`autoplay.py:107-111`). | (1) **proven by code**; (2)(3) candidates — **needs Slice 03 runtime repro**. Screenshot 1 is consistent: band « En cours » 00:10/00:15, ▶▶ Tout active, but the inner bar shows « Lecture » (Player halted). |
| **B** Boundary flash/stutter | Preview hosts (Explorer `explorer.js:602`, window `window.js:160`, inspector `inspector.js:1124`) are created **without `swapPrefix`**, so every slide change runs `unmount` + fresh iframe (`prefab_host.js:671-679`) → loading note, on-demand compile, `ready`, `pause frame 0`, 450 ms hold, play. In the run stage, the seamless swap only applies to `presentation-studio.*` pins when the live frame is `ready` (`prefab_host.js:661`); otherwise same remount. | Preview hosts: **proven by code**. Run stage: needs Slice 03 repro. |
| **C** Next scene starts mid-animation | (1) Core's `from_frame` = frame of the **furthest revealed anchor** of the scene (`domain/remotion_timeline.py:144-156`): if the score item that enters a scene already reveals an anchor with `at_ms>0`, or the run re-enters a scene whose anchors were revealed, the Player starts there by design. (2) Stage page orders `play` on sandbox ready (`remotion_stage.js:352`) before the host's `pause frame:0` (`prefab_host.js:486`): a hidden preloaded Player can advance a few frames before being sent back to 0. (3) Manual-scope drift catch-up seeks forward to Core's expected frame (`remotion_frame.js:248-265`). | Candidates only — **needs Slice 03 runtime repro**. |
| **D** Inner scrub does not move outer timeline | `rs-bar` scrub → `control('seek')` on the sandbox only (`remotion_stage.js:127,392-395`); the clock it emits stops at the host (`prefab_host.js:455-466`, "jamais envoyée à Core"); the band's clock is the score item's elapsed time (`player.js:363-366`), and the follower **fights** the scrub: in manual scope it re-seeks to Core's expected frame within 1 s (≤5×, `remotion_frame.js:248-265`); in auto scope a paused Player is re-ordered to play after 2.5 s (`:244`). Preview hosts have no outer clock at all. | **Proven by code** (no shared clock). |
| **E** Per-slide dwell cuts an animated scene | In repo code, Core advances on `target_duration_ms` **only** for an item without a Remotion segment in `scene/all` scope (`autoplay.py:112`) — e.g. when the timeline is unresolved (`playback.py:904-909` → `timeline_unresolved`), the Player then free-plays/loops while Core cuts at the item target. The screenshot's « 8 s par slide » selector is **unknown code** (§1.3): its cut-off cannot be audited here. Nothing ties `target_duration_ms` (8 s) to the composition length (30 s) (blind audit §2). | Repo path: code-read candidate, **needs Slice 03 repro**. Screenshot path: **unknown owner**. |
| **F** Too many overlapping controls | Screen 2: 2 fullscreen buttons (+1 in unknown row), 3 prev/next pairs (‹ ›, unknown row, strip), 2 play entry points (« Jouer… », unknown ▶) + inner « Lecture », 2 time readouts. Screen 1: band (9 buttons) + inner bar + window + Board. Plus the window host's own ◀ ▶ / Plein écran / Jouer / Studio (`window.js:119-126`). | **Proven** (inventory §1, §2). |
| **G** Agent decks worse/slower than console Claude+Remotion | Authoring is constrained by gate rules (`authoring_gate.py:107-181`: `tsx_monolith` >250 lines, `tsx_color_hardcoded` >3 literals, `tsx_text_hardcoded`, `tsx_layout_monotone`, …), playbook rules (`runtime/presentation_playbooks.py:37-126`), a 9 000-char planner budget and ≤3 fix rounds; one composition per scene, no shared deck timeline, no assets workflow. Whether these cause the gap is a judgement. | **Needs Slice 13 trace analysis**; not a code defect per se. |
| **H** Native Studio not first-class | Reachable only from the MCP dialog card; opens one scene pin; working copy is read-only; edits are backed up to `studio/edits/` and **never** published back (§3). « Studio » in the rail/window/Explorer means the Variant Explorer (`window.js:121`, `rail.js:86`). | **Proven by code** (intent gap, not a bug). |

---

## 7. Doc vs code contradictions

Fixed in this Slice (stale fact, not redesigned): `docs/presentation-studio.md` *Remotion timeline bridge / limits* paragraph said the Explorer UI offering a run start "is Slice 18"; it now says the Explorer offers it via « Jouer cette slide » / « Tout jouer », both `manual`.

Left for the rewriting Slices (02/04-06/09/15), all confirmed at `a8377529`:

| Doc statement | Code reality |
| --- | --- |
| `presentation-studio.md:2367,2504` "no blank, no remount at scene change" | only the run stage window and `presentation-studio.*` pins; preview hosts remount every slide |
| `:2466` anchorless scene "plays ONCE and holds" | Player is `loop:true`; hold relies on `frameupdate ≥ until` |
| `:2506` "A Player starts paused on its first image" | stage page sends `play` on ready (`remotion_stage.js:352`), host pause follows |
| `:2398` band button list | code also has ▶ Slide, ▶▶ Tout, Sortir de la séquence, Ouvrir l'explorateur |
| `explorer.js:343` tooltip « toute la présentation d'un coup » | starts a manual run |
| `docs/02-architecture.md` (handoff) calls `control_center_presentation_window.js` a "separate presentation window" | it is a third preview host with its own transport, and it starts runs (`window.js:312`) — and the Explorer prefers its `startRun` (`explorer.js:501`) |
| handoff `docs/06-screen-evidence.md` treats the lower row as part of the product | it is not in `d2332e61` (§1.3) |
| « Studio » word | Variant Explorer in rail/window, native Remotion Studio in `docs/remotion-studio.md` |

---

## 8. Facts that change the plan (Slices 02-10)

1. **The lower transport row and the « 8 s par slide » selector are not in the code base** (§1.3). Slices 04/10 have nothing to remove there; Slice 02 must forbid it in the contract; Slice 03 must reproduce on `d2332e61`, not on the screenshot's unknown build.
2. **« Tout jouer », « Jouer cette slide », window « Jouer » and rail « Jouer » all start `manual` runs** and close the Explorer → the floating stage. Defect A on the Variants path is proven by code; the fix is a scope and a destination change, not a timing fix.
3. **No whole-deck composition exists anywhere** (Player, Studio, render are single-scene). A canonical composition clock (Slice 04) is new work: either a generated `<Series>` root (crosses the per-scene sandbox — security review) or a pure Core interval map over per-scene Players with seamless swap. Decide in Slice 02/04.
4. **The Explorer preview host is the natural single Player but today lacks everything the stage has** (swap/preload, follower, Core clock); the stage window carries ~20 Core-side dependents (hot reload binding, pins, reveals, aux, ledger, Tool Brain guard, MCP fullscreen). Slice 09 is a migration of those bindings, then a deletion.
5. **The presentation window host also starts runs and is the shared `startRun` with refusal reasons**; it must be extracted into a shared playback client before removal, and the MCP `window_open/close` + `stage_fullscreen_enter` contracts change (catalog budget test).

## 9. Open decisions for the Human

- **Screenshot 2's build:** which machine/checkout produced it, and should its unpushed player work (the « 8 s par slide » row) be discarded? Recommendation: discard; do not port.
- **Detours / aux windows** (`studio-aux-*`): render inside Variants or stay Board windows? Recommendation: inside Variants (one surface).
- **Rail auto-open when an agent works:** open the Variants screen, or only a rail indicator? Recommendation: rail indicator only (no auto-opening full-page surface).
