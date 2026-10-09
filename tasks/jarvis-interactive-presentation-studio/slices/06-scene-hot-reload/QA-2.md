# QA-2 - Slice 06 (scene hot reload), INTEGRATED, critical tier re-verification

Reviewed: `C:/Projects/jarvis/bipq` detached at `bf94b352` (HEAD and `git status` checked before and after every step and after every mutant; clean at the end). Diffs read: `e437d5b6..5d991394` (rework) and the integration surface (`v2_app.py`, `presentation_studio_pins.py`, `presentation_studio_reload*.py`, playback `ReloadOrigin` hook, edit `announce_commit`, variants `pin_index`, history `pins`). Python: jarvis `.venv`, `PYTHONPATH=bipq` (`import jarvis` resolves to bipq). Skills applied: qa-verification, code-review, runtime-validation, caveman. No product file modified. Real Core + Control Center + headless Chrome runs used isolated tmp data roots and free ports (never 17653/17654). Disk free about 42 GB at the end; no Chrome with a debugging port left running; I deleted only my own temp dir.

## Recommendation: REWORK (1 BLOCKING, trivial; the 8 original QA-1 findings are really fixed)

Everything QA-1 asked for is fixed and proved by my own repros. The only blocker is a Slice 06 test that went red in the integration merge (one-line doc/test mismatch). One test-only startup-order gap and the known flake root cause are POLISH.

## Original QA-1 findings: status

| QA-1 item | Result | My evidence |
| --- | --- | --- |
| B1 control edit during mount wait + failing report clobbered | FIXED, both orderings and late path | Real Core + real page + real Chrome (`q2/test_b1_real.py`, real `throw` in `init`, report delayed 2.5 s at Core so the window is wide). (a) control edit BEFORE the pin write (during the 0.4 s coalescer wait): the reload returns `stale` (409, band "La scene a change entre-temps"), value `EDIT-BEFORE` kept, pin unchanged. (b) control edit DURING the wait: HTTP 409 `presentation_studio_scene_reloading`, then the real failing report -> `rolled_back`, stage and pin back on `jarvis.window@1`, `source_revision` 2, a control edit right after is 200 and persists (`EDIT-AFTER-ROLLBACK`). (c) LATE path: deadline 1 s -> `pending_mount` (202), band "montage non confirme", control edit accepted (200), then the real failed report arrives -> rollback keeps the value (`data.body == EDIT-AFTER-PENDING`), pin and stage back on `jarvis.window@1`. Mutant M2 (rollback copies the stale scene) killed. |
| P1 failed mount + stage restore fails | FIXED | Rig drill (`q2/test_degraded.py`): persistent `StagePatchError` after the first call -> status `degraded` (409, `presentation_studio_stage_failed`), 3 bounded tries, variant keeps new pin + fallback, `unverified` 1. Hard stop, new life on the same dirs: `pending_scenes` finds it, a new run shows the pin, the failing report rolls back: scene on `lab.counter@1`, `last_valid_pin` None, stage on `lab.counter@1`. Repairable after restart. |
| P2 stage exception + variant restore fails | FIXED | `faults.py` "stage.repin Err + restore fails": original `RuntimeError` propagates, pin + fallback kept, `_note_unverified` called, `unverified` 1 (recover() finds it after restart). "mount FAILED + variant restore fails" -> `degraded:presentation_studio_storage_io`. |
| P3 confirm write failure said `reloaded` | FIXED | Drill: second `replace_scene_source` fails -> `pending_mount` (202), code `presentation_studio_storage_io`, `mounted: true`, fallback kept, `unverified` 1, never `reloaded`; the page text says "confirmation non ecrite" (page_js test). A later edit confirms (v2, fallback cleared). Mutant M7 killed. |
| P4 registry never takes the Studio lock untested | FIXED | `test_the_registry_never_takes_the_studio_lock` exists; my mutant (registry refreshes from `pin_index()` = takes `exclusive()`) killed by it. |
| P5 browser flake `inline_handler` | FIXED | prelude now waits for `counters.mounted===1` on all frames; reload_browser 23/23 three times. |
| P6 hidden-tab sentence | FIXED, honest | OPERATIONS.md now says the case is not proved by a test and does not promise a moment. |
| P7 rate limit for `brain` | FIXED | Rig: brain edits 1-10 `reloaded`, 11th-13th `presentation_studio_source_edit_rate` (429), another scene unaffected, user 12 edits all `reloaded`. Doc says 429 and the code table says 429. Syntax pre-check explicitly declared infeasible and documented (honest). |
| Scene lock covers all writers | FIXED | Rig (`q2/test_lock.py`) with a mount that never reports: control.set, control.reset, scene.remove, scene.restore_values, `PUT` variant save changing the scene, `create_branch`: all `presentation_studio_scene_reloading`; other scene control.set: applied; undo/redo: `history_stale` / `history_unavailable` (refused, the document moved under them; integration test 175 covers the typed `scene_reloading` refusal of undo with ticket release). `set_controls []` was refused for an unrelated reason (anchors) in my call; the guard is in the one write door (`_write_variant`), so structure ops cannot bypass it. Mutant M1 killed by 3 files. |

## Findings

### BLOCKING

**B1. Slice 06 test red on the integrated tree.** `tests/unit/test_presentation_studio_reload_docs.py::test_the_canonical_event_is_documented_on_both_sides_and_in_the_allowlist` (line 92) asserts `"10. **Presentation Studio scene hot reload" in events`, but the merge renumbered the note to 11 (`docs/conversation-events.md:268`, the table row at :181 already says "see note 11", note 10 is the Slice 14 presenter). 1 failed, 10 passed. Not in BASELINE. Fix: assert note 11 (or match on the title only). The merge was not re-verified with the Slice 06 own test file.

### POLISH

**P1. Startup order is not pinned by any test (mutant M6 SURVIVES).** `jarvis/core/v2_app.py:538-553`: moving `presentation_studio_variants.start()` after `presentation_studio.start()` (the order the code comment calls "obligatoire") leaves green: reload_core (4), variants_recovery (15), variants_crash (15), recovery (23), v2_architecture (8). Add one Core-level test that records the call order (variants.start, studio.start, pins.rebuild, reload.recover, playback.start_service).

**P2. Known flake `test_fullscreen_keys_act_once_each_and_leaving_fullscreen_restores_the_band`: root cause found. It is a harness race on top of a real, sub-human product window.** Reproduced 1/8 alone (run 5), 1/3 as a whole file (realpage#1), 1/14 and 1/4 with my instrumented copy (`q2/test_flake.py`). Failure: `reads["after_one"][0] == 1`, expected 2; the `until POS===2` times out at 8 s (run takes 17 s instead of 9 s). Evidence from the instrumented failing run: the harness waits only for `!!document.fullscreenElement`; the first `ArrowRight` is delivered while `document.fullscreenElement` is already set but `document.activeElement` is still the band's `<button>` (key log: `["doc-cap","ArrowRight",false,"BUTTON","BUTTON",true,1418]`, no `keydown` reached the host); `stats.keys` stays 0 for both the player and the fullscreen module; a moment later `activeElement` is the stage host (`studio-stage-...`), so the module's `focusHost()` ran after the key. Mechanism: `control_center_fullscreen.js:443-470` binds the host `keydown` listener and calls `focusHost()` only in the `fullscreenchange` handling, which runs after the browser has set `fullscreenElement`; meanwhile `control_center_presentation_studio_player.js:515` deliberately ignores nav keys when `doc.fullscreenElement` is set ("the fullscreen layer reads them"), so the key is dropped by both layers. It is a REAL ordering gap, but only reachable inside one rendering step after entering fullscreen (a human cannot press a key there; a CDP-injected key can). Slice 12/03 code, not Slice 06; nothing in the reload touches it. Fix: the test should wait for `JarvisFullscreen` state `entered` or `document.activeElement === document.fullscreenElement`; optional product hardening: in `onKeyCapture` only defer when the fullscreen module has bound its host (not merely when `fullscreenElement` is set). Recommend recording as an Issue for Slice 12/03, not blocking Slice 06.

**P3. Rollback with values that do not fit the restored manifest keeps them.** `presentation_studio_reload.py` `_restore_variant` (`carried.scene is None` branch): "pin fields only, values kept, traced" at warning level. The scene can then be pinned to a manifest its stored values fail, visible only in the journal, not in the `ReloadResult`. Rare (needs a value written during the wait that is invalid for the old manifest). Surface it in the result message or `reset`.

**P4. Module sizes.** `presentation_studio_reload.py` 709 -> 890 lines (+181 from the rework), `presentation_studio_playback.py` 1091, `v2_app.py` 903. Within repository practice (v2_architecture green) but the reload service is now the second largest Studio core module; the rollback/degraded block (about 150 lines) is a natural split.

### ISSUE (non-blocking, PM backlog)

- I1. Rate limit keys on the `actor` claimed in the body. The Control Center relay forces `user`; a direct holder of the Core token can claim `user` and skip the `brain` cap. Same local trust boundary as the other routes. Also validation-refused brain edits consume quota (counted in `_admit` before the gate); acceptable, say so in the doc.
- I2. Archive growth is still unbounded by design (move, never delete): after 50 reloads + 1, 160 files in `prefabs/.archive`, 18 live versions of the source id, 424 KB. Carried from QA-1 P7. Needs the documented archive bound that 01a I1 asked for.
- I3. Leak check at 50 reloads (real page, `q2/test_leak.py`): 50/50 `reloaded+` in 42.8 s (about 0.86 s each, about 70/min, bounded by mount latency; the 0.4 s coalescer never merges serial edits, one version per edit), iframes 3 -> 3, sandbox `["allow-scripts", null]` on all 3, per-frame listeners 7 -> 7, neighbours keep their node and document, console errors none. DOM nodes 657 -> 667 (+10, not obviously per reload) and used JS heap 9.1 -> 11.8 MB without forced GC: inconclusive, not shown to leak. The host bundle cache and `stats()` are in a page closure and could not be read from CDP; the unit leak tests (`prefab_host_js`, `reload_host_js`) cover them. Not measured at runtime.
- I4. A kill during a reload leaves the scene on the unconfirmed new pin with its fallback (by design) until a run shows it again; nothing shows it proactively after restart. The playback hook confirms or rolls back at the first mount. Acceptable, state it in OPERATIONS.
- I5. Presenter drill covers a reload while the line is `pending`; a reload while the line is mid-speech is not exercised (see Not verified).

## Integration verification (task points 2 to 4)

**Registry sources with the real 01a retention.** `test_presentation_studio_pin_sources.py` (4 tests) builds the REAL registry as `v2_app` does and publishes more than 64 versions with a version pinned by each single source (live variant, archived variant, undo-stack entry, running playback stage window) and one pinned by none: the pinned ones survive, the unpinned is archived. All pass. Mutant M3 (`pin_index` skips archived variants) killed (the restart-survival test); mutant M4 (registry takes the Studio lock) killed. Registry fails closed (`test_the_registry_stays_closed_when_a_source_cannot_answer`, pins 12/12 pass), 5 s timeout is `PIN_REGISTRY_TIMEOUT_SECONDS` in `prefab_retention.py:30` and used at `prefab_service.py:678`; coalescer flush is `v2_app.stop()` -> `presentation_studio_reload.close()` (line 845, before scene and prefab close) and the Core-level test passes.

**Kill drills on a REAL Core subprocess, `taskkill /F /T`, restart on the same data root with the real start order** (`q2/test_kill.py`):

| Kill point | After restart |
| --- | --- |
| mid-reload (pin + fallback written, stage patched, no report) | no `studio-*` object left in the scene (ledger reclaimed), no active playback, `pending_scenes` = the scene, scene on the new pin with `last_valid_pin = jarvis.window@1`, pins ready (`variants 1`), pinned set `{new: [1], jarvis.window: [1]}`, health ok. The existing 6 subprocess kill tests (`reload_crash`) also pass on the integrated tree with the real playback. |
| mid-playback-detour (stage + aux window up) | no `studio-*` object (stage and aux both reclaimed from the ledger), playback inactive, scene unchanged, nothing pending, health ok. |

**Playback integration.** Existing integration tests pass (16): the run's own stage window is patched, position and phase kept, run not paused; foreign edit still pauses (`playback_service` 336 and rework 18 pass); presenter test asserts `interrupted False`, same position, `brain.texts` unchanged (no line repeated or dropped), no presenter event. The cue follower has no commit subscription (grep of `presentation_studio_cue_follower.py`: no edit/commit hooks), so a reload cannot be read as a user interruption by it. Mutant M5 (`ReloadOrigin` ignored so the reload pauses the run) killed.

**Hot-swap abuse.** Gate is `swapPrefix` set only in `control_center_scene_page.js`; `git diff cee99e77..bf94b352 -- jarvis/runtime jarvis/prefabs` shows sandbox/CSP/jv:1 only in comments and no change to `control_center_prefab_protocol.js` or `jarvis/prefabs`. Runtime: every survey in the real-page runs (3 times, plus the 50-reload run) reads sandbox `["allow-scripts", null]` on every frame. Mutant M8 (hot-swap for any id) killed by `reload_host_js`; note it SURVIVES `test_prefab_host_js.py` alone (that file does not cover the swap), caught by the reload host file.

## Tests (one file at a time, foreground)

146 non-browser files, all pass except 2: the new B1 above and `test_scene_group_drag_js.py` (BASELINE red, source-inspection string absent, unchanged). Includes all reload*, pin_sources, reload_integration, playback*, presenter*, variants*, history*, cue*, edit*, scene*, score*, store/service/routes/docs/crash studio files, test_prefab_*, scene prefab page/bridge JS, authority suites, conversation_events (142), control_center_timeline js/ui (72/13), documented_routes (3), v2_architecture (8), schema_migrations (8), capture_relay (35), prefab_relay (22), fullscreen commands/js/surface. Browser files, 3 runs each: fullscreen_browser 8x3 pass; prefab_browser_js 4x3 pass; attention_browser 31x3 pass; player_browser 4x3 pass; presenter_browser 2x3 pass; reload_browser 23x3 pass; reload_real_page_browser 2x3 pass; player_realpage_browser 5/5, 4/5 (the flake, P2), 5/5.

Existing test edits reviewed (domain 1->2 schema constants, `presentation.v2` fixture, capture_relay forwardable prefix for `/playback`, reload_docs/page_js additions, crash test adapted to the real playback, reload_browser prelude strengthened from a 1200 ms sleep to a real `mounted===1` condition): all legitimate; no assertion weakened. Docs: canonical names numbering 12..18 consistent (18 = "Slice 06 additions (merged after 12 to 17)"), presentation-studio.md states degraded, scene lock, rate limit, compare-and-restore and the structural-only gate honestly; the conversation-events note numbering is the one stale spot (B1).

## Mutation (8 mutants, each restored with `git checkout`, `git status` clean and HEAD identical after each)

| # | Mutant | Verdict |
| --- | --- | --- |
| M1 | scene lock removed (`_refuse_reloading_scenes` returns) | killed (service 1, integration undo test, routes 409 test) |
| M2 | rollback copies the stale scene (props/data from `before`) | killed (`test_rollback_keeps_a_control_value_written_during_the_wait...`) |
| M3 | registry/`pin_index` skips archived variants | killed (pin_sources restart test, variants_service) |
| M4 | registry takes the Studio lock (refresh via `pin_index`) | killed (`test_the_registry_never_takes_the_studio_lock`) |
| M5 | `ReloadOrigin` ignored, reload pauses the run | killed (integration, first test) |
| M6 | startup order swapped (variants.start after studio.start) | SURVIVED (P1) |
| M7 | confirm failure reports `reloaded` | killed (`test_a_confirmation_that_cannot_be_written_never_reports_reloaded`) |
| M8 | hot-swap for any prefab id | killed by `reload_host_js` (survives `prefab_host_js` alone) |

## Not verified

Hidden-tab runtime behaviour (docs now honestly say it is unproved); two Control Center tabs reporting; a reload while the presenter line is mid-speech; a kill drill with a live browser page attached (the real-Core kill drills had no page); host bundle-cache size at runtime; physical Esc key / second screen; `set_controls` as a scene-lock probe (my call was refused for an unrelated reason).

## Process notes

Scratch drills (outside the repo): `C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/2c31ce96-dd64-4b96-839c-feff87315a95/scratchpad/q2/` (`test_b1_real.py`, `test_degraded.py`, `test_lock.py`, `test_rate.py`, `test_kill.py` + `kill_child.py`, `test_flake.py`, `test_leak.py`, `mut.sh`). Two deviations from the brief: one long browser loop was auto-backgrounded by the tool after 10 minutes (it still ran to completion on its own, nothing overlapped with another Chrome run), and I used one short Monitor to wait for it. No stash used, no other worktree touched.
