# Read-only audit: Jarvis Remotion playback, Variants screen and floating stage viewer (`C:/Projects/jarvis/brn`)

I did not open `tasks/jarvis-remotion-native-studio-playback-fix/` and I ran nothing. Anything I worked out rather than saw in the code is marked **[inferred]**.

**Main finding:** a Remotion scene is shown with three separate transport bars. None of them reads one shared clock:
1. the stage page's own bar inside the frame,
2. the floating playback band, driven by Core,
3. the preview's slide navigation, with no time at all.

---

## 1. Owner map

**(a) Variants / Explorer screen and its preview**
- Controller: `jarvis/runtime/control_center_presentation_studio_explorer.js`.
  - Layout at :321-356.
  - The preview mounts the scene through a prefab host in `mode:'preview'` (:597-607, mount at :716). This host is created without `swapPrefix` or `onLive`.
  - Its own controls: scene prev/next (:333-334), « Jouer cette slide » / « Tout jouer » (:341-344), the scene strip (:346, :736-754) and fullscreen (:1173+).
- Helpers: `_explorer_core.js`, `_widgets.js`, `_compare*.js`, `_compose.js`, `_upgrades.js`.
- Other preview hosts built the same way: the presentation window, `control_center_presentation_window.js:155-184`, with its own ◀ ▶, slide strip, « Plein écran » and « Jouer » (:119-128); and the inspector, `control_center_presentation_studio_inspector.js:1124`.

**(b) Transport under the preview**
- The bar the user sees is drawn by the Remotion stage page, not by the Explorer: `control_center_remotion_stage.js:118-131` builds `rs-bar` (Pause/Lecture toggle, scrub slider, time). The time text is `${s} s / ${d} s` with one decimal (:446-447), which is the "2.6 / 30 s" reading.
- The scrub only sends `seek` to the sandboxed Player (:127, :387-407). Core never hears about it.

**(c) The floating "STUDIO_STAGE" viewer and its control box**
- The viewer is a Board window of category `studio_stage`, id `studio-stage-<run_id>`. It is created once per run and then patched by `SceneStage`: `jarvis/core/presentation_studio_stage.py:44,50,194-240`.
- The window header shows the category (`control_center_scene_page.js:1721`), which is why the user sees "STUDIO_STAGE" **[inferred: label case comes from CSS]**.
- It is wired in `jarvis/core/v2_app.py:474-480`.
- The control box is the band `#jvStudioBand` in `control_center_presentation_studio_player.js` (position fixed, bottom-left, :111). Its buttons (:241-257): ◀ Précédent, Pause, Suivant ▶, ▶ Slide, ▶▶ Tout, Plein écran, Sortir de la séquence, Arrêter, plus « Ouvrir l'explorateur de variantes » once a run has stopped.
- It also adds keyboard capture on the stage host (:580-617).

**(d) Per-scene Remotion stage and the iframe protocol**
- Window side: `control_center_remotion_frame.js` creates the `/remotion-stage` iframe and the `rsh:1` messages (`props/control/cue/teardown` and `status/clock`, :9-14). It also holds the timeline follower (:123-275).
- Mounting, preload, swap, the 450 ms hold, and the start paused on frame 0: `control_center_prefab_host.js:410-450, 452-514, 562-588, 632-701`.
- Stage page: `control_center_remotion_stage.html` and `.js`, which mounts the sandbox iframe and owns `rs-bar`.
- Sandbox child: `remotion_sandbox_child.js`, which mounts `@remotion/player` with `controls:false, loop:true` (:116-121) and stops itself at the `until` frame (:78-87, :96-103).
- Protocol and server: `remotion_sandbox_protocol.js`, `remotion_sandbox_server.py`.
- Core side: `jarvis/core/remotion_player.py` builds the descriptor (composition at :110).
- The scene page wires all of this together: `control_center_scene_page.js:1757-1809`, with `swapPrefix:'presentation-studio.'`, `onLive`, `onClock`, and listeners for `jarvis:studio-timeline` and `jarvis:studio-segment`.

**(e) Native Remotion Studio process and its UI entry**
- Domain: `jarvis/domain/remotion_studio.py` (builds `studio-root.tsx`, :181).
- Service: `jarvis/core/remotion_studio_service.py` (`open/sync/close/restart/status/reconcile`, watch loop every `TICK_S=15`).
- Process runner: `jarvis/adapters/remotion_studio_runner.py`.
- In-process guard: `jarvis/capabilities/remotion/studio-guard.cjs`.
- Routes and relay: `jarvis/protocol/remotion_studio_routes.py`, `jarvis/runtime/remotion_studio_relay.py`.
- UI: the card in `control_center_remotion_studio.js`, inside the « Plugins externes » tab of the MCP dialog (`control_center.html:1739`).
- Brain tool: `remotion_studio` in `remotion_mcp.py:155` and `remotion_mcp_tools.py:195`. It only says where to click.

**(f) Presentation rail**
- Page: `control_center_presentation_rail.js`.
- Core: `jarvis/core/presentation_studio_rail.py`.
- Routes: `jarvis/protocol/presentation_studio_rail_routes.py`.
- Storage: `file_presentation_studio_store.py` (`rail.json`).
- MCP: `presentation_studio_mcp_tools.py` (`presentation_view`, `presentation_library`).

**Core playback**
- Service: `jarvis/core/presentation_studio_playback.py`, with mixins `presentation_studio_autoplay.py` (chained play) and `presentation_studio_preview.py` (scene-variant preview on the stage).
- State machine: `jarvis/domain/presentation_studio_playback.py`.
- Request bodies: `jarvis/domain/presentation_studio_playback_requests.py` (Verb at :29-49, Scope at :52-58).
- Frame map and segment clock: `jarvis/domain/remotion_timeline.py`.
- Routes: `jarvis/protocol/presentation_studio_playback_routes.py`.
- Speaking runs: `jarvis/core/presentation_studio_presenter.py`.

## 2. Durations and how scenes are sequenced

**Where the "8 s" comes from**
- It is `item.target_duration_ms`, a soft per-item target written into the score by whoever authored it. Core puts it in the view at `domain/presentation_studio_playback.py:935`.
- The band shows it as `00:02 / 00:08` (`player.js:363-366`, mm:ss).
- There is no 8000 ms constant anywhere in the code. So the value is agent-authored **[inferred]**; the guide's examples use 20 000 and 15 000 (`presentation_studio_authoring_guide.py:157,181`).
- The gate only bounds it: 500 ms to 15 min, and the total must be within ± a tolerance of the brief's duration (`authoring_gate.py:72-73, 135-137`).
- The only fallback constants are `DEFAULT_DWELL_MS=4000` and `MIN_DWELL_MS=1500` (`core/presentation_studio_autoplay.py:35-36`), and they apply only to items with no segment to play.

**Where the "30 s" comes from**
- It is the scene manifest's `composition.duration_in_frames / fps`, read by `PrefabService.remotion_composition` (`core/presentation_studio_playback.py:899-903`).
- If the agent gives no composition, the default is 150 frames at 30 fps, i.e. 5 s (`authoring_remotion.py:50`). The guide's examples use 300 frames.
- So 30 s is 900 frames chosen by the agent **[inferred]**.
- Nothing ties the item target to the composition length.

**One composition per scene, swapped at each boundary**
- Each scene is a separate prefab pin and a separate Remotion composition.
- The stage window is patched with the next scene's prefab (`presentation_studio_stage.py:205-222`), and the host swaps iframes.
- The next scene can be preloaded hidden beside the live one (`prefab_host.js:686-701`, taken over at :649-658). This only works when:
  - the prefab id starts with `presentation-studio.` (:661, :691);
  - Core announced it as `next_scene` (`core/presentation_studio_playback.py:1236-1252`);
  - its pin differs from the current one.
- The preview hosts (Explorer, presentation window) have no `swapPrefix`, so each slide change unmounts and remounts the iframe (`prefab_host.js:671-679`).

**How the next scene gets its start frame**
- Core sends `timeline.from_frame` from `target_segment` (`remotion_timeline.py:129-156`): frame 0 for the entry segment, otherwise the frame of the furthest revealed anchor.
- `seq` and `play_ms` come from `SegmentClock.observe` (:196-208, used at `playback.py:919-935`).
- In `scene`/`all` scope only, a scene without anchors gets one segment covering the whole composition (`playback.py:903`, `remotion_timeline.py:136-137`).
- In `manual` scope, a scene without anchors gets no timeline at all. It free-plays and loops (`prefab_host.js:440-449` plus `loop:true`).
- Every mounted Player starts paused on frame 0 (`prefab_host.js:486`). But `remotion_stage.js:352` sends `control('play')` on ready just before that pause arrives, a possible brief race **[inferred]**.

## 3. Clocks and state machines

There are about seven clocks, and sync is mostly one-way, from Core to the browser.
1. **Sandbox Player frame clock** (Remotion `@remotion/player`).
   - Emits `clock` at most every 250 ms (`remotion_sandbox_child.js:70-77`).
   - Runs with `loop:true` and stops itself at `until` (:78-87).
2. **Stage page projection** (`remotion_stage.js:323-333, 440-449`).
   - Relays the clock to the window at most every 250 ms (`CLOCK_RELAY_MS`).
   - Redraws `rs-bar` every 500 ms (:477).
   - The `rs-bar` scrub and pause act on the Player locally only.
3. **Prefab host**: stores `rec.clock` and a per-mount `incarnation`; 450 ms hold before playing on its own (`prefab_host.js:111, 442-449, 455-466`).
4. **Timeline follower** on the scene page (`remotion_frame.js:104-266`).
   - Ticks every 500 ms and recomputes the expected frame from Core's `play_ms` plus local time.
   - Manual scope: catches up by seeking (at most 1 correction/s, 5 per segment).
   - `auto` scope: sends `advance{started|done}` to Core; re-sends after 2.5 s if the Player stalls (`STALLED_MS`), up to 3 times.
5. **Band** (`player.js:40-46, 492-498, 657`).
   - Polls `GET /playback` every 500 ms when there is a timeline, 1.5 s when active, 5 s idle, with backoff up to 15 s.
   - Advances its displayed item clock locally every 1 s.
6. **Core**, several independent pieces:
   - the closed state machine (`domain/presentation_studio_playback.py`) with item and run elapsed time (`where_are_we`, :906-937);
   - `SegmentClock` (`remotion_timeline.py:174-208`);
   - the autoplay deadline, an `asyncio` timer: remaining segment + 3 s grace, + 45 s load allowance until `started` (`autoplay.py:97-129`);
   - the presenter / locked-sequence clock (`presenter.py`, `domain/presentation_studio_sequence.py`);
   - the preview timeout.
7. **Preview hosts** (Explorer / window): the Player free-runs and loops. The only other timers are graph or document re-reads (Explorer graph every 10 s, explorer.js:41; window every 5 s, window.js:23).

**Also: two transport channels**
- The scene page receives the stage patch through its scene long-poll (`scene_page.js:252-342`).
- The timeline arrives through the band's poll.
- The follower bridges the gap with `swap_wait` and `onLive` (`remotion_frame.js:175-178, 201-205`).
- The Player's position never reaches Core (doc `presentation-studio.md:2484`).

## 4. Recent commits

**a8377529** is only the handoff mirror (67 files).

**d2332e61** (2026-10-10)
- One-line doc change for MCP context budgets: `jarvis-presentation` 19 138 bytes with `scope`, ceiling 19 300 (`docs/presentation-studio.md`, `docs/mcp/tool-contract.md`, `test_mcp_catalog.py`).
- No effect on behaviour.

**55039c2d**
- Removes the PRS dock button; the rail is now toggled with Alt+Maj+P (`control_center_presentation_rail.js:610-617`, `control_center.html` minus 1 line).
- Test and string tweaks only. No playback impact.

**4288e735** (presentation rail, 31 files, about 2.9k lines)
- Adds:
  - `core/presentation_studio_rail.py` (366 lines), with `rail.json`, in-memory work state and the brain's screen requests;
  - routes and client;
  - `control_center_presentation_rail.js` (623) and `control_center_presentation_window.js` (352);
  - the MCP ops `presentation_view window_*/rail_*` and `presentation_library`.
- Explorer changes: the variant bar, plus « Jouer cette slide » / « Tout jouer » (`explorer.js:340-344, 487-512`).
- Relation to the symptoms:
  - It **adds** redundant controls and a second floating window that has its own ◀ ▶ / fullscreen / play.
  - « Tout jouer » calls `startRun` **without `scope`**, so it starts a manual, not chained, run from slide 1. This contradicts its tooltip « Lancer toute la présentation d'un coup ».

**0a5adaaf** (chained Remotion playback, 29 files)
- Core:
  - `Verb.PLAY/ADVANCE` and `Scope` (`playback_requests.py`);
  - autoplay mixin with deadlines;
  - the `whole_scene` timeline;
  - `timeline.prefab` and `auto` fields;
  - `SegmentClock.restart`;
  - `next_scene` and `GET /playback/preload`.
- Browser:
  - the follower orders only its own scene's frame (`swap_wait`);
  - it no longer re-orders a Player that halted on its stop frame (this fixes "replay every ~3 s");
  - it reports `started`/`done`;
  - the host starts Players paused on frame 0, preloads the next scene and takes it over;
  - the band gains ▶ Slide / ▶▶ Tout.
- Tests: autoplay (13), continuity_js (11), the real-Chrome continuity test, chain_js (4).
- Relation to the symptoms:
  - It addresses replay/flash and mid-animation starts **for the run stage window in `scene`/`all` scope** (measured in doc :2508).
  - It does **not** cover the preview hosts, `manual` scope without anchors, a second transport, or non-`presentation-studio.` pins. It also **adds** two buttons to the band.

**0d2b6830** ("small fixes")
- Adds `presentation_playbooks.py` (151 lines), the brief/author/review sub-agent playbooks.

## 5. Native Remotion Studio

- **Launched and managed by Jarvis, but only on an explicit user click.**
  - Started by `POST .../studio/open`, which requires `acknowledge_unsandboxed_scene:true`.
  - Never started by Core boot, the preview or the brain (`docs/remotion-studio.md:9-15`).
- Process:
  - one per profile, bound to loopback only, behind an in-process guard;
  - idle shutdown after 30 min by default;
  - adopted again after a Core restart; killed when Core stops (`docs/remotion-studio.md` §3, §5).
- **UI exposure:** only the « Remotion · Studio » card at the top of the « Plugins externes » tab in the MCP dialog (`control_center.html:1739`, `docs/remotion-studio.md` §8). It shows a confirmation that names the source's provenance, then opens a `target=_blank` link.
  - It is not reachable from the Presentation Studio or the rail. There, « Ouvrir le Studio » means the variant explorer, so the word "Studio" is overloaded.
- **Edits are staged aside, never persisted.**
  - The working copy is read-only.
  - Changes made from outside Jarvis are copied to `studio/edits/<ts>/` (at most 5 folders) on close or sync, then overwritten (`remotion_studio_runner.py:216, 269-292`; doc §2, §9: « Rien n'est écrit dans la bibliothèque »).
  - The real edit path is the source-edit route (`scene.source_request`, a sub-agent; Slice 14).

## 6. Agent authoring constraints

**Playbooks** (`runtime/presentation_playbooks.py:37-126`)
- Three roles: brief, author, review.
- The author must read the brief and follow its art direction; one idea per scene; at most about 20 words on screen.
- Visuals are SVG animated with `interpolate`/`spring`; colours come from `props.theme` and `./jarvis-kit`, never hard-coded.
- Workflow: `presentation_draft_assemble`, then gate fixes; never start playback or exports.
- `PLANNER_PROMPT` (`authoring_policy.py`) is appended, with a 9000-character budget and at most 3 fix rounds.

**Generator** (`authoring_remotion.py:48-60`)
- Exact-key spec `{title, files, …, composition?}`.
- `theme` is a reserved prop that Core declares and fills.
- Namespace `presentation-studio.`; Remotion only.

**Gate rules** (`authoring_gate.py:107-181`)
- Engine: `prefab_engine_mismatch` (HTML is refused).
- Compilation: `tsx_compile` and its budgets.
- Source content:
  - `tsx_theme_unread`, `tsx_color_hardcoded` (more than 3 colour literals), `tsx_text_hardcoded`;
  - `tsx_static_scene`, `tsx_interpolate_unclamped`, `tsx_props_unread/undeclared`;
  - `tsx_monolith` (over 250 lines), `tsx_layout_monotone`.
- Anchors: `tsx_anchor_range` (`at_ms` must fall inside the composition), `tsx_anchor_untimed`.
- Live refs and inspiration rules.
- Content rules: placeholder, density, contrast, arc, `scene_no_score`, duration rules, cue rules, `motion_unguarded` (reduced motion), `behavior_risky`.

**Isolation**
- Static guards in `domain/remotion_isolation.py`: no access to window, document, network, workers or dangerous tags. Applied at publish time and on every re-read.
- Then the sandbox iframe on a dedicated origin with its CSP.
- TSX lint (`authoring_tsx.py`): linear and time-boxed (2 s), and fails closed.

## 7. Entry points into the floating viewer (all would need migrating)

Every run start creates the `studio-stage-*` window and the band. The entry points:

- **Brain / voice MCP:**
  - `presentation_play start|play|goto|next|…` (`presentation_studio_mcp_tools.py:706-764`; prompt at `claude_local.py:191`);
  - `presentation_view stage_fullscreen_enter`, which targets `stage_object_id` (:622-629);
  - `presentation_inspect target playback` (:367).
- **Voice cue follower:** `runtime/presentation_studio_cue_follower.py:325`, then `/cues/satisfied`, then `next`.
- **Jarvis presenter:** `core/presentation_studio_presenter.py`, through `notify`.
- **Graphical:**
  - band buttons and keys (`player.js:59-66, 569-617`);
  - Explorer « Jouer cette slide/Tout jouer » (`explorer.js:489-512`);
  - window « Jouer » (`window.js:312-316`);
  - rail menu « Jouer » (`rail.js:416-421, 445`);
  - `JarvisStudioPlayer.startRun/chain/enterFullscreen` (`player.js:701`);
  - the fullscreen module's `onNavigate`.
- **Core features that depend on the stage window:**
  - hot reload binding (`core/presentation_studio_reload_stage.py`, `playback.py:958-977`);
  - scene-variant preview (`presentation_studio_preview.py`);
  - detours and aux windows;
  - ledger and reclaim;
  - the Tool Brain guard (`tool_brain_executor.py:127-129`);
  - `presentation_studio_scene_variants.bind_playback` (`v2_app.py:499`).

## 8. Existing tests (file: number of `def test_`)

- **Band / player:** `test_presentation_studio_player_js` 30 (node harness, so several cases per test), `_player_chain_js` 4, `_player_browser` 4, `_player_realpage_browser` 4.
- **Explorer:** `_explorer_*` 15 files, about 156 tests (actions_js 23, commands 21, lifecycle_js 19, view_js 15, browser 14, core_js 14, compare_js 12, …).
- **Playback (Core):** `_playback` 52, `_playback_service` 39, `_playback_rework` 16, `_playback_routes` 13, `_playback_docs` 9, `_autoplay` 13, `_stage` 10.
- **Timeline / continuity / frame:** `test_remotion_timeline` 19, `_timeline_js` 22, `_timeline_service` 12, `_timeline_composition` 3, `_timeline_realpage_browser` 2, `test_remotion_continuity_js` 11, `_continuity_realpage_browser` 1, `test_remotion_stage_js` 26, `test_prefab_host_js` 18, `test_remotion_sandbox_child_js` 8, `_sandbox_protocol_js` 16, `_sandbox_server` 5.
- **Native Remotion Studio:** `test_remotion_studio` 35, `_runner` 22, `_guard` 19, `_rework` 19, `_routes` 10, `_docs` 10, `_data` 2, `_real` 1 (opt-in), `test_control_center_remotion_studio` 23.
- **Rail / window:** `test_presentation_studio_rail` 17, `test_control_center_presentation_rail_browser` 13, `_rail_js` 7, `test_presentation_rail_e2e_browser` 3. I found no test file dedicated to the presentation window; it is exercised inside the rail tests **[inferred]**.
- **Authoring:** `_authoring_*` 15 files, about 250 tests (remotion 49, gate 29, service 29, policy 24, …), `test_presentation_playbooks` 6, `test_remotion_isolation` 42, `test_remotion_source` 25.
- **MCP:** `test_presentation_studio_mcp` 23, `_mcp_ops` 21, `_mcp_policy` 11, `test_remotion_mcp_tools` 34, `_mcp_server` 12.
- **Presenter / cues:** `_presenter*` about 80 tests, `_cue_follower` 42, `_cues` 35.
- **Reload:** `_reload_*` about 200 tests.
- **Fullscreen:** `test_fullscreen_js` 36, `_commands` 26, `_browser` 8.

## 9. Canonical docs and where they disagree with code

**Which doc owns what**
- `docs/presentation-studio.md`: playback runtime :2282, stage window :2363, band :2396, Remotion timeline bridge :2431, chained playback :2490, Variant Explorer :2776, rail :3331.
- `docs/remotion-isolation.md` (§10-11), `docs/remotion-studio.md`, `docs/presentation-engine.md` (engine policy).
- `docs/presentation-mode.md` is only an index for the PRESENTATION interaction mode, a different concept from the Studio.

**Contradictions and stale statements**
1. **"No blank, no remount, no frame 0 flash at scene change"** (`presentation-studio.md:2504`, :2367).
   - Only true for the run's stage window on the scene page, and only for `presentation-studio.*` pins.
   - The Explorer and window preview hosts have no `swapPrefix`, so they remount on every slide (`explorer.js:602`, `window.js:160`, `prefab_host.js:671-679`) and loop freely.
2. **« Tout jouer » tooltip** (`explorer.js:343`) promises the whole deck in one go.
   - The code (:501) and the doc (:3419: "`start` … then `goto`") start a manual run instead.
   - The doc also says "Smoothness of the playback itself is not part of this section".
3. **"A scene with no anchors … plays ONCE and holds its last image (it does not loop)"** (:2466).
   - This depends on the `until` check in `onFrameUpdate`, while the Player still has `loop:true` (`sandbox_child.js:81, 119`).
   - If the Player wraps past the last frame before a `frameupdate` sees it, the hold is missed **[inferred risk]**.
4. **"A Player starts paused on its first image"** (:2506).
   - The stage page itself sends `play` on ready (`remotion_stage.js:352`), and the host's pause follows.
5. **The doc's band description** (:2398) lists previous/pause/next/fullscreen/stop.
   - The code also has ▶ Slide / ▶▶ Tout and Sortir de la séquence (`player.js:245-257`); the doc only mentions these at :2399-2500.
   - :2429 still says the explorer UI that offers a run start "is Slice 18", but it exists now.
6. **The `rs-bar` transport inside the frame** (`remotion_stage.js:118-131`) is not described as a user transport in `presentation-studio.md`.
   - Its scrub and pause fight the follower: drift correction in manual scope, stall re-send after 2.5 s in auto scope (`remotion_frame.js:244, 256-263`). This matches "scrubbing one does not move the other" **[inferred]**.
7. **"Studio" has two meanings:**
   - rail and Explorer « Ouvrir le Studio » means the variant explorer (`rail.js:86`, :3410);
   - `remotion-studio.md` means the native Remotion Studio, reachable only from the MCP dialog card.