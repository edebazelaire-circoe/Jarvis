# QA-1 - Slice 06 (scene hot reload), critical tier

Reviewed: `C:/Projects/jarvis/bipr` detached at `e437d5b6` (diff `cee99e77..e437d5b6`, 10 S6 commits, 54 files, +7077/-113). HEAD and `git status` checked before and after every step, clean after every mutant (restored with `git checkout`). Python: jarvis .venv, `PYTHONPATH=bipr`, `import jarvis` resolves to bipr. Skills applied: qa-verification, code-review, runtime-validation, caveman. Disk: 50.24 GB free before, 50.11 GB after (my CDP/tmp dirs deleted; a `jarvis-fs-cdp-*` dir that appeared mid-run may have been another agent's and I removed it with mine). No product file modified.

## Recommendation: REWORK (1 BLOCKING, narrow; everything else POLISH/ISSUE)

The mechanism is sound and well tested. One real data-loss race in the rollback path must be fixed or explicitly closed by locking before approval.

## Verdict on the specific questions

| Question | Answer |
| --- | --- |
| Is the validation gate real? | Yes. `PrefabService.validate_candidate` is literally `parse_candidate` + fingerprint (`prefab_service.py:479`), the same function `save` runs, so the implementer is right: equivalent. In `_gate` it is also followed by a second `parse_candidate` (`presentation_studio_reload.py:301`) that is needed to get the manifest, so the `validate_candidate` call is redundant (mutant M1 survives, equivalent). Real limit: it is a STRUCTURAL gate. A JS syntax error or a throw in `behavior.js` passes it, is published (burns a version) and is caught only at mount (see drill). |
| Rollback at every step | Verified by my own fault injection (below). Consistent for validate, publish, pin write, stage patch, mount failed, mount deadline. Inconsistent only on double faults (P1, P2) and on the concurrent control edit (B1). |
| Never destroy the last valid scene / kill drills | Existing 6 real-subprocess-kill tests cover publish->pin, pin->stage patch, stage patch->report, file wholeness. Pass. I did not add a kill drill of my own (see "Not done"). |
| Service-owned `source_revision`/`last_valid_pin` | Verified over HTTP (adv.py): a variant save setting `source_revision` -> 400, clearing/setting `last_valid_pin` -> 400, new scene must be 0/null, pin move by save = exactly +1 and clears fallback, rollback = +1 (edit+rollback gives 2). Mutant M7 killed. |
| Schema v3 + UPGRADES | `_variant_v2_to_v3` in place, `variant.v3.json` fixture, v2 file reads equal to v3 object, rewritten as v3 on next save, v4 refused (older code refuses v3 by the `> current` rule). Test edits to constants are legitimate (v2->v3, 3->4), not weakened. |
| Host hot swap abuse | Gated by `swapPrefix='presentation-studio.'` set only in `control_center_scene_page.js`. Mutant M9 (swap for any id) killed. The namespace cannot be saved by a user (guard below), so another prefab id or hostile prefab cannot reach the swap path. Staged frame: same `SANDBOX`, same srcdoc builder, events and `open_url` refused until promotion, window height not moved, discarded on failure. Sandbox/CSP/jv:1: diff grep over `jarvis/runtime` finds `sandbox/CSP` only in comments; no change to `control_center_prefab_protocol.js`, `jarvis/prefabs/`, `domain/prefab*.py`; no new jv:1 message pair (the outcome goes host -> page -> relay, never to the frame). Runtime: every survey in the real-page tests and my drill shows 3 iframes, sandbox `["allow-scripts", null]`. |
| Reserved namespace guard | `POST /v1/prefabs` (the MCP `prefab_save` and CC relay go through it) refuses `presentation-studio.*` with a message naming the way out (400). A user cannot save their own `presentation-studio.x` (intended, documented in prefabs.md:385). Case, unicode (U+2011, Cyrillic), trailing dot, `..`, NUL, `X` are refused earlier by the id grammar; `lab.presentation-studio.x` is allowed (201), correct. The guard is only in the route; `PrefabService.save` itself is unguarded by design (Studio uses it). Mutant M6 killed by one test (routes). |
| Prototype keys | `__proto__`, `constructor`, `prototype` in inputs/events/sample refused with `presentation_studio_source_invalid` (HTTP 400, adv.py). M8 killed. |
| Registry | Fails closed (not built or degraded -> raises; M4 killed). Sources: variant docs (pin + fallback), live scene snapshot (memory, lock-free), holds, add_source. Answer: every requested id is a key. `close()` wired: removing the call in `v2_app.stop()` fails `test_the_pending_burst_is_published_at_shutdown...` (checked by hand). Real-registry 01a retention tests pass (`test_prefab_retention*` 47 passed). |
| 8 s `pending_mount` | Verified: deadline -> `pending_mount`, pin and fallback kept, stage patched, late report confirms/rolls back. Never a false success by construction (`mounted` needs `ready` + 250 ms no error). Hidden tab claim is unverified (P6). |
| Provisional `POST .../stage` | Reachable by anything that can call the CC relay or Core with the token (writes a global `window` object as actor USER, visible to the audience). No MCP tool, no brain exposure, and the three new `LocalCoreClient` methods have no caller. PM decision (remove, or test-only seam, when Slice 12 binds) is right. |
| 0.4 s quiet period | Acceptable. Measured: 60 concurrent API edits on one basis = ONE publication (59 `merged`), 0.95 s. Page serializes: 59 of 60 concurrent in-page calls returned `busy`. Serial worst case (each edit awaits its mount): 60 versions in 50.8 s (about 70/min), i.e. the rate is bounded by latency only, not by a limiter. Coalescer ceiling gives at most 1 version per 4 s under a continuous burst. Retention active: after 61 versions, live dirs 33..61, 193 files in `prefabs/.archive`. |
| Slice 12 binds `StageWindows.bind`/`PlaybackProbe` at merge | Agreed; `bind`, `unbind`, `binding_for`, `PlaybackProbe.position` are the seams. |

## Findings

### BLOCKING

**B1. A rollback overwrites a committed Tier-1 edit made during the mount wait.**
`jarvis/core/presentation_studio_reload.py:479-525` (`_roll_back` -> `_restore_variant`, target built from the stale `before` scene, line 510/518) and `:489-492` (stage restored from the stale `shown` values).
Scenario: source edit published and pinned; while the service waits (up to 8 s) for the host, the user changes a control (`control.set` data.count=77, status `applied`, revision 4). The host then reports `failed`. Rollback checks only `live.prefab != scene.prefab` (line 514), then writes the pre-edit document: `data.count` back to 12.
Evidence (scratchpad `faults.py`): `after tier1 during wait ... data={'count': 77}` then `after late FAILED (rollback) ... data={'count': 12} srcrev=2`. The edit service does not take the reload per-scene lock, so nothing prevents this. The late-report path (`_resolve_unverified`, line 564) is correct because it rebuilds from the current scene; only the in-flight path is wrong.
Why blocking: SLICE.md "never let a failed edit destroy the last valid presentation state"; the doc promises concurrent edits are serialized. Silent loss of an `applied` user/voice edit.
Fix direction (not trivial, note): during the wait the Tier-1 edit was validated against the NEW manifest, so reverting only the prefab may leave values invalid for the old one. Either (a) make the control-edit path wait on the scene lock while a source edit is unconfirmed, or (b) roll back by rewriting only `prefab/source_revision/last_valid_pin` on the live scene and revalidating live values against the old manifest, resetting what no longer fits with a visible `reset` signal. Add a test for edit-during-wait + failed report.

### POLISH

**P1. Double fault: failed mount + stage restore fails leaves the stage window on the failed version.** `:493-496`. Repro (faults.py "mount FAILED + stage restore fails"): variant rolled back to `lab.counter@1`, stage object still `...s0000000000a1@1` (the failed source). The result message says so, but nothing retries and nothing is added to `_unverified`; the next reload of the CC page mounts the broken pin as a plain frame (error band), the late-failed report then rolls the stage back only if an entry exists (it does not). Add the entry or retry once.

**P2. Double fault: unexpected stage exception + variant restore fails.** `:426-429`. Variant keeps new pin with fallback, stage shows old, `_unverified` has no entry until the next Core restart (`recover()`); the next edit composes from the unmounted new pin (`_source_of`). Rare; note `_note_unverified` before re-raising.

**P3. Confirm write failure reports `reloaded`, `mounted: true`.** `_confirm` lines 466-477 trace the failure but return a scene with `last_valid_pin=None` while the document still holds the fallback (faults.py "confirm write fails": `lvp=('counter',1)`, status `reloaded`). Self-heals only at restart. Return `pending`-like status or retry.

**P4. Test gaps.** Mutant M5 (registry awaits the Studio lock) SURVIVES `test_presentation_studio_pins.py` (11 passed): no test proves the registry never takes the Studio lock. M1 (skip `validate_candidate` verdict) survives: equivalent, see above; drop the redundant call or keep it only as documentation.

**P5. Browser-test flake.** `test_presentation_studio_reload_browser.py::test_a_source_refused_before_publication_touches_nothing_in_the_page_or_in_core[inline_handler]` failed once in three full-file runs (line 276, the `{"starts":1,"mounted":1,...}` counters assertion); that single parametrization passed 18/18 on isolated reruns. The prelude waits 1200 ms but not for the 250 ms settle outcome of all three frames; wait on `counters.mounted==1` instead. Both browser files otherwise 23/23 and 2/2 on the other runs.

**P6. Hidden-tab claim not evidenced.** `docs/OPERATIONS.md` (new Human recipe) says a hidden tab reports "at the next paint". No code or test handles visibility; Chrome only throttles timers (settle 250 ms becomes about 1 s, longer after intensive throttling), so a hidden tab usually still reports inside 8 s and otherwise yields `pending_mount`. Never a false success, but the sentence is unproven: reword or add a CDP visibility test.

**P7. Syntax errors and throws are caught at mount, not before publish.** Drill: `function ( {` gives `rolled_back / mount_failed / frame` ("SyntaxError: Function statements require a function name") after publishing version 1; `throw` likewise. Each bad edit consumes a version; `prefabs/.archive` grows unbounded (move, never delete: 193 files after 61 versions) and `source-edits` has no per-scene rate limit for the `brain` actor. Consider a cheap `new Function` / parse check in the page or Core before publish, and a documented archive bound.

**P8. Housekeeping.** Source-edit timeout constants disagree (client.py `SOURCE_EDIT_TIMEOUT_S=40`, relay `45`, page `EDIT_TIMEOUT_MS=50000`); three new `LocalCoreClient` methods (`presentation_studio_source_edit/mount_report/reloads/show`) have no caller; `control_center_prefab_host.js` is now 858 lines (+186), `presentation_studio_reload.py` 709, `control_center_presentation_studio_reload.js` 456. Within the repository's practice but the host is the largest.

### ISSUE (non-blocking, for the PM backlog)

- I1. `POST .../mount-reports` trusts any caller of the relay/Core token: a forged `failed` during a wait rolls back a good source, a forged `mounted` confirms an unmounted one (adv.py: `forged report 200 matched:false` when nothing waits). Local trust boundary, same as the other CC routes; the frame itself cannot reach it (sandbox `allow-scripts`, no network). Revisit when the Studio gets a multi-user surface.
- I2. Two CC tabs both report; first wins. Fine for single-user.
- I3. Stage route: remove or make a test-only seam when Slice 12 binds (PM answer confirmed).
- I4. Restart between steps was not done on the real Core+page drill (relied on the 6 subprocess-kill tests).

## Evidence: test runs (all one file at a time)

| File | Result |
| --- | --- |
| reload_domain / service / routes / core / crash / docs | 50 / 39 / 14 / 4 / 6 / 10 passed |
| presentation_studio_pins | 11 passed |
| reload_host_js / page_js | 18 / 25 passed |
| reload_browser (x3) | 23 passed; 22 passed + 1 failed (P5); 23 passed |
| reload_real_page_browser (x3) | 2 passed each time |
| 52 other files: all `presentation_studio_*`, `prefab_*` (incl. retention, retention_crash, draft_coalescer, frame_containment, host_js), `scene_prefab_*`, `conversation_events`, `control_center_timeline_js`, `documented_routes`, `v2_architecture`, `schema_migrations`, `capture_relay`, fullscreen (browser/commands/js/surface) | all passed, 0 failed |

None of the BASELINE.md red tests are in this set. Existing test edits (variant constants 2->3, scene wire keys, route tables, schema 3->4 refusals, frame_containment extra `advance(SETTLE_MS)` for the new settle timer) are legitimate adaptations; no assertion was weakened.

## Evidence: real drill (real `JarvisCoreApplication` + `ControlCenter` + real page in Chrome, own tmp data root, free ports, not 17653/17654)

3-scene presentation, stage shows scene 1, two neighbour windows `user-a`/`user-b`.

| Edit | Result | Old frame | Others |
| --- | --- | --- | --- |
| good style | `reloaded`, mounted true, 852 ms, band ok | replaced | same DOM nodes, listeners 7 = 7 |
| syntax error (behavior) | `rolled_back` `presentation_studio_mount_failed` reason `frame`, 583 ms, band bad | same node, listeners 7 | same |
| throws at init | `rolled_back`, message "boom" | same node | same |
| oversize (400 KB template) | refused by request check (327680 byte body limit), thrown to page, band bad, Core untouched | same | same |
| static CSP violation (`<script src>`) | `refused_validation` `presentation_studio_source_invalid` before publish | same | same |
| runtime CSP violation (fetch/WebSocket out) | mounted fine (network blocked by CSP, no error) | replaced | same |
| good after failures | `reloaded`; final pin v4, `last_valid_pin` null, `source_revision` 6 | | |
| 60 serial edits | 60 `reloaded`, 50.8 s, 3 iframes, listeners 7, others untouched | | |
| 60 concurrent edits (page) | 1 `reloaded`, 59 `busy` (page guard) | | |
| 60 concurrent HTTP edits, no window | 1 publication, 59 `merged`, version 1 only | | |

Console errors `[]` throughout. Stage window pin and variant pin agree after every step.

## Fault injection (own, `Rig` fakes with real services; state = variant pin / fallback / counter / stage pin)

| Injected | Result | Consistent? |
| --- | --- | --- |
| `validate_candidate` raises | RuntimeError propagates, nothing changed | yes |
| publish `STORAGE_IO` / RuntimeError | raised, pin unchanged | yes |
| pin write fails (io / RuntimeError) | raised, pin unchanged, stage unchanged | yes |
| `stage.repin` StagePatchError | `rolled_back` `stage_failed`, counter 2 | yes |
| `stage.repin` RuntimeError | variant restored then raised | yes |
| `stage.repin` error + variant restore fails | raised; variant new+fallback, stage old | partial (P2) |
| mount FAILED | `rolled_back`, stage and variant old | yes |
| mount FAILED + stage restore fails | variant old, stage on failed version | NO (P1) |
| mount FAILED + variant restore fails | raised; variant new+fallback, stage old | partial |
| mount deadline | `pending_mount`, pin+fallback kept | yes |
| confirm write fails | `reloaded` but fallback kept | partial (P3) |
| tier-1 edit during wait + FAILED | edit lost | NO (B1) |

## Mutation (10 mutants, all restored, `git status` clean after each)

| # | Mutant | Verdict |
| --- | --- | --- |
| M1 | skip `validate_candidate` verdict | SURVIVED (equivalent, `parse_candidate` repeats it) |
| M2 | rollback does not restore pin | killed (service, 3 tests) |
| M3 | host promotes staged frame before mount | killed (host_js, 3 tests) |
| M4 | registry failure treated as open | killed (pins, 3 tests) |
| M5 | registry takes the Studio lock | SURVIVED (P4) |
| M6 | namespace guard off | killed (routes, 1 test only) |
| M7 | variant save may set the reload fields | killed (service, 3 tests) |
| M8 | prototype keys allowed | killed (domain 3, service 1) |
| M9 | any prefab id uses hot swap | killed (host_js, 1 test) |
| M10 | close() skips coalescer flush | killed (service); v2_app wiring removal also killed (core test, checked separately, not counted) |

## Not done
Kill drills of my own on a Core subprocess (relied on the 6 existing crash tests); restart between steps of the live drill; hidden-tab runtime test; fullscreen interplay beyond the existing fullscreen suites; two-tab report race.

Files: `C:/Projects/jarvis/bips/tasks/jarvis-interactive-presentation-studio/slices/06-scene-hot-reload/QA-1.md` (this report). Scratch scripts (outside the repo): `C:/Users/Clarice/AppData/Local/Temp/claude/C--Projects-jarvis-sub-agents-jarvis-agent-01/2c31ce96-dd64-4b96-839c-feff87315a95/scratchpad/{drill,adv,faults,mut}.py`.
