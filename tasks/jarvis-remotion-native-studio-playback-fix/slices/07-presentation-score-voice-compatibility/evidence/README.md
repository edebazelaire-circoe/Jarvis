# Slice 07 evidence: presentation score and voice compatibility

Tested HEAD `85326358`. Nothing here was spoken on a real voice stack; every speech fact is a fake (`tests/fakes/presentation_studio_presenter.py`).
The live Jarvis (Core `127.77.0.1:17653`, its voice, `project jarvis`) was never started, stopped or contacted.

| File | What it shows |
| --- | --- |
| `summary.json` | checks and their result, the finding below |
| `presenter_entry_reveals_anchor_S2.json` | real Chrome, run stage: a presenter run enters S2 whose entry item reveals an anchor at 2 s; Core says `from_frame` 0 / `until_frame` 149, the Player is ordered `play 0 -> 149`, first moves at frame 0, never steps back, holds 149 |
| `finding_next_by_core_route_grace_race.json` | the same scene entered by a `next` posted to Core (as a cue or the voice does): the host's own grace play starts the Player before the band's poll brings Core's order, which then replays from 0 (pre-existing, owner Slice 09) |

Contract: `docs/presentation-studio.md` > *Presentation experience contract* § 5 (*Implemented (Level 3, Slice 07)*).

## Human checks

Slice 07 claims **no** live voice, microphone, audio-routing or second-screen proof. These are for the Human, on the target machine (HV-RFX-07-01).
Recipe context: `docs/OPERATIONS.md`, *Lecture d'une présentation*, *Présentation par Jarvis*, *Suivi des cues à la voix*.

1. **Spoken cues, real microphone.** `user_presenter` run on a Remotion deck whose next item has a cue, voice architecture with the OpenAI ambient stack. Say the cue phrase: the run moves once; a newly entered scene starts from its first image (no jump into the middle of its animation); saying the phrase inside a question, a negation or a quote does not move it.
2. **Cue path down.** Same run on a voice architecture without the ambient lane (`legacy` or `duplex`), or with Voice stopped. Within about 10 s the band says « Suivi vocal indisponible … La lecture continue au clavier et à la souris. »; `→` / « Suivant » still move the run; the scene still plays and holds.
3. **Jarvis presents, real voice.** `jarvis_presenter` on a deck with an explicit silence item on a Remotion scene: Jarvis's lines are heard one after another, each ends before the next item; the silence lasts until the scene's animation reaches its stop image (never cut at the item's target time); the media keeps its image while Jarvis speaks.
4. **Voice not started.** Same run with Voice stopped: after about 10 s the run pauses with « La voix n'a pas commencé la ligne à temps … »; the image holds; « Continuer » then « Suivant » move the run on without the voice.
5. **Interruption.** During a Jarvis line, speak over it: the run pauses (or waits for the item's boundary when the score says so) and resumes only on « Continuer »; the image is not replayed from the start of the scene.
6. **Audio routing.** Unmute the scene (a click in the image), then check that the scene's own sound and Jarvis's voice come out of the intended output device and that Jarvis's voice is not cut by the scene's sound (or the reverse) on this machine.
7. **Dual screen.** Move the Jarvis browser window to the external display, start a presenter run, press « Plein écran »: the stage fills that display; `→` / `←` move the run; `Échap` leaves fullscreen and does not pause the run; a newly entered scene still starts on its first image on the projector.
8. **Continuous video stays silent.** In Variants press « Lire » on the same deck with Voice running in PRESENTATION mode and say a cue phrase aloud: nothing moves, nothing is said, the mode does not change; the video plays on to its last image.

Record for each: the machine, the voice architecture, the output device, pass / fail, and the time the line or cue took (seconds from the words to the image).
