# QA-1 — Slice 07 Edit inspector UI (standard tier, frontend, user-visible)

Reviewed: `adc4d707` (5 S7 commits on base `bf94b352`), detached worktree `C:/Projects/jarvis/bipq` (HEAD checked before/after every step; clean at the end).
Isolation: own Core + Control Center per run (rig from `tests/fakes/presentation_studio_inspector_browser.py`, own `JARVIS_DATA_ROOT`), never the live Jarvis. No product code touched on any branch. No stash.
Skills used: qa-verification, code-review, runtime-validation, impeccable (critique), caveman.

**Recommendation to PM: REWORK** (3 BLOCKING, all small; the core design is sound). Decision stays with PM.

## Verdict summary

| Area | Result |
| --- | --- |
| Contract (contextual, generated widgets, semantic API only, no own persistence) | OK. grep: `widgetSpec` only table, no control-id branches, no `innerHTML`/`eval`, `localStorage` only `jarvis.studio_inspector.ui` {tab, preview}, no document key handler (only temp `pointerup/cancel` capture during a drag + `fullscreenchange`/`visibilitychange`). |
| Slice 08 entry conditions: drag, keyboard coalescing | Drag OK. Keyboard OK for slider and +/-. **FAIL for number-field arrows (B1).** |
| GUI/voice parity re-run with my own edits | OK, byte-identical durable doc (details below). |
| stale / 409 / 15 s / undo / hidden in run / sandbox / XSS / a11y | OK (details). |
| Dock changes | **FAIL: existing tests red + real overlap at narrow width (B2, B3).** |

## BLOCKING

### B1. Arrow keys / spinner on a number field commit once per press (one undo entry per keystroke, plus a self-inflicted stale)
- `jarvis/runtime/control_center_presentation_studio_inspector.js:1065` (`num.addEventListener('change', ... ev.commit(v,{immediate:true}))`) and `:1059-1064` (`input` -> preview only). In Chrome a `type=number` field fires `change` on every ArrowUp/ArrowDown/spinner step, so each press commits at once. The `IDLE_COMMIT_MS` coalescing exists only for the range element and the +/- buttons (`nudge`).
- Slice 08 entry condition (docs/presentation-studio.md "Slice 07 (inspector UI), entry condition"): "never one commit per keystroke (it would evict every earlier meaningful step)"; Slice contract/doc table: "keyboard steps ... one commit after 700 ms".
- Evidence (real Chrome CDP, real key events, integer `Inclinaison`, 5 x ArrowUp 60 ms apart, then 1.5 s): `commits` +5, history `{"undo":5}`; value 5. In another run the same gesture produced `commits` +4, `staleHandled: 1`, a 409 in the console and the field ended on 4 instead of 5 (second commit built with `if_current` of the pre-first-commit value, so it went `stale` against the inspector's own earlier write). Slow presses (500 ms apart) -> 3 presses = 3 entries. Holding the key (auto-repeat) would flush the 32-entry ring in about 1 s.
- Why not caught: node tests use a fake DOM (no native `change` on arrows); the real-Chrome file only drives the range with the mouse.
- Fix direction: on `change` while the field still has focus and the event came from a step (not Enter/blur), route through `ev.idle(v)` (arm the 700 ms commit); commit at once only on Enter/blur/focus-out. Add a real-Chrome test with ArrowUp x5 asserting exactly 1 commit (and no stale).

### B2. The tenth dock tool overlaps the Boards button at narrow widths (cosmos) and pushes a tool off-screen at 360 px
- `jarvis/runtime/control_center_work.js` (cosmos `.topbar`/`.bgpills` `right:422px`) + dock row 10 x 34 + 9 x 6 = 394 px.
- Existing `tests/unit/test_boards_hud_browser.py::test_in_cosmos_the_dock_never_covers_the_boards_button_nor_the_voice_state[500-700]` **fails at `adc4d707`, passes at base `bf94b352`** (I ran both): Boards rect r=98.75 vs dock row l=96.
- My geometry sweep (cosmos, `JarvisThemeAPI.activate('cosmos',{persist:false})`): Boards button right edge 138 px @520 wide, 158 @540, 161 @560+; leftmost dock button (AGT) left edge 116 @520, 136 @540, 156 @560: overlap 22 px @520/540, 5 px @560, clear from ~600. At 360 px the row spans -44..350: the AGT button is entirely off-screen (base: -4, still reachable). The implementer sized the media query tiers by HEIGHT only (520 px high) and the doc Human check #8 says "360 px: no horizontal scroll, no too-small target".
- Not an issue at 1280x720, 1024x600, 800x600, 720x640 (non-fake pills), 900x520, 900x500, 1280x560 for dock-vs-HUD/band/Boards (all `hits` empty apart from the `.topbar` container box vs pills, which is base behaviour).
- Fix direction: at <= ~600 px wrap/shrink the row (e.g. 30 px buttons, or two rows) or move the Boards button; run the Boards HUD browser file.

### B3. Another existing test is red and was not updated
- `tests/unit/test_control_center_mcp_inspector_js.py::test_the_served_page_carries_the_dock_button_the_dialog_and_the_module` : `assert order == ["ERR","TRC","LAB","CNV","SET","MCP","WSP","PFB","AGT"]` now sees `INS` (fails at `adc4d707`, passes at base). Update the expected order (legitimate change, the implementer simply missed the file). Shows the dock-touching suites were not all run (see B2).

## POLISH

- **P1. Ctrl+Z with a pending keyboard step on a slider undoes an OLDER entry and leaves the draft alive.** `onPanelKey` (`:1630-1643`): only a dirty *text field* keeps the browser undo; a dirty range goes to `runHistory('undo')`, which clears the timers (`:1522`) but leaves `dirty`. Real Chrome: commit tilt, focus size slider, ArrowRight x2, Ctrl+Z -> tilt undone, size still `aperçu · non enregistré`; Tab -> the draft commits (`size 1.02`) and **the redo entry is gone** (`{"undo":1,"redo":0}`). Expected: Ctrl+Z on a dirty control abandons the draft first (like Escape). Ctrl+Z with focus outside the panel does nothing (verified).
- **P2. Cramped at low height; two clips.** 1024x600: pick + preview + tabs + DA chip + (when waiting) reload card use about 70 % of the panel; only one control row visible (screenshot `layout-1024x600`, `orb-1024x600`). The `.jvi-top` region (`max-height:36%`, `:73`) clips the reload card's bottom border and the clock line ("tentative 1/5 · prochaine dans 1 s" cut). The preview slot (`clamp(96px,21vh,240px)` = 126 px at 600 px) clips the orb at `size` 1.8 (the "clipped orb" the implementer mentioned is still there at 1024x600; fine at 1280x720 and 360x740). The reload card button itself is visible and unclipped at 1280x720 and 360x740 (checked after the fix). Suggest: preview collapsed by default under ~640 px height, DA chip folded into the header, top region not height-capped.
- **P3. Voice-started run window (<= 5 s).** I started a run through the relay while the panel was open and clicked a switch at once: the commit **succeeded**, the run went `paused` (Core listener, documented), and the panel hid at the next player poll (<= 6 s). Safe and consistent with Core's contract, but the user's tweak silently pauses a run the voice just started. Cheap improvement: `JarvisStudioPlayer.refresh()` on `pointerdown`/before a commit. Acceptable as is.
- **P4. Background pills.** Non-cosmos vertical dock: pills now start at `50% + 317px`; at 1280x720 only the first of 3 pills is on screen (base: 2 of 3). Cosmos @720x640: a row of 3 pills overlaps the Boards button (the row moved 40 px left). Only when 3 categories are unseen at once.
- **P5. Discrete enum via keyboard commits per arrow.** Segmented `radiogroup` arrows (`choose`, `:1124`) and a closed `select` ArrowDown commit each step: cycling 6 easing values = 5 undo entries. It is what the docs table says ("commits at once") but it is the same ring-eviction risk as B1 for keyboard users. Consider idle-commit for arrow traversal.
- **P6. Small robustness.** `roundTo` caps decimals at 8 (`:277`): a range narrower than ~1e-6 derives a step that rounds the value to 0 (nudge no-ops). The JSON widget parses on every `input` event (a multi-MB paste janks the page). Messages mix decimal point ("Doit être au moins 0.6") with the French comma shown in the field ("1,8").
- **P7. Module size.** 1,777 lines, one closure of ~1,400 lines. Recommend a split in a later Slice (not blocking): CSS + pure helpers (`widgetSpec`, `validateValue`, `setAtPath`, `diffControls`, about 300 lines, already exported for node), widgets (`*Widget`), session/queue/commit machinery, status/reload UI. Siblings: player 611, prefab host 858.
- **P8. Test and comment hygiene.** `test_control_center_timeline_ui.py` comment says `10 x 44 + 9 x 6 = 498 px`; it is 494 (margin 14, not 12). The PM brief says `test_presentation_attention_browser` expectations were edited; the diff does not touch it (it passes, 31/31). Mutation 4 below shows the default `playing()` implementation is covered only by the real-browser test (node tests inject `playing`).

## Existing test edits: legitimate?

- `test_control_center_timeline_ui.py` (9 -> 10 tools, `INS` in the name list, `right:422px`, `top:calc(50% + 317px)`, `+ 261px`): legitimate arithmetic updates (10 x 34 + 9 x 6 = 394 + margin; 10 x 52 + 9 x 10 = 610 -> 305 + 12 = 317). Not weakened. Only the 498 comment typo.
- `test_presentation_studio_docs.py`: the "no `art_direction` in any `presentation_studio*.py`" rule now allows exactly one occurrence in the relay file and asserts the exact `("GET", "studio_art_direction"` route. Narrowly scoped, still forbids any write route. Legitimate.
- `test_presentation_studio_edit_routes.py`: +1 test (GET relays 200/404 verbatim, PUT/POST/DELETE are 404/405, Origin null / cross-site / foreign Host = 403). Good (I re-ran: 19 pass).
- Not updated though they should be: B2, B3.

## Contract checks (evidence)

- **Parity, my own edits** (GUI on presentation B through the real page, same ops as actor `brain` on presentation A): title text (type + Enter), colour hex `#12ab34`, gradient stop 2 `#ff0000` (hex field), boolean switch, segmented enum `left`, integer `+` stepper, `select` ArrowDown (`ease-in`), number `2.5`. Durable variant files identical after masking ids/revisions (only the presentation titles differed). History after the GUI run: 8 undo entries = 8 edits. Reset: GUI `size` 1.4 then `↺`, switch then `↺` vs brain `control.set` + `control.reset`: **identical** durable docs.
- **Drag** (real mouse events through CDP, 60 moves, 25 ms apart): 22 previews, 38 coalesced, variant file SHA-256 identical before / mid-drag / (draft listed `["size"]`), exactly 1 commit after release, history `{undo:1}`. Range keyboard: 6 ArrowRight 60 ms apart -> 0 commits during, 1 after 700 ms. `+` x5 -> 1 commit.
- **Stale**: user typed `#aa0000` (dirty) while another writer set `#00ff00` on the same control; Enter -> "La présentation a changé ailleurs avant votre réglage : il n'a pas été appliqué. Valeurs relues : Couleur d'accent : #6ee7ff -> #00ff00." with `Réappliquer ma valeur (#aa0000)` and `Fermer`; stored value stayed `#00ff00` (nothing overwritten). (Screenshot `stale-1280x720`.)
- **409 reloading**: scene guard forced "always reloading": card "Rechargement en cours ... tentative 1/5 · prochaine dans N s" with spinner and `Arrêter d'attendre`; click -> "Attente arrêtée : rien n'a été enregistré." + `Réessayer`, value unchanged. Schedule 0.8+1.5+2.5+4+6 = 14.8 s code-verified (`RELOAD_RETRY_MS`), and the real-Chrome file's retry-then-commit test passes.
- **Deadline / Réessayer / history unavailable**: covered by node tests (pass) and by code (15 s `AbortController`, `HISTORY_TEXT`); not re-driven with a real silent Core (see Not verified).
- **Undo/redo**: `expected_entry_id` passed from `S.history.next_undo/next_redo` (`:1524`); Ctrl+Z/Y handled only on the panel's own `keydown`; Ctrl+Z with focus on `body` did nothing.
- **Hidden in run**: real run via relay: panel hidden+inert, dock disabled with reason, drafts dropped, comes back closed (existing real-browser test passes 3/3). Voice-start window: see P3.
- **Preview mechanism**: runtime check in the live page: preview iframe `sandbox="allow-scripts"`, `referrerpolicy="no-referrer"`, no `allow`, no `src`; srcdoc CSP `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'`; `contentWindow.document` -> SecurityError (null origin). Diff touches no prefab host / protocol / shim / Core file (stat of `jarvis/prefabs`, `control_center_prefab_*`, `jarvis/core`, `jarvis/protocol` is empty): sandbox, CSP and `jv:1` untouched. Relay: `GET .../art-direction` with `Origin: null` -> 403; normal -> 200; read-only (PUT/POST/DELETE 404/405 in the test); actor forced `user` by the existing relay.
- **XSS / injection** (real Chrome, hostile data through the real routes): control label `<img src=x onerror=window.__pwn=2>`, meaning `<script>window.__pwn=3</script>...` and `<b onmouseover=...>`, enum values `<img onerror>`, `javascript:alert(1)`, RTL override `U+202E`, 40-char values, string value `<img onerror>`, body `<svg onload>`+250 chars. Result: `window.__pwn` undefined, 0 injected `img/script/svg/b` elements in the panel, text shown literally, no horizontal overflow (panel 418 px, page 1280). `javascript:` URL: Core refuses (`must be an http(s) URL`) and the client refuses first (`URL http(s) attendue`). JSON array widget with `[{"__proto__":{"polluted":1}}]`: `({}).polluted` undefined, Core refuses ("reserved key name"). Label/meaning length are bounded by Core (<= 40 / <= 160), so "huge strings" are server-bounded; the field `maxLength` is 2 x `max_length` and the counter says the exact limit. Art-direction hostile name could not be stored (Core caps 80; my 185-char attempt was refused); by code review the chip uses `textContent` only and swatches are `#rrggbb`-guarded. Not driven at <= 80 chars.
- **Number / colour validation**: `0.5` (min 0.6) -> "Doit être au moins 0.6. Rien n'a été enregistré." (0 requests); `1e400` -> "Saisissez un nombre."; `1,5` accepted (1.5); integer `2.5` -> entier message; `99` > 15 refused client-side; colour `#abc` and `#GGGGGG` refused client-side with "Rien n'a été enregistré"; `code` `abcd` -> length counter message; no request left the page for any of these (commits/previews counters unchanged).
- **Theme "non appliqué" 10 vs 5**: `shim.js:49` `THEME_VARS` = accent, text, muted, surface, scale (5, applied at `:220-223`); `ALLOWED_THEME_VARIABLES` (`presentation_studio_art_direction.py:477`) = 15. 15 - 5 = 10 and the module's `NOT_APPLIED_THEME` lists exactly those; claim **correct** (and a test pins it). Note the inspector's own preview card applies no theme at all, so "appliqué" means "reaches the projected scene frame" (the chip's sentence says so).
- **Accessibility**: axe-core 4.x (local copy from another repo's `node_modules`, no CDN) run on the open panel on all 4 tabs and on the dock: **0 violations** each (colour contrast included); the real-Chrome file asserts names/roles/tab order. Focus ring `2px var(--accent)`; targets >= 28 px (steps 30, reset 28 x 28); `prefers-reduced-motion` stops the spinner (test passes). Not checked: a screen reader.
- **Keyboard vs presentation navigation**: panel `keydown` stops propagation of unmodified keys; typing, Enter, arrows, Home/End in widgets did nothing outside (own runs + `test_..._keys_go_to_the_player`). No document-level key handler.

## Design critique (impeccable), from the screenshots I took (1280x720, 1024x600, 360x740)

- **Hierarchy / consistency.** The panel reuses the Control Center tokens (same slot, border, mono caps for section labels, accent cyan); `INS` sits in the dock with a coherent slider icon and an active state. Header (title, undo, redo, close) is clean; tab bar with counts reads well; rows are label + state + reset on one line, meaning under it, then the control, then the default; clear and scannable at 1280x720.
- **Density.** The top stack (scene picker, 180 px preview card, DA chip with 3-4 chips) takes about half of a 720 px panel before the first control; at 600 px high it leaves about one row (P2). The DA chip repeats on every tab although it is not about the current group; the chips `GÉNÉRÉE` / `REPLI` / `DA · RÉV. 1` are terse for a non-expert (what is "repli"?).
- **Empty / error states.** Stale card (orange text, two plain buttons, toast duplicating it) is clear but the toast lands on the dock's `AGT` button (existing toast placement). Reload card: spinner + plain sentence + countdown is good; clipped under height pressure (P2). Empty list and no-control scene have helpful French sentences (node tests).
- **Preview.** The live prefab frame follows the draft at once and is labelled "Aperçu local : rien n'est écrit avant le relâchement" (honest). Orb clipped at 1.8 x on a 600 px high screen.
- **360 px.** Panel 272 px wide, tabs scroll horizontally (the "Mouvement" tab is cut but reachable), no page overflow; but the dock row is clipped on the left (B2).
- **Controls.** Slider + number + steppers, native colour swatch + hex, segmented radiogroup and switch are consistent in height and radius; the gradient editor (bar + swatch/hex/up/down/remove per stop) is the densest widget but readable. The tiny `↺` reset glyph has only an aria-label (no visible text), muted at rest: discoverable only by hovering; acceptable.

## Runtime evidence: test runs (one file at a time, `bipq`, `adc4d707`)

| File | Result |
| --- | --- |
| inspector_js / inspector_behaviour_js (34) / inspector_docs (9) | 9 / 25 / 9 pass |
| inspector_browser (12), 3 consecutive runs | 12 / 12 / 12 pass (about 103 s each) |
| presentation_studio_edit, edit_docs, edit_overlay, edit_routes (19), edit_service | all pass |
| history, history_crash, history_docs, history_routes, history_service | all pass |
| player_js 27, player_browser 4, reload_core, reload_domain, reload_host_js, reload_page_js, reload_routes, reload_service, reload_integration, reload_browser 23, reload_real_page_browser 2 | all pass |
| `test_presentation_studio_reload_docs` | **1 fail**: `docs/conversation-events.md` row/note numbering ("10. **Presentation Studio scene hot reload" expected, note is 11). Not touched by S7 (diff has no `conversation-events.md`; base holds the same note 11). Pre-existing Slice 06 inconsistency (ISSUE I3). |
| `test_presentation_studio_player_realpage_browser` | S7: run 1 = 2 failures (band vs HUD @1920x1080, fullscreen keys), run 2 = 1 failure, runs 3-5 = 5/5 pass (39 s). Base: 5/5 once. Looks load-flaky (my first runs overlapped other sessions' Chrome work: one foreign Chrome was active). Unattributed; recommend the PM re-run it alone (ISSUE I4). |
| `test_presentation_attention_browser` | 31 pass |
| `test_control_center_timeline_ui` 13, `_appearance`, `_catalog_ui`, `_mvp`, `_presentation_status`, `_quality`, `_testlab_js`, `_timeline_js`, `_voice_architecture_ui_review`, `_timeline_browser` | pass |
| `test_control_center_mcp_inspector_js` | **1 fail (B3)**, passes at base |
| `test_boards_hud_browser` | **1 fail (B2)** `[500-700]`, passes at base; the other 9 pass |
| `test_boards_hud_js`, `test_prefab_browser_js`, `test_prefab_library`, `test_scene_renderer_logic`, `test_workspace_manager_browser` | pass |
| `test_capture_rail_js` 60, `test_capture_rail_browser` 23 (+1 skip), `test_interaction_mode_hud_js` 48 | pass |
| `test_interaction_mode_hud_browser` | 1 fail `reduced_motion_arrete_vraiment_le_halo`; **same failure at base** (pre-existing, Chrome-version dependent; ISSUE I5) |
| `test_documented_routes` 3, `test_v2_architecture` 8, `test_capture_relay` 35, `test_prefab_relay` 22 | pass |

## Mutations (5, riskiest first; each restored with `git checkout`, `git status` clean, HEAD `adc4d707`)

1. Commit on every move (range `input` -> `ev.commit`): **killed** (`test_a_sixty_move_drag_...`).
2. Actor not `user` (inspector sends `actor:'brain'` + relay `setdefault`): **killed** by `test_presentation_studio_edit_routes` (2 tests) and `behaviour_js` sixty-move test. The S7 real-browser parity tests alone did NOT catch it.
3. Previews write (`postEdit('commit')` in `sendPreview`): **killed** (`behaviour_js` sixty-move test).
4. Panel visible during playback (`playing()` returns false): **survived** node tests (25 pass), **killed** by the real-browser `test_while_a_run_plays...` (45 s). Real coverage exists only in the slow browser file (P8).
5. Stale overwritten (`stale` classified as `applied`): **killed** (2 behaviour tests).

## Docs honesty

- `docs/presentation-studio.md` "Edit inspector UI" is thorough and, apart from the items below, matches the code (constants, table, decisions). The row "type in a text / URL / number field ... one commit on Enter, blur or `change`" documents the very behaviour that breaks the entry condition for arrows (B1).
- "Human check 8: 360 px, no too-small target" is not true for the dock (B2).
- `OPERATIONS.md` Human check is useful; add "keyboard ArrowUp on a number field leaves one history entry" once B1 is fixed.
- The brief's claim that `test_presentation_attention_browser` was edited is inaccurate (P8).

## Questions answered by PM (recorded)

- No page-to-server log route now: console `[studio-inspector]` + relay journal suffice. Agreed.
- Manifest/introspection carrying `unit`, `step`, enum labels, array item schema is a shared prefab-contract change: **ISSUE I1**, later Slice, not this one.
- GET-only art-direction relay confirmed (verified read-only, origin-guarded, actor `user`).
- `last_recovery` route later (**ISSUE I6**).

## ISSUES (non-blocking, for the PM log)

- I1. Manifest `InputSchema` has no `unit`/`step`/enum labels/array item schema; step is derived, JSON editor for non-colour arrays.
- I2. Inspector reads only the first listed presentation's active variant (Slice 18 owns variant choice) - by design.
- I3. `test_presentation_studio_reload_docs` red on `conversation-events.md` note number (pre-existing, Slice 06 area).
- I4. `test_presentation_studio_player_realpage_browser` intermittent under load.
- I5. `test_interaction_mode_hud_browser::reduced_motion_arrete_vraiment_le_halo` red at base too (headless Chrome version).
- I6. Recovery report still has no route.
- I7. The shared TEMP is full of leaked `jarvis-*-cdp-*` profile dirs from older harnesses (about 980 left, none mine; the inspector harness cleans its own). I removed about 105 stale dirs created during my runs (older than 12 minutes, none in use) and my own `q7*`/`qa7*` scratch dirs. C: free space 42 GB before and after.

## Not verified

Real touch / pointer device; hold-key auto-repeat on a number field (inferred from B1); a silent Core for the 15 s deadline (node tests only); cosmos-theme screenshots with the inspector open; art-direction name with hostile text <= 80 chars; screen reader; multi-MB JSON paste; Slice 06 QA-2 fixes / Slice 11 / Slice 17 interplay (not in this base); 3 simultaneous pills on real alerts.

## Artifacts

Private scripts and screenshots (not product): `C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/2c31ce96-dd64-4b96-839c-feff87315a95/scratchpad/qa7pq/` (`drill.py`, `shots/*.png`).
