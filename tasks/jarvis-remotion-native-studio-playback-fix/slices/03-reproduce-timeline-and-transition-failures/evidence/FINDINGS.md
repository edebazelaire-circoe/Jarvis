# Slice 03: runtime reproduction findings

These findings were written by agent 0 from the Slice 03 Work Agent's report, because the harness refuses `.md` writes from that sub-agent. The raw numbers are in `summary.json`; logs and captures are in `runtime/`; the plain-Player control is in `control_group/`.

## Setup

**Code under test**
- Product SHA tested: `16d56857` (task base, no product change).
- Harness commit: `a5343198`, merged in `b524e5bf`.

**Runtime**
- Headless Chrome 154.0.8037.99 over CDP, Node v24.18.0, Windows 11.
- Remotion and `@remotion/player` 4.0.534, React 19.3.0, esbuild 0.28.1.

**Isolation**
- Reuses `RemotionStack`: free `127.0.0.1` ports, the sandbox on `127.77.0.2:<free>`, a throw-away data root.
- The live Jarvis was never contacted.

**Remotion runtime**
- No data root on this host has one installed.
- A read-only copy of an existing install was used. Its `runtime-host.mjs` and lock hashes match the shipped ones.
- The copy is passed with `JARVIS_REMOTION_RUNTIME_DIR`. No `npm install` was run.

**Fixture**
- 9 scenes of 3 s, 8 s and 30 s, at 24, 25, 30 and 60 fps.
- Anchors on S2, S5 and S7 only.
- Every score item targets 8000 ms, so S3 is a 900-frame composition with an 8 s target.

## Results per defect

| Defect | Reproduced | Key evidence |
| --- | --- | --- |
| A: playback does not start or continue | **Yes, severe** | See A below |
| B: flash or stutter at boundaries | **Partly** | See B below |
| C: next scene starts mid-animation | **Partly** | See C below |
| D: inner scrub does not move the outer clock | **Yes** | See D below |
| E: per-slide dwell cuts an animated scene | **No** | The 30 s scene with its 8 s target played to frame 899. The band only *displays* « 00:37 / 00:08 ». The « 8 s par slide » selector does not exist in this code base. |
| F: overlapping controls and disconnected state | **Yes** | At one instant, screen and Core give four different times for the same picture |

### A: playback does not start or continue

**Run with `scope: all`:** scenes without anchors that are followed by another scene are never shown.
- In one run S3, S6 and S8 never appeared. The previous picture stayed frozen for 78.0 s, 51.1 s and 51.0 s.
- 74 s of content took 232.9 s to play.
- Which scenes survive depends on message order, but at least 2 were lost in each of 3 runs.

Mechanism:
1. A scene without anchors has a single segment, so its first timeline event already preloads the next scene (`player.js:437-457`, `scene_page.js:1798-1806`).
2. `mount` of the entered scene defers its takeover (`prefab_host.js:657`).
3. The next `preload()` then drops it through `dropNext` (`prefab_host.js:693`).
4. The follower keeps returning `swap_wait` (`remotion_frame.js:177-178`).
5. Core waits the segment time, plus a 3 s grace, plus a 45 s load allowance, then skips the scene (`autoplay.py:106-111`).

**Variants buttons:**
- « Tout jouer » starts a `manual` run and closes the Explorer. After 9 s, Core is still on scene 1 (`explorer.js:501,511`).
- « Jouer cette slide » also starts a `manual` run and closes the Explorer.

**Manual run, scene without anchors:** the Player loops forever, wrapping at 4378 ms and again at 7311 ms (`playback.py:902-903`, `prefab_host.js:442-450`, `loop:true` at `remotion_sandbox_child.js:119`).

### B: flash or stutter at boundaries

**Variants remounts on every slide change** (`explorer.js:602`, no `swapPrefix`):
- the DOM has no ready frame for 149 ms and 190 ms;
- the screen stays dark for 1251 ms and 1226 ms after the click.

**Run stage window:** no white or dark capture over 4 swaps, about 150 captures at 20 Hz.

**New finding:** on a swap, `mount` pushes the next scene's props into the outgoing Player (`prefab_host.js:652` → `update` at `:713-717`). During the S3 stall, the screen showed S2's frame 239 with S3's title and colour for 78 s (`runtime/play_all-stall.png`).

### C: next scene starts mid-animation

**Every scene that was shown started at frame 0:** 6 of 6 in the run, 3 of 3 in the preview. The race between `play` on ready and the host's pause never showed.

**What looks like a mid-animation start has two other causes:**
- the hybrid frame described under B;
- a scrub clears the stop frame (`remotion_sandbox_child.js:97`):
  - in manual scope, S2 ran on to frame 149, into the next anchors;
  - in `scene` scope, S3 wrapped from frame 896 back to frame 4.

### D: inner scrub does not move the outer clock

**One instant, Player at frame 79:**

| Readout | Value |
| --- | --- |
| Stage bar | « 2.6 s / 30.0 s » |
| Band | « 00:04 / 00:08 » |
| Core segment clock | 2770 ms |
| Core item clock | 5060 ms |

**After a scrub to frame 600:** the Player was at 21.3 s, the band at 00:06 and Core at 4.4 s, a 16.9 s gap.

**End of the scene:** the Player reached its end at 13.5 s. Core ended the scene on its own deadline 20.3 s later, and the follower then jumped the Player from frame 612 to frame 835.

## Who owns « 2.6 / 30 s » and « 2 / 8 s »

**« x.x s / 30.0 s »**
- Owner: the stage page's inner bar (`remotion_stage.js:440-448`).
- Clock: the sandboxed Player's clock, so it shows media time.

**« 00:0x / 00:08 »**
- Owner: the band (`player.js:363-366`).
- Clock: Core's score-item elapsed time, over `target_duration_ms`.
- It starts about 2.3 s early, because it counts the loading time.

Nothing couples these two clocks. A scrub stops at the host and never reaches Core (`prefab_host.js:455-466`).

## Control group: plain `@remotion/player`

- **Looping:** with `loop:true` the Player wraps every 3.0 s, exactly as in Jarvis. Jarvis's looping comes from its own setting.
- **End of composition:** with `loop:false` alone, the Player jumps back to frame 0 at the end. It holds the last frame only when `moveToBeginningWhenEnded:false` is also set. **Slice 06 needs both settings.**
- **Seeking:** `seekTo` while playing simply continues to the end.

The stalls, skipped scenes, hybrid frame, remount gap and clock split are therefore Jarvis behaviour, not Remotion behaviour.

## Release gate

File: `tests/unit/test_presentation_playback_release_gate_browser.py`, with its helpers in `presentation_playback_gate_world.py` and a `burst` action added to `_remotion_stage_browser.mjs`.

**10 strict xfails.** Each accepts only an `AssertionError`, so a broken harness fails instead of passing as expected.

| Test | Defect | Fixed by |
| --- | --- | --- |
| `play_all_shows_every_scene_in_order_from_frame_zero_without_stall_blank_or_cut` | A | Slices 05/06 |
| `one_clock_every_time_readout_shows_the_composition_time` | D/F | |
| `a_scrub_of_the_player_bar_moves_the_shared_clock` | D | |
| `after_a_forward_scrub_the_scene_ends_once_and_core_ends_with_it` | C/D | |
| `a_manual_scene_without_anchor_plays_once_and_holds_its_last_frame` | A/C | |
| `a_manual_scrub_back_while_playing_is_honoured_and_the_segment_still_stops` | C/D | |
| `variants_slide_change_never_shows_an_empty_preview` | B | |
| `variants_preview_plays_a_slide_once_and_holds` | A/C | |
| `variants_play_all_plays_the_whole_presentation_inside_variants` | A | |
| `variants_play_this_slide_plays_the_slide_in_scene_scope` | A | |

**2 regression guards that pass:**
- `a_30s_composition_with_an_8s_score_target_plays_to_its_last_frame`
- `a_manual_scrub_of_a_held_segment_is_kept`

**Run results**
- The whole file gave 2 passed and 9 xfailed in 146 s; the play-all test xfailed on its own run in 237 s.
- Without `JARVIS_REMOTION_RUNTIME_DIR`, all 12 tests skip in 1.5 s.

**Command**, from the worktree:

```
JARVIS_REMOTION_RUNTIME_DIR=<runtime copy> [JARVIS_PLAYBACK_GATE_EVIDENCE_DIR=<dir>]
<repo>/.venv/Scripts/python.exe -m pytest tests/unit/test_presentation_playback_release_gate_browser.py -q -p no:cacheprovider -rxXfE
```

The whole file takes about 6.5 min. Run `-k play_all_shows` on its own.

**Known risk:** if a lucky message order happened to save every anchorless scene, the play-all xfail would pass and fail as strict. This was never observed: at least 2 scenes were lost in every run.

## Not run

- **Native Remotion Studio as a control group:** it needs the managed Studio process and the unsandboxed-trust acknowledgement. The plain-Player control covered the Remotion side.
- **Mixed fps inside one composition:** fps is set per scene, so rates are mixed only across scenes.
- **Transitions:** there is no whole-deck composition, so only boundaries between separate per-scene Players were measured.
- **Frame-exact screen captures:** CDP captures about every 50 ms, so a single 16 ms flash could fall between two captures. Start and stop frames come exactly from the Player's own clock.

## For the canonical docs

To be folded in by the slices that change the behaviour (05, 06, 15):
- `presentation-studio.md`, *Chained playback*: anchorless scenes followed by another scene are skipped after a long stall.
- `:2367` and `:2504`, « no blank, no remount »: false for the Variants preview, and silent about the outgoing frame receiving the next scene's props.
- `:2466`, « plays ONCE and holds »: true only in `scene` and `all` scope. Manual runs and the Variants preview loop.
- Add the gate file to `OPERATIONS.md` and to `scripts/remotion_player_harness.py`.
