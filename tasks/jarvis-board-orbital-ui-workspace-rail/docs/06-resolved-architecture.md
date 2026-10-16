# 06 - Resolved architecture (Slice 00, binding)

Written by the Slice 00 planner on worktree `bor`, HEAD `b956fd49`
(`origin/main` `57f28a74` + handoff mirror `c8e753e5` + merge of
`task/jarvis-unified-chat-and-board-drop` `e614669d`). Supersedes `02-architecture.md`
and `03-implementation-strategy.md` wherever they differ. Every code fact cites
`file:line` at HEAD; re-check before dispatch (freshness gate).

## 1. Verified facts and corrections to the blind audit

| # | Fact at HEAD | Evidence | Audit claim |
|---|---|---|---|
| F1 | Layer registry is the CSS comment in `control_center.html:12-68`; enforced by `tests/unit/test_scene_renderer_logic.py:1376-1414` (asserts `.voicehint`, `.dock`, `.bgpills`, `.panel`, `#boardsPanel`, Cosmos ranks) | read | confirmed |
| F2 | Cosmos theme (`control_center_work.js:154-205`) is a second full layout: `.topbar` 45 (right:422px), `.dock` top-right ROW 50, `.bgpills` top row 50, `.panel` 42, `.live-banner` 48; `#boardsPanel` Cosmos 51 (`control_center.html:90`) | read | confirmed; note the default theme is `circuit-board` (`control_center_work.js:762`), the user runs Cosmos (`assets/current-ui.png`) |
| F3 | Unified-chat ranks absent from the registry comment: `.chat-tab` 32 / Cosmos 50 (`control_center.html:312,433`), chat panel = `.panel` 33 / Cosmos 42, `.board-drop::before` 21, `.board-drop-card` 34, `.board-drop-tray` 34 / Cosmos 49 (`:448,450,456,478`) | read | confirmed |
| F4 | Presentation rail ranks also outside the registry text body: host 30, Studio 9100, menu 9300, dialog 9400 (`control_center_presentation_rail.js:96,132,137,145`); `#presentationRail` is created by the script, not declared in the HTML | read | 9400 missing from audit |
| F5 | No standalone Control Center UI/layer doc in `docs/` | `ls docs` | confirmed |
| F6 | `.dock` (`control_center.html:1839-1850`): ERR TRC LAB CNV SET MCP WSP PFB INS AGT | read | confirmed |
| F7 | Background pills: categories `failed/attention/done/said` (`control_center.html:2195-2200`; Core `background_events.py:83-87`), counts from `/api/status` beat, popover `/api/background?limit=60` (`:2285`), ack `POST /api/background/ack` (`:2334`), sound `bgCue`/`bgCueTone` (`:2141-2172`), multi-tab leader via `JarvisPresentationAttentionControl.mayCue` (`:2185`), Board "elsewhere" attribution (`:2213`) | read | confirmed |
| F8 | `said` = background agent result not spoken (`agent.unsolicited_result` with `spoken:false`, `docs/boards.md:1710`); canonical and meaningful | read | resolves O04 |
| F9 | `#voiceHint` text rewritten in `refreshStatus` (`control_center.html:2354`: `${key} · DÉMARRER/ANNULER/INTERROMPRE`, `VOICE HORS LIGNE`); hidden while chat open (`:320`) | read | confirmed |
| F10 | Hidden objects: per-object `visibility` (`control_center_scene_interact.js:1153` `set_visibility`), capsule = `.sc-note.sc-hidden` inside `.sc-status` (`control_center_scene_page.js:3844-3847`, menu `openHiddenMenu` `:3300`). `.sc-status` also carries scene degraded, scene full, covered signals, stopping, offscreen notes (`:3807-3870`) | read | correction: only the hidden note is replaced; `.sc-status` stays |
| F11 | A canonical per-browser scene view-pref store exists: `JarvisSceneView` (`control_center_scene_view.js`, key `jarvis.scene.view`), with precedent filter toggle `showEphemeral` (`:58`) applied in `viewModel` via `options.workView` (`control_center_scene_layout.js:1705-1719`) | read | new, drives D9 |
| F12 | BH lifecycle `off/sleep/active/error` (`control_center_barehands_contracts.js:110`); public surface `enable/disable` = master switch written to server (`control_center_barehands.js:9632,8998`), `activate/sleep` (`:9644`). HUD `choose()`: OFF is "the only mode where c_pose can do nothing" (`control_center_barehands_hud.js:1655-1661`) | read | drives D5 |
| F13 | Synthetic BH events: `PointerEvent` with `pointerType:'mouse'` and `pointerId` 9001-9002 (`control_center_barehands.js:5996`, contracts `:160-172`), `MouseEvent` clicks, `contextmenu` from thumb+middle pinch (`:6408-6411`). All synthetic events have `isTrusted===false` | read | confirmed |
| F14 | Voice path to BH: brain tool `barehands_activate` -> `JarvisBarehands.activate()`; `deactivate` -> `sleep()` (`docs/barehands-contracts.md` §12) | read | used for explicit return |
| F15 | Palette tools `pointer/pan/select` (`contracts.js:923`), canonical selector `#barehandsPalette` (`docs/barehands-contracts.md` § Palette, `:1795`); capture is not a BH tool (D14/D15, `:1862-1870`) | read | confirmed |
| F16 | Capture rail routes `/api/captures/status|start|screenshot|{id}/stop` (`control_center_capture_rail.js:97-100`), no options sent. Core accepts `options:{source?,device?}` (`jarvis/protocol/capture_routes.py:16,179-184`). Screen devices `default|displayN` (`jarvis/adapters/screen_capture.py:579-600`); displays enumerable in-process (`jarvis/adapters/windows_display.py:169`) but no route. Audio device token `default` (= Voice setting `audio_input_device`) or PortAudio index/name (`jarvis/adapters/sounddevice_recording.py:423-428`); Control Center lists input devices at `/api/audio/devices` (`control_center.py:1504,6072`) in ITS process, not Core's | read | correction: audio is not "microphone default only" |
| F17 | Screenshot answer `{capture, artifact}` (`jarvis/core/capture_api.py:278-280`); artifact routes `/api/artifacts/{id}`, `/payload` (bytes, 8 MiB per response), `DELETE` (`capture_relay.py:109-115`). No UI after a screenshot | read | confirmed |
| F18 | Chat attachments: Core refuses any artifact not `kind=upload` + `provenance=chat_attachment` of the open Session (`jarvis/core/upload_service.py:499-514`, `docs/chat.md` step 5). A message must carry text | read | drives D7 |
| F19 | Presentation rail: `left:94px top:76px` z30 (`control_center_presentation_rail.js:96`), rows = Studio summary + `hidden/archived/work` (`jarvis/core/presentation_studio_rail.py:209-226`), no thumbnail/type; work state in memory, TTL 90 s (`:41`); flags persisted in `<data_root>/presentations/<id>/rail.json`, schema v1, unknown keys ignored by `parse_rail` (`:67-86`) | read | drives D10 |
| F20 | Render artifacts `presentation_still/video/pdf` (`jarvis/domain/artifacts.py`), previewed by the Workspace inspector through `/api/artifacts/{id}/payload` (`control_center_workspace.js:1371-1381`) | read | confirmed |
| F21 | Board-linked artifacts: `GET /v1/workspace/artifacts?board_id=` (`jarvis/protocol/workspace_routes.py:20`) | read | Stage B source |
| F22 | Interaction mode bottom-left rungs `--im-rail/--im-lift`, `<700px` escape (`control_center_interaction_mode.js:597-656`) | read | confirmed |
| F23 | `#boardsHud` in `.topbar` (`control_center.html:1761`); `docs/boards.md:1457-1459` says "top-right; top-left in the Cosmos theme" | read | correction: boards.md is accurate, not stale |
| F24 | `CONTROL_SELECTOR` (`control_center_scene_page.js:2476`) omits `#interactionModeHud`, `#chatTab`, `#presentationRail`, `#boardDropTray` (existing gap); capture rail has its own `OBSTACLE_SELECTOR` (`control_center_capture_rail.js:1144`); `test_capture_rail_js.py:408` parses the literal | read | extended |
| F25 | Tests coupled to current chrome (verified lines): `test_control_center_mvp.py:74` (F9 text), `:94-108`, `test_interaction_mode_hud_js.py:1328,1397,1469`, `test_presentation_attention_browser.py:606`, `test_barehands_hud_js.py:985`, `test_prefab_library.py:497`, `test_control_center_mcp_inspector_js.py:821`, `test_presentation_studio_inspector_docs.py:117`, `test_board_alerts_browser.py:31`, `test_capture_rail_js.py:389-415`, `test_presentation_rail_e2e_browser.py:52,68`, `test_barehands_contracts_js.py:194`, `test_boards_hud_js.py:924`, plus `test_control_center_chat_ui.py:77` and `test_control_center_chat_browser.py:385` (voicehint hidden under chat) | grep | two chat tests added |
| F26 | New page modules are inlined by `ControlCenter.index` (`control_center.py:2293`) through a `*_SCRIPT_FILE` constant (e.g. `:590`) | read | wiring rule |

## 2. Owners (unchanged) and new modules

| Concern | Owner (unchanged) | UI module after this task |
|---|---|---|
| BH lifecycle | `control_center_barehands.js` controller + `JarvisBarehands` | projected by the wheel's Selection; lifecycle HUD kept until S03 |
| Selection method | none new: derived from BH lifecycle (D5) | `control_center_input_arbitration.js` (pure policy + seam) |
| Capture | Core `CaptureService` via relay | `control_center_capture_rail.js` controller refactored to a view-model publisher; views in wheel + status centre |
| Artifacts | Core `ArtifactService` | `control_center_screenshot_preview.js` |
| Background alerts | Core/CC `background_events.py` + `/api/status` | `BG` code in `control_center.html` re-rendered into the status centre (ids `#bgPills`, `.bgpill`, `#bgPop` kept) |
| Hidden objects | Core scene `visibility`; view pref `JarvisSceneView` | eye button in status centre |
| Presentation rail | Core `presentation_studio_rail.py` | `control_center_presentation_rail.js` rebuilt right; `control_center_workspace_rail_model.js` (pure view-model adapter) |
| Interaction mode | Core `/api/status` + `/api/interaction-mode` | unchanged module |
| Boards | `control_center_boards.js` | unchanged owner (see D11) |
| Shell geometry/layers | NEW canonical doc `docs/control-center-shell.md` | `control_center_shell.js` (tokens, zones, `CONTROL_SELECTOR`), registry test `tests/unit/test_control_center_shell_layers.py` |
| Tool wheel | NEW surface | `control_center_tool_wheel.js` (render, geometry, keyboard, pointer; injected actions) |

Each new module: `*_SCRIPT_FILE` constant + injection in `ControlCenter.index` (F26), host declared in `control_center.html` (rank in registry), refuses to install under a searchable name if its host is missing (existing convention), journal lines `[<module>] <key> {json}`.

## 3. Decisions D0-D13 (resolved)

- **D0 Task Type: `waived`.** No Workspace Task Type vocabulary exists in the repo; Human precedent on 5+ tasks. `task_type: "waived"` in `task.json` and every `metadata.json`.
- **D1 Base.** Built on the unified-chat merge `b956fd49`; lands after `task/jarvis-unified-chat-and-board-drop` reaches `main`. The shell contract owns placement of `#chatTab`, `#chatPanel`, `#boardDrop`, `#boardDropTray`, `.toasts`. If unified-chat changes those surfaces again before landing, re-run the S01 registry test against the new merge.
- **D2 Shell contract.** `docs/control-center-shell.md` created in S01: zones, tokens, layer registry (single source), `CONTROL_SELECTOR` membership, a11y rules. The HTML comment `control_center.html:12-68` is replaced by a pointer to the doc plus a machine-readable mirror; `test_control_center_shell_layers.py` parses the real CSS (base and Cosmos `STYLE`) and compares it to the doc table. Every later slice updates the doc in the same commit as the CSS.
- **D3 Wheel = new surface.** Not the BH palette, not the capture rail. Video/Screenshot/Audio wedges call the capture controller (no `data-bh-tool`, D15 intact). Old palette/rail stay functional until S03/S04 migrate them (rollback = remove the wheel host).
- **D4 Secondary activation = the existing secondary channel.** Mouse right-click, BH thumb+middle pinch (already a real `contextmenu`, F13), keyboard `ContextMenu` / `Shift+F10` on the focused wedge. Never long press (BH decision 22). README/SLICE "long-press" wording replaced (S00 contracts below; README left as planning record, this doc wins).
- **D5 Selection method: resolved in §4.**
- **D6 Capture targets: resolved in §5.**
- **D7 Screenshot actions: resolved in §6.**
- **D8 Bottom status centre.** Categories, in order: `failed` (orange, alert), `attention` (question, "points à vérifier"), `done` (check), `said` (unspoken result, F8) — the fourth is canonical, so it stays. Icons are inline SVG (no emoji), 32 px targets, count badge, `aria-label` = existing `pillLabelOf` text. Popover, ack, sound cue, multi-tab leader, Board-elsewhere attribution and go-to-Board unchanged (same `BG` code, same ids `#bgPills/.bgpill/#bgPop`). `#voiceHint` element removed in S06; its text moves into the top state line as an accessible description (`.state` gets `title`/`aria-description` "F9 · DÉMARRER" etc.; `VOICE HORS LIGNE` already readable there via `#voiceState`); F9 keyboard untouched. Board drop tray sits above the status strip: `bottom = var(--shell-bottom) + var(--shell-status-h) + 8px`.
- **D9 Eye toggle: resolved in §7.**
- **D10 Workspace rail: resolved in §8.**
- **D11 Board access (CHANGED, reason below).** Board control `#boardsHud` stays where the approved target shows it: in the top state line (top-left in Cosmos, F23). Bottom-left keeps the interaction-mode control only. Reason: `assets/target-ui-reference.png`, which the user called exactly what they wanted, shows `BOARD Présentation Jarvis` top-left and `MODE SIMPLE` alone bottom-left; moving it would contradict the approved composition, move a control twice and break `test_boards_hud_js.py:924` for no product gain. The grill phrase "keep the bottom-left mode/Board context control" is kept as an explicit Human check (HV-08-01). Fallback, fully specified if the Human prefers: `#boardsHud` moved as a sibling button right of `#interactionModeButton`, same `JarvisBoardsControl`, no merged state, `docs/boards.md` § Placement updated. Dock tools move into a compact top-right launcher (S08), nothing deleted.
- **D12 QA tiers.** S01 ui, S02 ui, S03 ui (+ property-style tests of the pure arbitration function), S04 critical (privacy stop path, status truth; mutation testing allowed), S05 ui (+ adversarial on Delete/Send/Annotate route), S06 ui, S07 ui (no SQLite migration, §8), S08 ui, S09 ui, S10 docs. Runtime validation always on an isolated instance (own ports, own `JARVIS_DATA_ROOT`, headless Chrome via CDP), never `127.77.0.1:17653/17654`.
- **D13 Parallelism.** One implementer per worktree. S02 and S07 may run in parallel after S01, separate worktrees; S07 must not touch `control_center.html` outside the rail host line and the registry row it owns (merge order: S02 first, S07 rebases).

## 4. D5 - Selection method and Mouse takeover

**Owner: none new.** The selection method is a projection of the BH lifecycle (F12):

| BH lifecycle | Selection shows | Notes |
|---|---|---|
| `active`, `sleep` | Bare Hands | ACTIVE<->SLEEP (idle timeout, `c_pose` wake) stays Bare Hands' own business |
| `off` | Mouse | master switch false; `c_pose` cannot wake (F12) |
| `error` | Bare Hands, error mark + cause (`code`) | truthful failure, Mouse still usable |
| `starting` | Bare Hands, wait mark | |

- **Mouse** = `JarvisBarehands.disable()` (existing single write path: camera released, master switch persisted, other tabs follow through `gate`). This is the only lifecycle in which hand presence and `c_pose` cannot return control: explicit-only return is guaranteed by construction, with no new field.
- **Bare Hands** = the HUD `choose('active')` sequence (`activate()` then `enable()` to persist, `control_center_barehands_hud.js:1686-1694`), exported as one function so the wheel and the HUD share it. Voice return = existing `barehands_activate` (F14).
- **Rejected:** Mouse = `sleep` (c_pose would auto-return) and a new `wakeOnPosture` / "mouse lock" field (second state). Accepted cost: camera re-acquisition latency on return (landmarker + getUserMedia). S03 measures it on the isolated instance; if > 3 s, the fallback (an `idle_wake` BH setting in BH settings v2, `docs/barehands-contracts.md` §9) is filed as an Issue, not built.
- **Takeover policy** (`control_center_input_arbitration.js`, pure core + browser seam). Input = real pointer events only: `event.isTrusted === true` AND `!BH.isBareHandsPointerId(event.pointerId)`. `pointerdown` / `click` / `wheel` / `contextmenu` -> immediate takeover (`reason: 'click'`). `pointermove` -> accumulate displacement in a sliding window; takeover when path length `>= distancePx` within `windowMs` AND net displacement `>= netPx` (jitter cancels out). Defaults (tunable, logged): `distancePx 48`, `netPx 24`, `windowMs 400`, `cooldownMs 1500` after an explicit Bare Hands choice. One transition per episode, accumulator reset after it, no call while lifecycle is already `off`. Takeover only while lifecycle is `active` (in `sleep` the hand drives nothing). Journal `input_arbitration.takeover {reason, distance_px, net_px, window_ms}`; aggregates only. Disable toast reads "Souris reprise — Bare Hands éteint" (reason passed to `disable`), not the generic stop toast.
- **Tools pointer/pan/select** leave the permanent strip in S03; reachable through the Selection > Bare Hands item's secondary activation (D4): a radial sub-arc of the installed tools, still `JarvisBarehands.tool(id)` -> `saveSettings({tool})`, `describeTools()`-driven, `aria-pressed`. The lifecycle HUD quick actions (help, diagnostic, calibration cards) and `Veille` move to the same secondary menu. `docs/barehands-contracts.md` § Palette rewritten (canonical selector moves).
- **BH reveal of the wheel:** no new gesture (O02). In ACTIVE the hand drives synthetic pointer events (F13); entering the left-edge hotspot with the hand pointer is the same `pointerenter` as the mouse; pinch = synthetic `click`. The wheel activates on `click` only (never `pointerup`), so a pinch fires once. "Two fingers toward the left" has no canonical gesture: deferred, Issue `Issues/bh-left-reveal-gesture.md` (S02).

## 5. D6 - Capture targets (S04)

- New Core route `GET /v1/captures/targets`, relayed as `GET /api/captures/targets` (`capture_relay.py`, read-guarded, 10 s): `{screen:{devices:[{token,label,primary,width,height}]}, audio:{devices:[{token,label,default}]}}`. Screen: `default` + `display1..N` from the same `WindowsDisplays.displays()` the source uses (`windows_display.py:169`), same order rule (`docs/capture.md` § Source policy). Audio: `default` (= Voice setting; label names the resolved device) + Core-side `sounddevice` inputs of the default host API, token = device name (stable across index drift; `device_from_token` accepts names, `sounddevice_recording.py:428`). Enumeration failure -> `{devices:[default]}` + journal `capture.targets_unreadable`, never an error page.
- The wheel sends `options:{device}` on start/screenshot; simple activation sends nothing (= `default`, current behaviour, O03).
- **Single entry rule:** when a channel lists only `default`, secondary activation still opens the sub-arc with that one informative, focusable entry ("Écran principal — seule cible disponible"). Never omitted silently, never a fake choice.
- No window capture, no all-displays, no system audio (`docs/capture.md` § Source policy V1).
- Video toggle: simple activation stops the open screen capture if exactly one; with several (one per display) the sub-arc lists each with its stop. Audio likewise.

## 6. D7 - Screenshot preview (S05)

| Action | Resolution | Part |
|---|---|---|
| Preview | thumbnail from `/api/artifacts/{id}/payload` (lazy `<img>`, CSS-bounded 240x135, `decoding=async`), 6 s, paused while hovered/focused, `Esc` dismisses; dismiss never deletes | S05.A |
| Open | minimal lightbox on the existing `.overlay` pattern (rank 60): full image + "Ouvrir dans un onglet" (same payload URL, same origin) | S05.A |
| Delete | `DELETE /api/artifacts/{id}` after `confirmDialog` (`.cdialog`, 85); refusal shown with its code | S05.A |
| Send to Jarvis | smallest real bridge: (1) Core `attachment_refusal` (`upload_service.py:499`) also admits `kind=screenshot`, `complete`, same `jarvis_session_id`; brief block unchanged (path, mime, readability recomputed by `with_agent_readability`). (2) `JarvisChat.attachExisting({artifact_id, original_name, mime_type, size_bytes})` adds a ready chip without upload. The action opens the Chat panel with the chip and focuses the input (text still required, `docs/chat.md`). No byte duplication. Agent contract change -> `agent-trace-analysis` on a real turn | S05.A |
| Annotate | implemented but gated (S05.B): canvas overlay (pen, 3 colours, undo, cancel, save); save = new Core route `POST /v1/artifacts/{id}/annotations` (PNG body <= 8 MiB, PNG magic sniffed, dimensions = original) creating a NEW `screenshot` artifact, `metadata.annotated_from`, relation `derived_from`, same Session/Context; original never touched. Button rendered only once S05.B passed QA; otherwise absent + Issue `Issues/screenshot-annotate.md` | S05.B |

Preview failure (payload 404/502/timeout) shows a typed placeholder, Open/Delete still work, capture state untouched. Placement: left zone above the bottom-left context zone (rank 38), never bottom-centre (status centre + board-drop tray).

## 7. D9 - Eye toggle (S06)

Choice (a): new toggle field `showHidden` (default `false`) in `JarvisSceneView.FIELDS` (`control_center_scene_view.js`), the existing canonical display-pref store (per browser, never sent to Core, like `showEphemeral`). A view decision, not a scene write; bulk-rewriting per-object `visibility` would lose which objects the user hid.

- `viewModel` (`control_center_scene_layout.js:1705`) gains `options.showHidden`: hidden objects with a placement are emitted with `ghost:true` (reduced opacity, dashed ring, accessible suffix "masqué"); still counted in `hidden`. Hidden objects without stored geometry follow the existing placement rule for visible ones (pure, tested); if unsafe, ghosts are limited to placed objects and the rest stay reachable in the list menu (documented).
- Ghost context menu: "Réafficher" only -> existing `showObjects([id])` (one `set_visibility visible`).
- Eye button (status centre, rank 40): `aria-pressed` = `showHidden`; label "Afficher les objets masqués (n)" / "Cacher les objets masqués"; count in label/tooltip only; focusable and inert-looking when `hidden === 0`. Secondary activation opens the existing `openHiddenMenu` (list + "Tout réafficher").
- The `sc-hidden` note leaves `renderStatus`; the other `.sc-status` notes stay bottom-left (F10). Interaction-mode rung selectors (F22) re-checked.
- Archived scene objects out of scope.

## 8. D10 - Active workspace rail (S07)

**Stage A (presentations, right side).**
- Core rail rows gain `preview: {artifact_id, kind:'presentation_still', width, height} | null` and `type: {engine}` (`presentation_studio_rail.py:209-226`). Preview = newest `complete` `presentation_still` `rendered_from` a snapshot of that presentation (`presentation_artifacts.describe_source`, F20). Bounded: computed at most once per presentation per change, cached in the rail service (key = presentation `updated_at` + latest render id); never a filesystem path. Absent -> typed placeholder ("Présentation · Remotion" / "Slidecar"); never a fake first slide.
- **Yellow "changed since reviewed": implemented, no SQLite migration.** Owner: Core rail service. Persisted as an additive optional key `unreviewed: {since, label}` in `rail.json` (schema stays v1: `parse_rail` ignores unknown keys, F19; an older Core drops the key on its next write and degrades to "not yellow" — documented in `docs/presentation-studio.md` › Rail). Set when the brain reports work `success` (`report_work`); cleared by a new rail action `review` (actor `user`) sent when the user opens the presentation from the rail or picks "Marquer comme vu". Precedence: `working` (blue) > `problem` (orange, own icon) > `unreviewed` (yellow) > `done` (green); unknown row -> muted dashed. A text label always accompanies the dot.
- Studio docking mirrors to the right: `html.jvr-studio #jvStudioExplorer:not(:fullscreen){right:<rail width>}` instead of `left` (`presentation_rail.js:132-135`); ranks 9100/9300/9400 unchanged. Brain `show_rail/hide_rail`, display-state report, `Alt+Maj+P` pin cycle, `shouldShow`, context menu actions unchanged.
- Width `--shell-rail-w`: 300 px (>= 1100 px), 72 px slim below 1100 (thumb + label on focus), toggle tab below 700 px.

**Stage B (Board-linked artifacts).** Pure adapter `control_center_workspace_rail_model.js` builds `WorkspaceRailItem` (`02-architecture.md` §7) from `GET /api/workspace/artifacts?board_id=<active>` (F21) for `upload`, `link`, `screenshot`, `screen_recording`, `presentation_*` renders. Previews: images/screenshots -> payload `<img loading=lazy>`; video, pdf, office uploads, links -> typed placeholder with type badge by `mime_type` / link host (`docs.google.com/presentation` -> Google Slides, ...). State from artifact `state` (`pending` working, `complete` ready, `failed`/`partial` problem); no yellow (no canonical review owner). Board switch (from `/api/status`) refetches, no leakage. Click: image -> S05 lightbox; others -> `JarvisWorkspace` artifact detail. Separate commit; can be cut to an Issue without touching Stage A.

## 9. Zones, tokens, geometry unification (S01)

- **One geometry, two skins.** Today the default theme and Cosmos place the same surfaces differently (F2), so every later slice would place each surface twice. S01 makes the Cosmos zone geometry the base for both themes (topbar left, launcher/dock as a top-right row, no vertical right dock); `circuit-board` keeps only its skin (colours, borders, fonts). `control_center_work.js` theme `STYLE` keeps no `position`/`top`/`right`/`left`/`z-index` rule for shell surfaces, except those listed in the registry with a reason.
- **Zones:** `top-left` state line (`.topbar`: `#boardsHud`, `.state`); `top-right` global launcher (`.dock`, S08); `left-edge` wheel anchor + wheel; `left-low` screenshot preview; `bottom-left` context zone (`#interactionModeHud`, `.sc-status` notes); `bottom-centre` status centre (recording indicators | `#bgPills` | eye); `bottom-right` `#chatTab`; `right` workspace rail (`#presentationRail`), chat/side panel over it; `centre` Board/scene.
- **Tokens** (`:root`, `docs/control-center-shell.md`): `--shell-gutter` 18 px (10 px < 700 px), `--shell-top-h` 40, `--shell-bottom` 18, `--shell-status-h` 44, `--shell-rail-w` 300/72/0, `--shell-anchor-w` 14, `--shell-wheel-r` 200, `--shell-wedge-min` 48 (target size), `--shell-glass-bg`, `--shell-stroke`, `--shell-focus` (2 px `--accent` outline, offset 2), semantic `--sem-alert` (orange), `--sem-done` (green), `--sem-question` (cyan), `--sem-working` (blue), `--sem-review` (yellow), `--sem-problem` (orange-red), motion `--shell-ease`, `--shell-dur-fast` 120 ms, `--shell-dur` 180 ms, all zeroed under `prefers-reduced-motion`.
- **CONTROL_SELECTOR:** every page control host carries `data-shell-control`; `control_center_shell.js` exports `CONTROL_SELECTOR = '[data-shell-control],#sceneLayer>.sc-status'`; `control_center_scene_page.js:2476` and the capture rail `OBSTACLE_SELECTOR` (`control_center_capture_rail.js:1144`) read it (fallback literal kept if the shell module is absent, journal `shell.missing`). Membership (must include): `.topbar>*`, `.dock`, `.live-banner`, `#bgPills` / status centre, `.panel`, `#barehandsHud`, `#barehandsPalette`, `#captureRail` (until removed), `#toolWheel` anchor, `#interactionModeHud`, `#chatTab`, `#presentationRail`, `#boardDropTray`, `#screenshotPreview`. Test: every host in the HTML with a registry row is matched.
- **Accessibility rules** (doc section): icon-only control -> `aria-label` + tooltip equal, never carrying a ticking counter; state never by colour alone (icon/text); one tab stop per group (roving), arrows, Home/End, Enter/Space native buttons, `Esc` closes the topmost transient; secondary = `contextmenu` / `ContextMenu` / `Shift+F10`; polite live region per module, timers in `aria-describedby`; focus never left on a hidden element; `forced-colors` mapping; 200 % zoom usable.

## 10. Layer plan (proposed registry; S01 encodes, later slices append)

Same ranks in both themes unless a row says otherwise. Existing ranks kept where they already work.

| Rank | Surfaces | Slice | Note |
|---|---|---|---|
| 0 | `.face`, `#cosmosFace` | - | |
| 20 | `#sceneLayer .scene` (internal 0-1000 and `.sc-status` stay inside its context) | - | |
| 21 | `.board-drop::before` | - | |
| 30 | `#toolWheel` anchor (closed), `#presentationRail` (right), legacy `#barehandsPalette`, `#captureRail` until removed | S02/S07 | |
| 31 | `.topbar` (state line + `#boardsHud`) | - | Cosmos today 45 -> 31 unless S01 finds the reason (git log -S) and records it |
| 32 | `.dock` launcher button(s), `#interactionModeHud` button, `#barehandsHud` (until S03), `#chatTab` | - | Cosmos dock/chat-tab today 50 |
| 33 | `.panel`, `#chatPanel` | - | Cosmos today 42 |
| 34 | `.board-drop-card`, `#boardDropTray` | - | Cosmos tray today 49 |
| 35 | `.live-banner` | - | Cosmos today 48 |
| 36 | mode chooser, BH lifecycle selector, `#boardsPanel`, launcher popover | S08 | `#boardsPanel` Cosmos today 51 |
| 37 | `#toolWheel` open + radial sub-arcs (Selection, targets, BH tools) | S02 | above choosers: the wheel is the user's latest focus |
| 38 | `#screenshotPreview` | S05 | |
| 40 | status centre: `#bgPills`, `#recIndicators`, `#hiddenEye` | S06 | |
| 55 | `.tl`, `.tlab`, `.mcpi`, `.wsp`, `.pfb` | - | |
| 60 | `.overlay`, screenshot lightbox, annotation editor | S05 | |
| 70 | `.toasts` | - | |
| 75 | `.bgpop` | - | |
| 80 | `.ctxmenu` | - | |
| 82 | `#barehandsCards` | - | |
| 85 | `.cdialog-back` | - | |
| 9000 / 9100 / 9150 / 9300 / 9400 | Variantes / rail in Studio / mode HUD during run (`html.jvx-run`) / rail menu / rail dialog | - | now listed (F4) |
| 2147483000 | `#jarvisHands` | - | |

Collapsing the Cosmos overrides changes relative order only where Cosmos had `topbar 45 > panel 42`; panel `top:64px` sits below the bar, so no visible change is expected; S01 runtime-validates both themes at 1440x900, 1280x720, 900x600, 600x800.

## 11. Test migration map (protect the invariant, not the string)

| Old assertion | Invariant | New assertion | Slice |
|---|---|---|---|
| `test_scene_renderer_logic.py:1376-1414` hard-coded selector list incl. `.voicehint` | every control > scene; documented relative order; Cosmos covered | `test_control_center_shell_layers.py` parses base CSS + Cosmos `STYLE` + module sheets, compares to the doc table; old test keeps scene/face asserts, drops `.voicehint` in S06 | S01, S06 |
| `test_control_center_mvp.py:74` "F9 · DÉMARRER" in html | wake key discoverable | `.state` carries the key hint description; F9 handler still bound | S06 |
| `test_control_center_mvp.py:94-108`, `test_interaction_mode_hud_js.py:1328`, `test_barehands_hud_js.py:985`, `test_prefab_library.py:497`, `test_control_center_mcp_inspector_js.py:821`, `test_presentation_studio_inspector_docs.py:117`, `test_control_center_timeline_ui.py` (dock entry) | each tool has an entry | keep `<nav class="dock">` and every button id inside it (launcher re-skins, does not rename); tests unchanged; if S08 must change markup, one shared helper `dock_entries(html)` replaces the six slicers | S08 |
| `test_interaction_mode_hud_js.py:1397,1469`, `test_barehands_contracts_js.py:194` | mode control dodges bottom-left badges/notes; aligned with the bottom baseline | rung selectors updated for removed `sc-hidden` note; baseline asserted against `--shell-bottom` instead of `.voicehint{bottom}` | S06 |
| `test_presentation_attention_browser.py:606` | attention cue visible at all widths | same check against `#bgPills` in the status centre | S06 |
| `test_board_alerts_browser.py:31` | pill opens popover | unchanged (ids kept) | S06 |
| `test_control_center_chat_ui.py:77`, `test_control_center_chat_browser.py:385` | chat panel never overlapped by the bottom hint | status centre visible and not intersecting the open panel (re-centres in free space) | S06 |
| `test_capture_rail_js.py:389-415` (host + `CONTROL_SELECTOR` literal) | capture controls are measured obstacles; host declared | host `#toolWheel` declared; `CONTROL_SELECTOR` from shell module contains wheel anchor; rail tests kept for the controller until S04 removes the rail view | S01, S04 |
| `test_barehands_palette_js.py` | tool choice one write path, `describeTools()`-driven, keyboard | same assertions against the Bare Hands sub-arc | S03 |
| `test_presentation_rail_e2e_browser.py:52,68` (rail right of palette; left of Studio) | rail never overlaps left controls; coexists with Studio | rail inside right zone, no intersection with launcher/chat tab; Studio explorer bounded by rail on the right | S07 |
| `test_boards_hud_js.py:924` (`#boardsHud` in `.topbar`) | Board control always visible | unchanged under D11 as resolved; migrates only on the Human fallback | S08 |

## 12. Risks

| Risk | Mitigation |
|---|---|
| Unified-chat branch changes before landing in `main` | D1: re-run S01 layer test after any re-merge; status centre/tray rule depends on `#boardDropTray` id only |
| Mouse=OFF return latency and camera LED flicker | measured in S03; fallback Issue (§4) |
| Multi-tab: Mouse takeover in one tab disables BH in all tabs (master switch) | intended (one physical camera); documented in barehands-contracts |
| Cosmos rank collapse hides an undocumented reason | S01 `git log -S` on each override before changing; keep with a written reason if found |
| Rail preview cost on 2-4 s polls | Core-side cache (§8); lazy images; no video decode |
| `rail.json` additive key lost on downgrade | degrades to not-yellow; documented |
| Send-to-Jarvis widens the attachment allowlist | only `screenshot`, `complete`, same Session; adversarial QA on foreign/other-session ids |
| Annotation route accepts browser bytes | bounded body, PNG sniff, loopback guard, derived artifact only; S05.B gated |
| Low-RAM host for browser suites | foreground chunked runs (project rule) |
