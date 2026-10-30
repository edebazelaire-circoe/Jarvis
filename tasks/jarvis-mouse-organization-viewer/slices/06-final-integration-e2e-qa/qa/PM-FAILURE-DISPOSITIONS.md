# S06 PM failure dispositions

All20 shards completed on exact revision97d56f11. The original red outcomes remain evidence; no ignore or synthetic green verdict is introduced. See the final dated dispositions below; older checkpoints are historical. Human acceptance remains pending.

| Observed failure | Evidence | PM disposition |
|---|---|---|
| `test_control_center_timeline_ui.py::test_the_cosmos_theme_knows_every_dock_tool_and_moves_the_pills` | Shard01; exact `c0858a80` baseline reproduction: same line165, expected right gutter while existing HTML uses left. Test/work source and dock block identical across revisions. Independent S2 baseline JUnit/log in QA commits `5c468016`, `6631a8bb` (to integrate after immutable gate). | Proven pre-existing, unrelated. Task criterion permits this with retained evidence; global gate stays truthfully red. No product fix or registry ignore in this task. |
| `test_presentation_response_policy.py::test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole` | Shard01; exact baseline reproduction: same line1185, scheduler ACK/QUESTION inventory versus old expected QUESTION. Source inventories identical. Same independent baseline invocation:2 failed31.50s, no error/skip. | Proven pre-existing, unrelated. Preserve evidence and scoped Issue; no broader speech-policy change. |
| `test_barehands_hud_js.py::test_the_page_serves_the_pointer_before_the_hud_that_subscribes_to_it` | Shard03; independent exact baseline reproduction:1 failed35.16s, same line987. Existing registry says `.dock, #railDock, #barehandsHud, #boardsHud`; old assertion expects `#chatTab`. QA evidence commit `a23ca0af` queued for integration after immutable gate. | Proven pre-existing annotation/test drift. No feature change to this registry. Retain evidence without adding a global ignore. |

No current feature regression has been established by these classified source failures. This does not claim the full gate passed. The dense-graph relation click at200% (Shard02) and two architecture-settings navigation cases (Shard03) remain **unclassified/blocking pending actual baseline browser comparison**; static similarity alone does not settle them. Existing App stub/data_root and Bare Hands practice failures match the canonical dated registry and previously recorded baseline causes. Later shards still require their own review.

## Shard06 mock duplex timeout

`test_presentation_turn_authority.py::test_duplex_architecture_refuses_presentation_visibly_once` failed at line701 waiting for the fake Core listening/snapshot condition. Independent exact `c0858a80` baseline reproduction:1 failed10.89s with the same line701→until185 timeout. Test and relevant voice/presentation/architecture/observer dependencies are unchanged. This was a mock-only test with no browser, model, hardware or live runtime. Actual stdout/JUnit and careful source comparison are in QA commit `b426bc9e`, queued for integration after the immutable gate.

PM disposition: proven pre-existing, unrelated. The observed fact is the same baseline timeout; no particular listener count or internal root cause was measured or claimed. Retain red evidence and scoped Issue, without changing speech architecture in this task.

## Shard09 background conversation cases

All three parameters of `test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale` and `test_ambient_noise_during_live_does_not_keep_the_session_alive` failed at the same background wait: test lines344/447 → virtual harness796→132, “the /v1/events subscription is closed”. The four exact cases were independently rerun at baseline c0858a80:4 failed140.21s, matching every gate trace. Real owned Core/SQLite/ephemeral HTTP/WebSocket, fake session/audio/backend; no user runtime, Chrome, model or hardware. Relevant tests/harness/voice/protocol dependencies are unchanged. QA commits `9f284b55`, `03cdbe25`, `ed851ead` preserve pretriage, actual JUnit/log and final comparison.

PM disposition: all four proven pre-existing/unrelated. The failure condition is measured; no specific subscriber count/internal root cause is claimed. No global ignore or speech implementation change.

## Shard10 mock mode follower cases

`test_mode_change_while_voice_is_idle_reaches_the_coordinator` and `test_legacy_architecture_refuses_presentation_visibly_once` in `test_interaction_mode_follower.py` failed at lines227/324 → until185. Exact independent baseline rerun:2 failed21.07s, same timeout and unchanged dependencies, mock-only/no browser/model/hardware. QA evidence is `00beeae2`.

PM disposition: both proven pre-existing/unrelated. No unmeasured internal count/root cause is inferred. After ten complete shards, the same three browser cases remain unclassified pending their actual baseline checks; no other unclassified failure remains among those ten reports.

## Shard12 current contract tests and Chrome infrastructure

Two `test_scene_renderer_logic.py` source assertions expected the old per-object commit loop removed by the required S05 atomic-group fix. PM disposition: correct these contract tests, without changing correct product behavior or pretending they are pre-existing failures. S2 `1adf4766` reuses the existing real desk harness: all targets/origins/representations/common movement, one group batch, actual pending layer before every hold release while promises remain unresolved; partial group, single, resize, legacy fallback and no-op.13 focused pure/Node checks passed10.35s. PM read the diff; independent S1 read-only review `ba131c2a` found no meaningful gap. Integrate after immutable gate, then run the affected canonical file gate.

Settings voice-model comparison1366×768 failed in Chrome boot `/json/list` polling, before WebSocket/Page.navigate; no overflow measurement occurred. PM disposition: infrastructure, pending one affected current-case rerun after the complete gate. Keep the original red report and unrelated unclosed aiohttp session/connector warnings. No product cause is attributed. Source-only cleanup review finds finally+exit owned-profile cleanup paths, best-effort; it proves neither a leak nor actual absence of residual processes. No broad scan/kill was performed.

## Shard14 indicators

Both pure `test_capture_rail_js.py` assertions failed at lines401/409. Exact baseline reproduction:2 failed6.87s, identical assertions. Unchanged shell measures top-right and unchanged HTML places recording indicators on the right; old tests expect top-left. S2 QA evidence `285100f2`. PM accepts these two only as proven pre-existing/unrelated.

Three actual `test_variants_run_browser.py::test_during_a_run_recording_chips_stay_visible_reachable_and_stop_without_touching_the_run` parameters (1280×720,1920×1032,600×800) measured recording-chip overlap with Fullscreen/Close controls. These remain **blocking/unclassified**, queued for actual baseline browser reproduction after the complete pass. Later continuity/stop assertions were not reached, so no success is claimed. Browser fixture uses real owned Core/SQLite/ephemeral HTTP and fake capture/transcription; no hardware/model is required. Static similarity alone is insufficient proof.

## Shard15 stale registry entries

All four `test_one_geometry_and_one_rank_set_for_both_themes[size0..size3]` cases passed in the complete run, so canonical policy correctly flagged their old `failing` entries as stale. S2 `8fb231e7` removes exactly those four rows; every other entry is identical, including reduced_motion. Production load_known validates28→24 entries. PM accepts this stricter metadata correction; actual passing browser evidence already exists, so no redundant browser rerun solely for metadata. Preserve original raw red/stale report.

The one actual known failure, reduced_motion, lists only existing Boards controls. Test and Boards style module are unchanged vs baseline; no new grip/viewer selector is implicated. This test excludes the scene and never mounts the viewer, so it is not claimed as their motion proof. New grips add no transitions/animations; viewer reduced-motion behavior has its separate actual S03/S06 evidence.

## Shard16 protocol conformance and unchanged model catalog

Historical `test_the_protocol_a_frame_speaks_did_not_gain_a_message` froze the pre-S03 frame vocabulary. The required, separately reviewed fieldless Escape bridge is an intentional contract amendment, not a product regression. S2 `2ae77967` renames/updates this test to pin the exact original five plus Escape, the complete field table (`escape:[]`), unchanged host vocabulary/sandbox/no-snapshot boundary and canonical docs.18 focused pure/Node tests passed9.13s. PM reviewed actual diff; integrate after immutable gate and include this file in corrective canonical gate. No product/protocol implementation changed by this correction.

All six known MCP catalog failures are independently bounded to the old baseline discrepancy: S2 `4666b5f0` uses production pure catalog helpers with inert backends, no tool invocation/server/network/model/browser. Both c0858a80 and97d56f11 expose exactly21 tools/40015 context bytes (old tests expect20/39513); names, schemas, descriptions, tools/list, descriptors and output schemas have identical hashes. `layout_selection` is absent from model-visible descriptors. SceneOp references in MCP are named internal operations, not a dynamically published enum. PM accepts unchanged baseline cause; this feature introduces no model-tool schema expansion.


## 2026-10-30 16:00 PM disposition: full run complete, F2 rework required

All20 canonical shards finished at15:51:31 on immutable97d56f1144cb721e7c5303f43ff71d291ed1d9bc:1062 modules,25378 passed,43 failed,162 skipped (25583 collected). Manifest/source/report equality verified; raw global gate red, no session/collection/unseen/expired problems. Evidence: full-suite-summary.json and original20 reports/logs. Source freeze released.

Independent actual Core/SQLite/HTTP/Chromium overlay campaign194a1246:2 passed/1 failed38.89s. Native dialog makes the fullscreen confirmation popover inert in both arrival orders. Go/Cancel are painted but inaccessible; Escape closing viewer restores them. No automatic fullscreen, scene revision/write or runtime error occurred. This is a real task blocker, not a baseline excuse. S05 acceptance reopened.

Authorized bounded policy: refuse viewer admission with clear French feedback while canonical fullscreen state is armed (including local requests without ID), preserving actionable prompt. When a fullscreen request arrives during the viewer, synchronously close it through its existing owner, including provider/read cancellation and focus restoration, then let canonical controller arm its normal prompt. Active-browser-fullscreen viewer refusal remains. Never automatically request/exit fullscreen; no new overlay manager, state owner, bus or wire protocol. S2 owns implementation/docs; S1 independently verifies affected arrival orders and existing-owner contracts. Preserve original red proof. Re-run affected gates after fix, not the complete four-hour suite without cause.

Remaining classification: six browser baseline comparisons, one Chrome-bootstrap-only current retry, one owned_read shutdown assertion. S1 assigned ONE uninstrumented exact-baseline whole-file backend run; earlier exact-case/pair passes and timed-out diagnostic are not proof of pre-existing failure. No daily Jarvis restart or paid model retry.


## Corrective conformance gate completed

At integration4ad30d43 the existing canonical runner executed the four whole affected files: test_scene_renderer_logic.py, test_scene_hold_desk.py, test_presentation_studio_reload_docs.py, test_presentation_studio_reload_host_js.py. Result117 passed,0 failed,0 skipped in27.8s; green, no stale/unseen/session issues. Original43-failure full-run evidence remains unchanged. This resolves exactly the four intentional-contract assertion failures, not the unrelated outstanding UI/backend cases. JSON/log in evidence/corrective-conformance-gate.*.

Fresh fetch16:07 Paris: origin/main remains exactc0858a80; no reconciliation delta. Product/docs/tests whitespace is checked separately from imported handoff Markdown hard breaks and raw JUnit evidence, whose historical formatting is retained.
