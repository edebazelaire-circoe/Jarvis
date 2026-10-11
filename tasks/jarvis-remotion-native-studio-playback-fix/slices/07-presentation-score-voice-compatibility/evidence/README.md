# Slice 07 evidence: presentation score and voice compatibility

Tested HEAD `85326358`. Nothing here was spoken on a real voice stack; every speech fact is a fake (`tests/fakes/presentation_studio_presenter.py`).
The live Jarvis (Core `127.77.0.1:17653`, its voice, `project jarvis`) was never started, stopped or contacted.

| File | What it shows |
| --- | --- |
| `summary.json` | checks and their result, the finding below |
| `presenter_entry_reveals_anchor_S2.json` | real Chrome, run stage: a presenter run enters S2 whose entry item reveals an anchor at 2 s; Core says `from_frame` 0 / `until_frame` 149, the Player is ordered `play 0 -> 149`, first moves at frame 0, never steps back, holds 149 |
| `finding_next_by_core_route_grace_race.json` | the same scene entered by a `next` posted to Core (as a cue or the voice does): the host's own grace play starts the Player before the band's poll brings Core's order, which then replays from 0. Finding 7: pre-existing (QA confirmed), owner Slice 09; Slice 07 made the visible jump-back larger for an entry that reveals an anchor (78 -> 0 instead of 78 -> 60), said in the file's `finding` field |

Contract: `docs/presentation-studio.md` > *Presentation experience contract* § 5 (*Implemented (Level 3, Slice 07)*).

## Rework (independent QA B1, I1, I2, I3, P1)

Tested HEAD `4497691d`; same rules (fake speech, the live Jarvis never contacted). `summary.json` › `rework` holds the findings, the mutant kills and the real-Chrome results.
- B1: a Jarvis silence over an HTML scene ends on its target, at the start and after a user `next`, with a stage whose `show` yields under the real presenter loop (`test_presentation_studio_presenter_media_rework.py`).
- I1: a Remotion scene without timeline is held during a Jarvis silence and said (`page_wait` reason `timeline_unresolved`). I2: a locked-sequence step 600 ms after the entry continues the entry (18 -> 299), never cut to the anchor.
- I3: mutants M3, M7, M11 killed, each verified by applying it and restoring with `git checkout`.

## Second rework (QA mutant, Agent 0 decision, Issue, polish)

Tested HEAD `8151092a`; same rules (fake speech, the live Jarvis never contacted).
- Mutant "`pending` treated as no media" (presenter `_drive_item` and `_next_deadline_ms`) killed by
  `test_a_video_silence_whose_stage_sync_outlasts_its_target_is_held_while_pending_never_paced_by_the_target`: each half alone and both together fail it.
- Agent 0 decision: the end of a Jarvis line (`line_heard`, `sequence_done`) is Jarvis pacing himself. The presenter sends `notify(NEXT, line_end=True)`,
  committed as `Move.STEP`: a line ending 500 ms into an entry continues it (15 -> 299), never cut to 180. A user `next` while Jarvis speaks, or a cue,
  still cuts (180 -> 299). Mutants killed: `line_end` always false; a user `next` mapped to STEP; the `_retime` wake removed; the `min(reached, until)`
  clamp removed (2.5 s into a 2 s entry, no `done` yet: 59, not 75).
- Real Chrome, release gate `-k "presenter or manual"`: 2 passed, 1 xfailed (presenter scrubber read-only, Slice 09/10, unchanged).

Recorded, not fixed here:
- A `SceneStage.show` that never resolves leaves the run stuck, and `stop` queues behind the playback lock. Predates Slice 07; owner Slice 09
  (stage lifecycle).
- A failed manifest read on an HTML scene is held with the "video timeline" message (`timeline_unresolved`). Accepted: an unreadable pin is held.

## Human checks

Slice 07 claims **no** live voice, microphone, audio-routing or second-screen proof. These are for the Human, on the target machine (HV-RFX-07-01).
Recipe context: `docs/OPERATIONS.md`, *Lecture d'une présentation*, *Présentation par Jarvis*, *Suivi des cues à la voix*.

1. **Spoken cues, real microphone.** `user_presenter` run on a Remotion deck whose next item has a cue, voice architecture with the OpenAI ambient stack. Say the cue phrase: the run moves once; a newly entered scene starts from its first image (no jump into the middle of its animation); saying the phrase inside a question, a negation or a quote does not move it.
2. **Cue path down.** Same run on a voice architecture without the ambient lane (`legacy` or `duplex`), or with Voice stopped. Within about 10 s the band says « Suivi vocal indisponible … La lecture continue au clavier et à la souris. »; `→` / « Suivant » still move the run; the scene still plays and holds.
3. **Jarvis presents, real voice.** `jarvis_presenter` on a deck with an explicit silence item on a Remotion scene: Jarvis's lines are heard one after another, each ends before the next item; the silence lasts until the scene's animation reaches its stop image (never cut at the item's target time); the media keeps its image while Jarvis speaks.
4. **Voice not started.** Same run with Voice stopped: after about 10 s the run pauses with « La voix n'a pas commencé la ligne à temps … »; the image holds; « Continuer » then « Suivant » move the run on without the voice.
5. **Interruption.** During a Jarvis line, speak over it: the run pauses (or waits for the item's boundary when the score says so) and resumes only on « Continuer »; the image is not replayed from the start of the scene.
6. **Audio routing.** Unmute the scene (a click in the image), then check that the scene's own sound and Jarvis's voice come out of the intended output device and that Jarvis's voice is not cut by the scene's sound (or the reverse) on this machine.
7. **Dual screen.** Move the Jarvis browser window to the external display, start a presenter run, press « Plein écran »: the stage fills that display; `→` / `←` move the run; `Échap` leaves fullscreen (on today's run stage the band still pauses a playing run on `Échap`; § 4.15 removes that with the band in Slice 09); a newly entered scene still starts on its first image on the projector.
8. **A Jarvis silence over an HTML scene ends on its target** (rework B1). `jarvis_presenter` on a deck whose first item, and a later one, is an explicit silence on an HTML scene (e.g. 2 s target): each silence ends about 2 s after its scene appeared, at the start of the run and after « Suivant »; the run never stays on it until a key is pressed.
9. **A page that goes silent shows the waiting notice** (rework I1). `jarvis_presenter` on a silence item over a Remotion scene, then close the run stage (or block the scene's page) while it plays: after the segment's length + about 15 s the band says « Scène n : lecture en attente de la page … « Suivant » ou « Arrêter » restent possibles. »; with a scene whose composition cannot be read, the band says « … la ligne de temps de la vidéo n'a pas pu être lue, la scène est tenue … » after the item's target + about 15 s; « Suivant » and « Arrêter » work.
10. **Continuous video stays silent.** In Variants press « Lire » on the same deck with Voice running in PRESENTATION mode and say a cue phrase aloud: nothing moves, nothing is said, the mode does not change; the video plays on to its last image.

Record for each: the machine, the voice architecture, the output device, pass / fail, and the time the line or cue took (seconds from the words to the image).
