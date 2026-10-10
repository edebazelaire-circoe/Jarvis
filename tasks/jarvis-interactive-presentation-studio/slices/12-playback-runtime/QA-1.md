# QA-1 - Slice 12 (playback runtime) - standard tier, user-visible runtime

QA agent. Worktree `C:/Projects/jarvis/bipq`, detached at `6aec096f` (HEAD checked before/after every step, `git status` clean at the end). Diff reviewed: `727ebb11..6aec096f` (9 S12 commits, 44 files). No product code modified on any task branch, no stash, no bips/bia/bi8/bif/bipr use (bips read-only; this file is the only file created there).

**Recommendation: REWORK (1 BLOCKING, the windowed keyboard does not work on the real Control Center page).** Everything else is POLISH or carry-forward ISSUE. The state machine, R5, R6, kill reclaim and the relay are solid.

## 1. Verdict summary

| Area | Result |
| --- | --- |
| State machine / contract | PASS. 20 000-event random walk (all event kinds, invalid args, huge/odd targets): 0 invariant breaks, 0 state change on refusal, generation monotonic, `where` bounded. |
| R6 variant never mutated | PASS. sha256 of every file under `presentations/<id>/` identical before/during/after: full run with control_set, reveal, detours, undo, sequence, 3000 concurrent mixed commands, 200-item score. Explicit `edit` verb: run pauses, variant revision moves (4), stage follows. Undo during run: run pauses. |
| R5 cue authority | PASS. 20-body fuzz of `/cues/satisfied`: only exact `{run_id, generation, cue_id}` reaches the machine (400 otherwise, `text` / extra / `__proto__` / bool / float / str-gen / bad ids). stale_run, stale_generation, not_armed, duplicate (`duplicate:true`, no second advance) verified live. |
| Relay | PASS. `/playback/armed`, `/cues/satisfied`, `/playback/../armed`, `%61rmed`, `/notify`, `/Start`, `POST armed` all 404; Origin `evil`/`null`/Host `evil` all 403; actor forced `user`, `origin: ambient_text` refused 400. |
| Kill drill | PASS (see 4). Corrupt ledger = visible orphans forever (P3). |
| Windowed keyboard on the real page | FAIL (B1). |
| Detour of bad prefab | POLISH (P2). |
| Chrome profile leak fix | PARTIAL (P7). |

## 2. Findings

### BLOCKING

**B1 - Arrow keys, Home, End (and windowed Escape) do nothing on the real Control Center page.**
`jarvis/runtime/control_center_presentation_studio_player.js:363-389` (`handleKey` returns on `event.defaultPrevented`; listener on `document.body`, bubble phase) vs `jarvis/runtime/control_center_scene_page.js:2257-2293`: the scene page's own keydown handler on the focused window node runs first and calls `event.preventDefault()` on ArrowRight/Left/Up/Down/Home/End (focus-navigation between scene nodes) and on Escape (blur). The player therefore never sees them.
Evidence (isolated real Core + real Control Center + headless Chrome via CDP, `drill_c`): click the stage window (host focused, `tabindex=-1` applied), then real CDP key events. A document-level bubble logger shows `dpAtDocBubble:true` for every key. Result per key: ArrowRight/ArrowDown/ArrowLeft/Home/End -> no command (`stats.keys` stays 0, position unchanged); PageDown, Space, `p` -> work; Escape -> windowed: blurred, no pause. Fullscreen arrows DO work (the fullscreen module's capture handler on the host element: command sent, `fs_right`).
Why tests are green: `test_presentation_studio_player_browser.py` uses a synthetic page with a fake core and no scene page keydown handler. The band hint (`player.js:174` "← → Espace ... P ou Échap ... Début / Fin"), `docs/presentation-studio.md` and `docs/OPERATIONS.md` Human check 1 all promise keys that fail windowed.
Fix direction (not applied): handle in capture phase on the stage host (as `control_center_fullscreen.js:461` does) and `preventDefault` + `stopPropagation` for the handled keys only; add one browser proof against the real scene page (or at least with `control_center_scene_page.js` loaded).

### POLISH (priority order)

**P1 - Band covers the interaction-mode HUD.** `#jvStudioBand` is `position:fixed; left:18px; bottom:18px; width:min(580px,...)`, z-index 34 (`player.js:63`). Measured at 1400x900: band rect `[18,660,580,222]` overlaps `interactionModeHud@18,818,168x60` (screenshot `b1_started.png`: the PRESENTATION indicator is dimmed under the band). During a run the user cannot see or reach the mode control (and "change the mode to stop the run" is the documented escape). Relevant to the legacy/duplex question (below): the only place that reports `Refusé par la voix` is that HUD.

**P2 - Invalid detour = HTTP 500 `stage_failed` + phantom detour.** Unknown prefab / unknown version / bad props (user- or brain-reachable input errors) pass the machine (`_detour`, domain `playback.py` ~386-399) and fail at staging (`core/presentation_studio_playback.py` `_show_aux` 607-614 -> `_execute` except at 402-411): response 500 `prefab_invalid`, state stays `detour` with depth 1 and no window, `next`/`previous` refused `in_detour`, `pause` illegal, until the user presses return; `problems: [aux_stage_failed]` then stays for the rest of the run (never cleared). Evidence `drill_f`/`drill_e`. Fix direction: validate the pin (and props) before the transition and answer 4xx, or roll the transition back and clear the problem.

**P3 - Unreadable/corrupt ledger leaves visible orphans forever and is silently overwritten.** `presentation_studio_stage.py:72-84` (`load` -> `[]` + error row) and `file_presentation_studio_stage_ledger.py:44-58`. Drill: run + 2 detours, kill Core, truncate ledger, restart: Core starts (tolerant, good) but `studio-stage-*` + 2 `studio-aux-*` stay VISIBLE; the next run's first `ledger.add` overwrites the corrupt file (evidence gone, run result says `problems: []`). Needs two faults (atomic write makes the second rare), but the asymmetric risk is a visible leftover on a projector. Suggest: move the bad file aside (`.corrupt`), and as fallback reclaim by `category in {studio_stage, studio_aux}` AND id prefix `studio-` (namespaced, not a free filter), or at least surface the error row on screen. Also: the ledger trusts any id string (no `studio-` prefix check) - a hand-edited file archives any object.

**P4 - Stale ids stay in the ledger after the user closes the stage.** `presentation_studio_stage.py:156-171`: user archives the stage mid-run -> a new `-1` window is created (good) but the old id stays in the ledger; after a clean `stop` the file is NOT erased (`{"object_ids":["studio-stage-2e93bc4fb8b3"]}` observed). Harmless (reclaimed next start with `unknown_is_gone`) but it contradicts the doc ("erased as soon as taken back") and Human check 5 ("le fichier a disparu"). Remove superseded ids on regeneration.

**P5 - `_own_edit` is a service-wide flag** (`core/presentation_studio_playback.py:159, 709-713, 735`). A foreign commit (inspector, undo) landing while the run's own `edit` is in flight is ignored by `_on_edit_committed`, so no pause/sync for it. Narrow race; use a per-call token.

**P6 - No `pending` shown + docs overclaim on voice architecture.** (a) `where` carries `pending` but the band never shows it: after Pause on an `at_boundary` item the band still says "En cours"/"Pause". (b) `docs/presentation-studio.md:685` says on legacy/duplex "`user_presenter` and silent rehearsal cannot start; the refusal reason is shown"; `:849` says Core cannot see it. They contradict; the code matches `:849` (see section 5).

**P7 - Chrome profile leak fix is partial.** `tests/unit/_fullscreen_browser.mjs:135-140` (await exit + `rmSync` retries) works for most launches: 20 player-browser launches (5 runs x 4) left nothing; but the 8-test `test_fullscreen_browser.py` run left one 13 MB `jarvis-fs-cdp-*` dir (I removed my own). `chrome.kill()` kills the parent only on Windows; child processes keep the profile. Suggest `taskkill /PID /T /F` (tree) before `rmSync`. 57 older `jarvis-fs-cdp-*` (and many `-pa-`, `-cr-`, `-im-`, `-ww-`... from the other harnesses) still sit in `%TEMP%`: out of scope but the same leak.

**P8 - Smaller.** Unused import `Verb` (`core/presentation_studio_playback.py:50`). `where` measured 2378 bytes (ensure_ascii, Core fields included, max-length accents) vs `MAX_WHERE_BYTES = 2048` for the machine part: bounded but the 2048 claim is for the pure part only; say so. Idle page polls `GET /api/presentation-studio/playback` every 5 s on every Control Center page load for everyone (12 req/min, acceptable; note). A Space/Arrow on a focusable button *inside* the stage host would navigate and `preventDefault` the button (no such button today). `parse_detour` accepts any `props/data` size up to the body limit before the scene refuses.

### ISSUE (carry-forward, not Slice 12 defects, or needs PM decision)

**I1 - Locked sequence wedges a run until Slice 14.** No component sends `sequence_done`/`abort`/`boundary` (`notify` is Python-only). At a host item (`score` of `drill_a`): `next`/`previous`/`goto`/cue -> `locked_sequence_active`; `pause` returns *applied* but only sets `pending=pause` (phase stays playing, no executor ever delivers the boundary), `resume` -> `illegal_transition`; a detour is queued as `pending` and never shows. Only Stop works. By design per docs `:775`, but the refusal message tells the user to "wait for it, abort it" and there is no abort verb. Until Slice 14 lands, say so in the band/doc and consider a user-reachable `sequence_abort` (the machine already supports it).
**I2 - Tool Brain ownership refusal test** belongs to Slice 21 (PM). Today `SceneStage` writes as `SceneActor.USER` straight through `apply_if`; with `JARVIS_TOOL_BRAIN=active` nothing arbitrates (doc says so). Not exercised.
**I3 - Slice 09 gate not merged.** `hasattr(... "require_art_direction")` -> `None` -> run says `art_direction: "unchecked"`, band line "Direction artistique non vérifiée.", warning trace, `docs/legacy/...gate.md` with removal condition. HONEST. I compared the port signature with `feat/ips-s09` (`git show`): `require_art_direction(presentation_id, variant_id, *, serious=True) -> {status, fallback, art_direction}` matches; `resolution.get("fallback")` and `art_direction.revision` use existing keys (revision key inside `to_document()` not checked on that branch).
**I4 - Pre-existing red (not S12):** `test_interaction_mode_hud_js.py::test_no_new_settings_surface` fails at `727ebb11` too (it forbids any `/api/presentation*` route in the Control Center; Slice 05's relay already broke it). Not in BASELINE. `test_interaction_mode_hud_browser.py::test_le_mouvement_reduit_arrete_vraiment_le_halo` = baseline red.

## 3. Evidence, tests (one file at a time, `PYTHONPATH=bipq`)

New S12 files: playback 245 passed; playback_docs 8; playback_routes 10; playback_service 39; stage 13; edit_overlay 7; player_js 18; player_browser 4 (x5 runs: 4/4 each, no flake). All other `test_presentation_studio_*` (24 files) and `test_presentation_staging_contract` green. conversation_events 142, control_center_timeline js 71 / ui 13 / browser 3, fullscreen browser 8 / commands 36 / js 36, documented_routes 3, v2_architecture 8, prefab_relay 22, capture_relay 35, board_service 26, interaction_mode contract 100 / control_plane 100 / follower 7 / protocol 12 / hud_js 47+1 red (I4) / hud_browser 12+1 red (baseline). scene_service 38, scene_service_prefab 18, prefab_events 26 green. Total reds: 2, both pre-existing.

## 4. Runtime drill (own `JARVIS_DATA_ROOT`, ports 28653/28654, never the live Jarvis; short root: a long root hit the 259-char Windows limit, noted)

Real `JarvisCoreApplication` + `LocalProtocolServer` + real `ControlCenter` (scene + mode views wired) + headless Chrome via CDP. 6-scene presentation, score with 2 cues, control_set/reveal actions and a locked sequence host item.

- Start (relay), band in Chrome ("Vous presentez - En cours - Scene 1/6 - Ensuite : Deux - dites << passons a la suite >>"), stage window `studio-stage-<run>` on the scene with the score overlay (`OVERLAY-1`, variant byte-identical). Navigation, pause, detour (aux window appears on the scene, retired on return/stop), fullscreen via the band (host fullscreen, Escape exits, run unchanged), stop: scene objects retired. `JarvisFullscreen` state `exited`.
- **Windowed keys: B1.** Fullscreen keys: OK, one command per key.
- **Kill drill:** (a) `user_presenter` + 2 stacked detours, ledger `{"object_ids":[stage, aux-a1, aux-a2]}`, `Stop-Process -Force` of the Core+CC process, restart: objects 0, ledger file gone, archived tombstones present, mode back to assistant. Repeated for `jarvis_presenter` and by accident for a plain playing run: same. (b) corrupted ledger: Core up, error row, 3 objects stay visible (P3).
- **Mode:** user change of mode during `user_presenter` and `jarvis_presenter` -> run stops (`reason: mode_changed_by_user`), aux retired, user's choice kept.
- **Adversarial:** 3000 concurrent mixed verbs (next/prev/pause/resume/goto/reveal/hide/detour/return) on a 200-item / 64-scene score: 15.9 s, all answers coded (409 in_detour/illegal_transition/paused/aux_stack_full/at_start), 727 applied, final state consistent (stage only, all aux archived), `where` 2378 B, variant hash unchanged, stop leaves no studio object. Illegal transitions: every table cell answers coded, never a 500 (except P2). Armed set churn: generation moved to 243, pull 229 B for 1 cue. Reports for wrong run/generation/unarmed cue refused; duplicate idempotent. User closing the stage/aux window mid-run: stage re-created as `-1`, aux retire tolerant (P4).
- Origin guard on relay: evil origin / `null` / foreign Host: 403 on GET and POST (a hostile prefab frame cannot drive playback).

## 5. Judgements asked for

- **Per-run stage window (`studio-stage-<run_id>`) vs PM brief "per presentation": ACCEPT.** An archived id keeps its tombstone and can never be re-created (`scene.py` `patch rewrites archived object`, `object_archived`; `scene.py:1322-1343`), so a presentation-scoped stable id could only live until its first archive; the run-scoped id plus `-n` regeneration is the working form of the PM's own rule ("patch, do not create+archive per slide"): one create + one archive per run, patched per scene (verified: same `stage_object_id` across 200 navigations). Cost: 1 tombstone per run (+1 per aux), ledger capped at 16 ids.
- **Detours = prefab windows only:** accepted; resource references not displayed (documented).
- **Tool Brain ownership refusal:** left to Slice 21 (I2).
- **Legacy/duplex voice architectures and `user_presenter`: NOT a visible refusal.** Core cannot see it (the Voice report goes to the Control Center HUD, `control_center.py:3328`, not to Core); the run starts, mode goes to PRESENTATION, the cue follower is deaf. The only signal is the mode HUD `Refusé par la voix`, which the band covers (P1). Docs contradict each other (P6b). Needs a PM decision: have the band read the HUD/voice-architecture state and warn for `user_presenter`/silent rehearsal, and correct `presentation-studio.md:685`. I could not run a legacy voice stack (no voice in the drill): code-read + doc-read evidence only.
- **Test-file edits to shared tests:** all legitimate, none weakens: `test_capture_relay` (prefix pinned in the list), `test_conversation_events` (allowlist gains `role`; note the key becomes allowed for ANY event type, values are scalar-checked only), `test_presentation_studio_docs` (adds the playback section), `..._edit_docs/_edit_routes/_history_routes` (exclude `/api/presentation-studio/playback*` from "relay maps to variant routes" and "page writes only edits/undo/redo"; the same invariants are re-asserted for playback in `test_..._playback_routes::test_the_core_route_table_and_what_the_relay_exposes`; the `edit` verb still writes only through the Slice 05 service), `test_presentation_studio_routes` (the "playback is refused by forward_json" assertion is replaced by `cues/satisfied`; since `/v1/presentation-studio/playback` is now forwardable, add a negative for `/v1/presentation-studio/playback/armed` in the generic client: currently only the fixed relay route list protects it), `test_v2_architecture` (adapter import allowlist, same pattern as the store), `_fullscreen_browser.mjs` (fake GET for the player + console prefix).
- **`render_overlay` writes nothing:** proven by hash across runs and by code (`apply_ops` + `check_scenes`, never the store); mutating its `mode` string is an equivalent mutant (see 6). **`add_commit_listener`:** exceptions caught and traced (`commit_listener_failed`), only `Exception` (cancellation propagates), awaited after the commit, no lock held; no deadlock found (own-edit short-circuit).
- **Events:** `playback_changed` Python and JS timeline parity green; attributes `presentation_id, variant_id, status, role, depth`; no title/phrase/cue text (`content="forbidden"`); only recorded with a live conversation. `role` is a global allowlist entry (see above).
- **Armed-set pull not relayed, phrases:** the pull route is not relayed (verified). Note the bounded `where` (relayed, shown in the band) carries up to 3 trigger phrases + label of the NEXT cue by design (marked `untrusted`); the full armed message with all phrases/semantics is Voice-only.
- **Voice authority 90 s:** `armed_until` renewed by pulls and by each armed-set publish; expiry refuses `armed_set_expired`; unit-tested with a fake clock. A Core-side publish also renews (the Core renews itself, not only a live follower): acceptable, a dead follower cannot report anyway.
- **Hidden-at-birth aux / "show everything hidden":** aux is created `visibility=hidden` in the same command, revealed by a second command; the gap is milliseconds and the object is revealed by design. A failed reveal leaves a hidden aux in `_aux_objects`, retired on return/stop/crash (code path, `_retire_all`/`_teardown`; mutant M4 proves the retire is covered by tests). The risk "brain reveals every hidden object" cannot make a studio object appear that was not meant to appear.
- **Module size:** domain 934, core 857, stage 265, armed_set 164, player.js 477: cohesive, under the repo's 1 500-line rule of thumb (`09-canonical-names` section 3 note); pure/IO split is clean.
- **Art-direction gate honesty:** see I3.

## 6. Mutation testing (foreground, each restored by `git checkout -- jarvis`, status clean after each)

6 runs (limit 5 exceeded by one because the first mutant proved equivalent; disclosed):

| # | Mutant | Result |
| --- | --- | --- |
| 1 | `render_overlay` request `mode: "preview"` -> `"commit"` | SURVIVED, equivalent: the method never reaches the store whatever the parsed mode. Replaced by 1b. |
| 1b | playback `_render` also calls `edit(... mode=commit)` (playback writes the variant) | KILLED (3 service tests incl. full-run byte-identical, 1 routes test) |
| 2 | cue accepted for any cue of the plan, not only armed | KILLED (3 machine tests + 1 service) |
| 3 | stale generation accepted (`elif False`) | KILLED (2 service + 1 routes) |
| 4 | aux not retired on stop/crash (`_teardown` and `_retire_all` retire nothing) | KILLED (3 service tests) |
| 5 | relay actor not forced (`setdefault`) | KILLED (playback routes 1, edit routes 2, history routes 2) |

## 7. Not verified

Real voice stacks (OpenAI ambient, legacy, duplex), real second screen / projector, physical Esc in a non-headless Chrome (headless CDP keys only), Tool Brain `active` arbitration, art-direction gate with the real Slice 09 service, the Control Center in a full real Jarvis process (my CC was constructed in-process with scene and mode views only), Windows long-run leak count of Chrome temp dirs beyond the runs above, undo-ring interplay beyond one undo, locked sequence execution (Slice 14), `rehearsal` with Jarvis speaking. Drill artifacts lived in `%TEMP%/q12` (removed), CDP profiles in `%TEMP%/qa12-cdp-*` (none left), isolated server stopped, ports free.

## 8. Answers to the implementer's open questions

1. Per-run stage window accepted: tombstone/no-reuse rationale holds (5).
2. Detours: prefab windows only for now: accepted; resource reference display is a later add.
3. Tool Brain ownership refusal test: Slice 21.
4. Legacy/duplex + `user_presenter`: not a refusal today, run starts with a deaf follower; PM decision + band warning + doc fix needed (5, P1, P6).
