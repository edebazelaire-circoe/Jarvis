# Slice 16: final implementation report

Task `jarvis-remotion-native-studio-playback-fix`, branch `task/jarvis-remotion-native-studio-playback-fix`.
Written by the Slice 16 Work Agent on 2026-10-13 and committed by agent 0, because the harness refuses `.md` writes from sub-agents.

- Steps 1-4 and 6 of `SLICE.md` are done.
- Step 5, the Human review, is prepared in § 9 and in `human-validation.json`.
- Nothing in this report is a Human approval.

## 1. Tested SHA

| What | SHA |
| --- | --- |
| Task base (wide baseline) | `a8377529` (product `16d56857` in Slice 03) |
| Slice 15 wide sweep | `c190f48e` (457 files) |
| Real-runtime run (§ 3) | `a437e5c2` (product code = `efa0cc08`: `b34d494a` + the S16 `confirmOpen` rename) |
| Failure-overlay fix, resilience runs, overlay-related reruns | `6aa93f20` |

The range `a437e5c2..6aa93f20` changes one CSS rule, tests and docs. Every file that draws or reads the failure overlay was rerun on `6aa93f20`.

- **Runtime:** headless Chrome 154 over CDP. `RemotionStack` runs a real Core, compiler and Control Center on free loopback ports, with a throw-away data root. Remotion comes from the read-only gate runtime (4.0.534).
- **Isolation:** the live Jarvis (Core `127.77.0.1:17653`, Control Center, voice, ai-visualizer) was never started, stopped or contacted.

## 2. Regression classification (step 1)

The baseline is `slices/00-project-manager/baseline.md` at `a8377529`: 16 failures that also fail when run alone, none in the presentation or Remotion domain. The full sweep was not rerun. This run covered:

- the 6 Slice 15 sweep failures;
- the 13 baseline files;
- every real-runtime and browser file listed in § 3.

| Test | `a8377529` | Sweep `c190f48e` | HEAD | Verdict |
| --- | --- | --- | --- | --- |
| `test_scene_interaction_logic.py::…never_uses_browser_dialogs` | passes | fails (`confirm(`) | passes (24) | **Task regression** from Slice 11 `a12c9672`: a local function was named `confirm`. Slice 15 called it pre-existing because it compared with `c486eae7`, a task commit. Fixed in `efa0cc08`. |
| `test_presentation_studio_edit_docs.py` | passes | fails | passes (6) | Task regression from Slice 13 `3da74f17`. Fixed in `b34d494a`. |
| `test_presentation_studio_authoring_remotion_browser.py` (needs the real runtime) | — | skipped | passes 3/3, twice | **Task regression in a test.** It expected one `iframe[data-remotion-stage]`, but since Slice 05 Variants preloads the next scene beside the visible one. Fixed in `6af80aed`. One earlier run stalled at the driver deadline (318 s); not reproduced in 3 later runs. |
| Failure overlay over the frame's own error panel (lost Core) | — | — | fixed | **Task defect** in the Slice 05 overlay: the texts overlapped and two « Réessayer » showed. Fixed in `6aa93f20` and asserted in real Chrome. |
| `test_control_center_voice_architecture.py` | fails | fails | fails | Inherited: the stub lacks `agenda_reminders`. |
| `test_scene_artifacts.py`, `test_scene_query_tools.py` | fail | fail | fail | Inherited: the pin `20a65470…` was already stale before the task. The hash moved from `fb9400af` to `87c9ecec` through intended prompt edits (S09 `bf676045`, S13 `aa061dba`). |
| `test_scene_group_drag_js.py` | fails | fails | fails | Inherited: stale source slice. |
| `test_app` (1), `test_barehands_interaction_js` (2), `test_brain_capability_parity` (1), `test_brain_delegation` (1), `test_tool_brain_choices` (1), `test_tool_brain_intents` (3), `test_interaction_mode_hud_browser` (1), `test_wake_word_settings_browser[cosmos]` (1), `integration/test_settings_redesign_migration` (1) | fail | outside the sweep | fail, with the same test ids and messages | Inherited. |
| Flakes: media fullscreen (Issue 01 I4), attention favicon, explorer upgrades | — | — | 7/7, 31/31, 3/3 | Not reproduced. |
| `test_remotion_import_real.py` | — | skipped | skipped | Needs `JARVIS_REMOTION_IMPORT_NETWORK=1`. Untouched by the task. |

**No failure is left unclassified, and no task regression is left open.**

## 3. Isolated machine run with the real runtime (step 2)

Each file ran in its own process, in the foreground, with a fresh data root. Every file passed.

| Area | Files (result) |
| --- | --- |
| Release gate | browser gate 14 passed + play-all 1 passed; `test_presentation_studio_release_gate` 6, `test_remotion_release_gate` 13, `test_remotion_release_flows` 1 |
| Continuous Player | continuous playback 2 (Variants warm; run from cold compiles), flow quality 3, frame quality real 3 |
| Variants | transport 5 (also on `6aa93f20`), controls 10, explorer 18, compare 3, upgrades 3, inspector 16 |
| Manual presenter, cues | Variants run 6, presenter browser 2, the gate's presenter tests; 17 cue, presenter and score unit files: 445 passed (fake speech) |
| Fullscreen, audio, export | media fullscreen 7; media export 2 (h264 + AAC 48 kHz stereo, checked with ffprobe) |
| Native Studio | round trip 1 (real `remotion studio`), Studio door 8, Studio real 1, shape real 1 |
| Remotion real pages | player 7, continuity 1, timeline 2, controls 1, source edit 1 |
| Other | reload browser 23, reload real page 2, authoring browser 3, rail 13, rail e2e 3, engine 4, attention 31, workspace 2, render real 2, authoring real 6, compiler real 16, isolation real 1, source edit real 1, media tools 12, swap race 2 |
| Resilience (new) | `test_presentation_resilience_browser.py` 2 |

Measured:

- **Play-all:** all 9 scenes play, in 83.4 s for 74 s of content, with Variants open and no Board stage. In the baseline, S3, S6 and S8 were lost (the previous image froze for 78.0, 51.1 and 51.0 s), and the run took 232.9 s.
- **Audio vs image:** 5-19 ms, and 46 ms just after a seek. The threshold is 200 ms. 9 checks out of 9 pass.
- **Remotion Studio:** cold open 75.2 s (62.0 s in Slice 12), hot reload 0.34 s, publish 0.78 s.
- **Fullscreen:** 12/12 checks; robustness 5/5; scene keys 7/7.

## 4. Scripted resilience (step 3)

| Scenario | Covered by | Result |
| --- | --- | --- |
| 9 scenes | gate play-all; continuous playback in Variants and in a run; the recorded flow | 9/9 in every run, each scene from frame 0 to its last frame, no wrap |
| 30 s scene | S3: 900 frames at 30 fps, score target 8 s | frame 0 to 899 in 29 982-30 015 ms; never cut at the 8 s target |
| Several fps | the deck mixes 24, 25, 30 and 60 fps | each scene plays its authored length: 25 fps 2 966-3 015 ms, 60 fps 7 989-8 007 ms, 24 fps 7 955-8 015 ms |
| Rapid seek | transport browser test: three fast « Suivant » presses, slider drags at 800x600 and 1280x720 | lands on S4 frame 0, one scene per press; slider, Player, readout and scene strip agree |
| Backward jump | « Précédent », scrubbing back, gate test `a_video_scrub_back_while_playing_is_honoured` | « Précédent » lands on S1 frame 0, paused; scrubbing back lands on S2 at 0:06 (frame 90); no re-seek order, no wrap |
| Cold cache | presenter run from cold compiles | hand-over gaps 13-42 ms |
| Warm cache | Variants « Lire » after one compile per scene | hand-over gaps 8-23 ms |
| Core restart (new) | Core stopped for 3.1 s during S2, then restarted on the same ports and data root | 9/9 scenes from frame 0 to their last frame. If the restart cut the next scene's preload, the first hand-over waits 393 or 404 ms on the held last frame; otherwise 10 ms. Compiled scenes survive the restart. |
| Lost connection (new) | Core unreachable for 20.1 s across the S2 → S3 hand-over | S2 holds its last frame. About 4 s later the failure overlay shows « Scène 3 : lecture impossible », the real reason, « Réessayer » and « Scène suivante »; S3 is never skipped. **Nothing retries by itself when Core comes back.** After « Réessayer », S3 plays 0 to 899 and S4-S9 follow; the S3 → S4 hand-over waited 407 ms. |

Not automated:

- **A physical network loss.** Everything runs on loopback, so a lost connection means Core's processes going away.
- **The user's own Jarvis restart.** Agents may not do it; the isolated restart uses the same code path.
- **Physical speakers, a second monitor and the physical Échap key.** These are Human checks (§ 9).

## 5. Transition discontinuity (step 4)

The gap is the time from the outgoing Player's last frame to the incoming Player's first moving frame, read from the Players' own clocks. About 35 screen captures were taken per hand-over.

| Measure | This run | Before (Slice 03) |
| --- | --- | --- |
| Variants, warm | 10, 8, 8, 13, 23, 16, 12, 11 ms; last frame → frame 0 at all 8 hand-overs; 0 blank and 0 mixed frames in 290 captures | Variants remounted at every change: blank for 149-190 ms, dark for 1.2 s |
| Presenter run in Variants, cold | 42, 17, 22, 18, 25, 13, 28, 26 ms; 0 blank and 0 mixed frames, 0 Board mounts, 0 Core deadline firings | S3, S6 and S8 never shown; a mixed frame (S2's image with S3's text) held for 78 s |
| Recorded flow | 680 captures over 74.1 s, verdict `clean`; slider lag max 283 ms (threshold 500); 8 scene changes, at 3.07, 11.11, 41.04, 44.09, 52.06, 55.12, 63.09 and 66.14 s | Slice 14: lag 250-283 ms |
| After an outage | 393-407 ms on the held last frame, at the first hand-over whose preload was lost | — |

Known limits, recorded rather than waived:

1. The slider trails the picture by up to 283 ms.
2. After an outage, the first hand-over can wait about 0.4 s on the held last frame.
3. Nothing retries by itself when Core comes back: the user must press « Réessayer ». This matches the contract (§ 4.11, PX-18). Filed as Issue 01 I7.
4. The failure text is the raw technical message (« Core is unreachable: ClientConnectorError … »). Filed as Issue 01 I8.
5. Screen captures are 50-100 ms apart, so a single-frame flash could escape the pixel measure. The Players' clocks are exact.
6. Remotion Studio's cold open takes 62-75 s. The door shows a counter while it waits.

No P0 visual, transition or playback defect is open.

## 6. Before / after screenshots

| Before | After |
| --- | --- |
| `../../evidence/01-unwanted-floating-viewer.png`; `09-…/evidence/screens/before-1793ad6e-floating-viewer-1280x720.png` | `evidence/after-a437e5c2-run-1280x720.jpg`; `09-…/screens/after-5870c17b-run-in-variants-1280x720.png` |
| `../../evidence/02-variants-screen-base.png`; `10-…/before-33015379-variants-1280x720.png` | `evidence/after-a437e5c2-variants-1280x720.jpg` and `-800x600.jpg`; `10-…/after-b8266568-*`; `11-…/after-a12c9672-*` |
| `03-…/runtime/play_all-stall.png`, `variants_clocks_S3-*` | `evidence/flow-transitions-a437e5c2.jpg`; `14-…/flow.mp4` |
| Lost Core before the fix, seen on `8c2328b6` (capture not kept): the frame's error panel showed through, with two « Réessayer » | `evidence/after-6aa93f20-lost-core-failed-1280x720.jpg`, `-lost-core-end-`, `-core-restart-during-` |
| No path from Variants to Remotion Studio | `12-…/studio-before-edit.png`, `studio-after-edit.png`, `variants-published-1280x720.png`, `variants-after-restart-1280x720.png` |

## 7. Retired paths, preservation, migration, rollback

**Retired.** The authoritative list is in `docs/presentation-studio.md`, section *Retirement map and migration readers (Level 3, Slice 15)*. More detail is in `09-…/evidence/README.md` § 1 and in `15-…/CLEANUP.md`.

- The floating run viewer: the Board windows `studio_stage` and `studio_aux`, and the band `#jvStudioBand` with its keys and fullscreen.
- The window host `control_center_presentation_window.js` (deleted).
- Variants « Jouer cette slide » / « Tout jouer », which closed Variants.
- The rail's « Jouer » and its auto-focus.
- `STUDIO_STAGE_PREFIX`, and the playback client's `chain()`.
- Core deadlines for Remotion scenes.
- `loop:true` and play-on-ready in Variants.
- The Variants variant bar and tree hint.
- Orphan CSS.

**Kept on purpose, as migration readers:**

- `LegacyStageReclaimer` and `StageLedger`: the old ledger is read once, then set aside as `.retired-<ts>`.
- `RETIRED_CATEGORIES`, `LEGACY_CATEGORIES` and the sanitizer pattern.
- Core's 400 answer on `open_window` / `close_window`. The MCP `window_*` tools now open Variants.
- `rs-bar` on generic Board Remotion windows, which are not a presentation surface.
- Slidecar, unchanged: an explicit Human experiment only, never a fallback.

**Source and variant preservation:**

- Old presentations open and play. The fixture `tests/fixtures/presentation_studio_task_base_a8377529/` holds data written by the task-base code; it is read and played, and its stored documents stay byte-identical after opening and after playing (digest check in both tests).
- « Publier » from Remotion Studio creates a new source version; the previous one stays available.
- Unpublished edits survive closing, the idle stop and a Core restart. Opening another version needs a confirmed discard.
- Planted files are set aside, never deleted.
- The version-pin format is unchanged.

**Migration: none.**

- No SQLite schema change: `_SCHEMA_VERSION` is untouched in both `sqlite_state.py` and `sqlite_scene.py`.
- No document format change.
- The only file-level effects: the stage ledger is renamed `.retired-<ts>`, and Studio edits are copied to `studio-edits/`.

**Rollback:**

1. Copy `presentations/`, `prefabs/`, `state/` and `local_capabilities/remotion/` from the data root.
2. Copy any unpublished Studio edits out.
3. Revert the merge commit, or the Slice commits listed in the LOG. No data step is needed.
4. Optional: rename `….retired-<ts>` back so an older Core re-reads the stage ledger.
5. The user restarts Jarvis. By design, there is no parallel UI to fall back on.

## 8. Remotion licence: pending the Human

The facts are in `15-…/CLEANUP.md` § 5 and in `docs/remotion-integration-release.md`, section *Remotion licence* (from the 4.0.534 `LICENSE.md`, SHA-256 `bd65083b…b673`).

- The Free License covers individuals, for-profit companies with up to 3 employees, and non-profits.
- Any other entity needs a Company License.
- Jarvis distributes no Remotion code and passes no `licenseKey`.

**No agent has decided this.**

## 9. Open Human checks

| Check | Recipe |
| --- | --- |
| HV-RFX-02-01: control hierarchy and two-view naming | `02-…/UI-INVENTORY.md` |
| HV-RFX-05-01: watch real continuous playback | Slice 05 evidence |
| HV-RFX-07-01: spoken cues, audio routing, dual screen | `07-…/evidence/README.md` |
| HV-RFX-08-01: projector, second monitor, audio | `08-…/evidence/README.md` |
| HV-RFX-09-01: the screenshot-1 experience never appears | `09-…/evidence/README.md` § 7 |
| HV-RFX-10-01: visual control audit, physical Échap in fullscreen | `10-…/evidence/README.md` |
| HV-RFX-11-01: Studio door, return, fullscreen and close | `11-…/evidence/README.md` |
| HV-RFX-12-01: trust and approval UX for unsandboxed editing | `12-…/evidence/README.md`, `DESIGN.md` |
| HV-RFX-13-01: blinded decks, verdict given before opening the key | `13-…/evidence/README.md` |
| HV-RFX-16-01 a-j: final approval | `human-validation.json` |
| Licence tier | § 8 |
| IGuard README in 19 earlier local commits: rewrite the history or not | LOG, Slice 13 |

## 10. Issue 01 carried forward

| # | State |
| --- | --- |
| I2 | Still present: the run slider shows no thumb or fill (`after-a437e5c2-run-1280x720.jpg`). |
| I3 | Code unchanged; carried forward. |
| I4 | 7/7 in this run; kept as a flake to watch. |
| I5 | Unchanged; carried forward. |
| I6 | Unchanged; carried forward. |
| I7, I8 | Known limits 3 and 4 of § 5. |

Slice 15 polish:

- P1-P4 are in `a437e5c2`.
- P8 is in the LOG.
- P5 could not be captured, because the gate deck has no upgrade notice. The dimming rule is pinned by `test_variants_css_orphans.py`.
