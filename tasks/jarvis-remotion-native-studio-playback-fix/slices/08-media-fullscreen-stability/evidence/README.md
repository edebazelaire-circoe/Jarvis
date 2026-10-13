# Slice 08 evidence — media, fullscreen, external display

Tested head: `006c659c` (see `summary.json`). Headless Chrome 154 over CDP, `RemotionStack` on free loopback ports, throw-away data root,
private Remotion runtime (junction to the read-only gate install). The live Jarvis was never started, stopped or contacted.

## What real Chrome proved

| File | Proof |
| --- | --- |
| `sound.json` | Muted at opening. A real CDP click on « Son » makes the scene audible through the cross-origin sandbox (`allow="autoplay"`): Remotion's `<audio>` unmuted and playing. Audio vs drawn frame, read in the same instant: 6–41 ms (S1, after a 1 s jump back, after the boundary into S2). The preloaded S2 frame stays muted; one audible Player at any sample; `M` mutes. |
| `sound-refused.json`, `sound-refused-lifted-000.png` | Frame forced to the pre-Slice-08 `allow=""`: the click on « Son » is refused and said (notice, pill on the image, button marked), the Player is never unmuted against the browser; one real click in the image lifts it and the scene plays with sound. |
| `sound-no-gesture-default.json` | No user activation anywhere (script `.click()`): sound refused and said, Player muted again by the stall watchdog, the image keeps moving (frame 73 → 105). |
| `sound-no-gesture-no-user-gesture-required.json` | Same path with `--autoplay-policy=no-user-gesture-required` (reference measure only): plays with sound. |
| `fullscreen.json`, `fullscreen-S1..S4-000.png` | 1920×1080: « Plein écran » makes the stage the fullscreen element (no tree, metadata, actions, strip); content box ratios 1.778 / 1.333 / 0.563 / 1.0 for 16:9, 4:3, 9:16, 1:1 on black; `f` and play state kept in and out; overlay hides while playing, returns on a mouse move, stays while paused; `F` leaves and the focus returns to the opener; first `Échap` leaves fullscreen only (still playing), the next closes Variants; windowed stage stays 16:9 at 1920×1080, 1600×900, 1024×768. |
| `scene-keys.json` | After a click in the scene (focus in the cross-origin frame): Space plays then pauses, → goes to S2 frame 0 once, M toggles once, `Échap` closes Variants, F enters the stage fullscreen. A key posted by the scene without the focus is refused (`keysRefused`), nothing moves. |
| `robustness.json` | Reduced motion: overlay hides with no transition, zero UI transitions/animations. Ten cycles (fullscreen in/out, next scene, play/pause): iframes ≤ 2, listeners (`message`, `resize`, `keydown`, `fullscreenchange`) unchanged, DOM node count unchanged. After a Chrome reload: muted, windowed, paused on S1 frame 0. |
| `export.json` | Real MP4 export of an `<Audio>` scene: runner verification by ffprobe, one h264 stream and one AAC stream of 2.0 s. |

What headless Chrome cannot prove: that sound comes out of real speakers; the physical `Échap`; a real second screen or projector.
Observed headless quirk: once the page has been fullscreen, an `Échap` typed inside the cross-origin scene is not delivered to it any more
(the top document still receives it); the tests check `Échap` from the scene before any fullscreen.

## Human check list — HV-RFX-08-01 (projector / second monitor and audio)

Open the Control Center normally, open Variants on a Remotion presentation that has sound (or add a `public/*.wav` and `<Audio>` scene).

1. Variants opens paused and silent; « Son » shows the muted icon (« Activer le son (M) »).
2. Click « Son », then « Lire »: the sound is heard from the speakers, in time with the image. Press `M`: silence; `M` again: sound.
3. Let the video cross into the next scene with sound: the sound continues without a click; it never plays twice at once.
4. Click in the image, then press Space, →, `M`: each acts once (play/pause, next scene, sound).
5. Drag the Jarvis browser window onto the projector or second monitor. Press « Plein écran » (or `F`): the slide fills that screen, whole, black bars where the format differs, no tree, no metadata, no Board, no Jarvis graph.
6. While it plays, do not move the mouse: the transport disappears after about 2.5 s; move the mouse: it comes back.
7. Press the physical `Échap`: fullscreen ends, the video keeps playing, Variants stays open; press `Échap` again: Variants closes.
8. Optional: with the browser's « Gestion des fenêtres » permission granted, `Maj+F` opens fullscreen on the other screen; without it, a message says to move the window.
9. On the projector, check sound still follows the image after a scrub and at a scene change.

Record pass/fail per step and the screen/projector model in the Human validation note.

## Rework after independent QA (REWORK: product correct, tests missing)

**Decision.** `allow="autoplay"` on the scene iframe is kept, as QA recommended: **decided by agent 0 (Human delegated autonomy)**. Its
residual (a scene, hidden or preloaded included, can play its own `new Audio()` after any gesture in the page) is written in
`docs/remotion-isolation.md` § 10.6 and in the *Variants media and fullscreen* section of `docs/presentation-studio.md`.

**Mutant kill table.** Each mutant was applied alone in the worktree, the named test run, the file restored (no mutant left in the tree;
`git diff -- jarvis` shows only the `S.fsOpener` fix). Every new test passes on the real code.

| Mutant | Where | Test that kills it | Failure under the mutant |
| --- | --- | --- | --- |
| M1b: `host.sound()` also posts `sound` to `rec.next` | `control_center_prefab_host.js` `sound()` | node `test_variants_media_js.py::test_toggling_the_sound_while_a_frame_is_loaded_ahead_never_reaches_the_preloaded_frame` | « the preloaded frame never receives `sound` » |
| M1b (real Chrome) | same | `test_variants_media_fullscreen_browser.py::test_a_real_click_on_son_...` check « « Son » pressed off then on while S2 is preloaded: … the preloaded S2 frame stays muted » | that check alone false |
| M4: Échap in stage fullscreen also pauses | explorer `escapeKey()` | node `test_escape_in_the_stage_fullscreen_while_playing_leaves_it_and_never_pauses` (Échap on the stage, on the page body, relayed by the focused scene; phase `playing` before) | `phase: 'paused'` after Échap (stage) |
| M4 (real Chrome) | same | `test_fullscreen_shows_only_the_whole_slide_...` check « an Échap that reaches the page handler in the stage fullscreen, while playing, leaves it and never pauses » (keydown dispatched to the stage element: the CDP Échap is kept by headless Chrome) | that check alone false |
| M7: no `isPlaying()` guard in `watchAudio` | `remotion_sandbox_child.js` | node `test_the_stall_watchdog_never_re_mutes_a_player_the_user_paused` (unmute, play, pause, +3.2 s; and « Son » pressed while paused) | Player muted, `audio {muted:true, blocked:true}` sent |
| M10: `sound.reset()` commented out | explorer `open()` | node `test_sound_is_muted_again_when_variants_is_reopened_in_the_same_page` | « Son » still `aria-pressed="true"` after the reopening |
| fsOpener set before the request | explorer `toggleFullscreen()` | node `test_the_focus_opener_is_kept_only_when_the_stage_fullscreen_really_starts` | refused request: focus went back to the stale opener |
| `parseExact` without the extra-field check | `control_center_remotion_frame.js` | node `test_the_window_parsers_of_audio_and_key_refuse_another_source_another_origin_and_an_extra_field` | `extra_field` accepted |

**Code change.** `S.fsOpener` is set only when the stage fullscreen really started (`entered` and `document.fullscreenElement` is the
theater); a refused or armed request keeps none, and a stage fullscreen started later gives the focus to « Plein écran ».

**Inspector flake (`test_presentation_studio_explorer_browser.py::test_the_inspector_header_opens_…`, `inspectorBehind` false).** Root
cause found, in the test, not in Slice 08 code: `#jvStudioInspector` lives inside `#app` (next to the dock), so the explorer's `inert`
goes on `#app` and the panel's own `inert` stays false; the panel's `hidden` turns true only when the inspector handles the
`fullscreenchange` of the workspace fullscreen the click asked for. The test read right after `state().open === true`, which is set
before the fullscreen is requested: a race against an asynchronous browser event. Measured in the reworked test (`fs_at_open`): one
run in six read `{"fs": true, "hidden": false}` at that instant (fullscreen element set, inspector handler not yet run), which is
exactly the old failure. Slice 08 only made the synchronous part of `open()` slightly longer (theater, sound button), widening the
window. No stage fullscreen is involved on that path. The test now waits for `document.fullscreenElement` and the inspector hidden,
then also asserts the panel is under an inert ancestor (`closest('[inert]')`).

**Test results on the rework (one file per process, foreground).**

| File | Result |
| --- | --- |
| `test_variants_media_js.py` | 21 passed (6 new) |
| `test_variants_media_docs.py` | 2 passed (§ 10.6 wording pinned) |
| `test_variants_media_fullscreen_browser.py` | 7 passed |
| `test_remotion_isolation.py` | 229 passed |
| `test_remotion_sandbox_protocol_js.py` | 16 passed |
| `test_remotion_stage_js.py` | 26 passed |
| `test_prefab_host_swap_race_js.py` | 2 passed |
| `test_variants_transport_js.py` | 29 passed |
| `test_variants_transport_browser.py` | 5 passed |
| `test_presentation_studio_explorer_browser.py` × 6 | 5 runs 18/18; 1 run 17/18: `test_activate_branch_rename_archive_and_restore_…` failed on console noise `sequencer_unavailable {"code":"presentation_studio_unknown_variant","retryable":true}` (the Variants sequencer of Slices 05/06 reading an archived variant), not the inspector test, which passed 6/6 |
| explorer node files (`_js`, `_lifecycle_js`, `_rework_js`, `_view_js`) | 1, 19, 9, 15 passed |
| release gate `-k "not play_all_shows"` | 12 passed, 1 xfailed (`test_a_presenter_run_scrubber_is_read_only`, Slice 09/10) |
