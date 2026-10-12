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
