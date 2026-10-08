# QA-1 - Slice 14 (Jarvis presenter and locked sequences)

Tier: standard + agent-trace-analysis + runtime-validation. Commit `ebe42b74` (detached worktree `bipq`, diff `2b3a45d8..ebe42b74`, 5 S14 commits). Product code untouched; `git status` clean before and after; HEAD checked.
Verdict recommendation: **REWORK (small)** - 1 BLOCKING, 3 POLISH, 3 ISSUE. Everything else holds.

## Runtime evidence (all one file at a time, Python venv of the main checkout, PYTHONPATH=bipq)

- 12 new files: sequence 25, sequence_machine 20, line 12, presenter 22, presenter_sequences 25, presenter_property 26, presenter_speech 4, presenter_routes 4, presenter_js 8, presenter_browser 2 (real Chrome + real Core), presenter_docs 7, presenter_trace 2 - all green.
- Regression set, all green: playback 257, playback_docs 9, playback_rework 18, playback_routes 13, playback_service 39, player_js 27, player_browser 4, player_realpage_browser 5, score 129, score_edit 6, score_service 34, stage 13, timeline_events 5, turn_authority 31, response_policy 119, tool_brain_speech 15, conversation_events 142, control_center_timeline_js 72 / ui 13 / browser 3, documented_routes 3, v2_architecture 8.
- Evidence replay: re-ran `JARVIS_WRITE_TRACE_EVIDENCE=1` on the trace test, `git diff` empty: committed `evidence/scripted-presentation-trace.json` is byte-identical to a fresh replay (then `git checkout`, clean). The test itself does not compare to the committed file (only writes it) - POLISH-3 below. Evidence JSON grep: no script text, no marker, no user name/path. "not_run_live" list is honest.

## Mutations (5, riskiest first, each restored, `git status` clean)

| # | Mutation | Killed by |
|---|---|---|
| M1 | `announce_notice` called twice per line | presenter, presenter_sequences. **Survives presenter_property** (it counts `issue_log`, not brain calls) |
| M2 | speak a user item (its note) | presenter, presenter_property |
| M3 | pause duration not added to `shift` | presenter_sequences, sequence. **Survives presenter_property** (never pauses) |
| M4 | interruption policy ignored (`refuse` branch removed) | presenter_sequences |
| M5 | spoken text added to a diagnostic row | presenter (privacy spy) |

All five killed by the suite as a whole. Weakness only in the property file (POLISH-2).

## My own adversarial runs (scratch scripts, not in the repo)

- Own property test on the pure module: 30 random trials x 1000 steps, random polls, random pause/resume: every release at exactly `t0 + shift + offset`, in order, once, never early, end at `t0+shift+duration`. No drift. (Score model caps a sequence at 32 steps, `MAX_STEPS`; 300 steps is not reachable through Core, only through the pure module.)
- Real monotonic clock, real `_loop`, slow `announce_notice` (200 ms): steps released 1, 0, 9 ms late; run completes and detaches. No busy loop: pumps/second while waiting on a user item = 0, paused = 0, playing with pending pause = 2.
- announce refused / raising (exception message containing the marker): pause `announce_refused` / `announce_failed`, resume retries once, run continues. No marker anywhere (events, views, diagnostics, `action_log`).
- Double start refused (`already_running`). Stop during a step: no further call after 20 s. 50x resume spam: no duplicate step, steps `intro, mid, wrap` once. 200-round interruption storm (floor + turn + cut + resumes): 3 announce calls total, no marker leak.
- Clock backward 50 s: nothing released, no crash, elapsed 0. Forward 500 s: `speech_stalled` pause (180 s limit), no skipped or doubled step. Mode change mid-run (PRESENTATION): run stops, nothing said afterwards.
- Stale events: a `brain.speech.requested` of another run key and a `started` for a foreign speech id are ignored; our line stays `pending` until its own id starts.

## Findings

### BLOCKING

**B1. A user-presented run is paused by every admitted user turn; docs say the opposite.**
`presentation_studio_presenter.py:472-478` (`_absorb`: `USER_TURN` sets `run.signal` unconditionally) + `:358-359` (`_drive` interrupts before looking at `run.speaks`). Scenario (reproduced, `user_presenter` run, no sequence, no Jarvis line): `user.transcript.accepted` -> run goes `paused`, `interrupted: true`; `next` is then refused (`paused`). Docs `presentation-studio.md` ("in a user-presenter run it executes locked visual sequences and nothing else (the user paces)") and Slice 12/13 behaviour say Jarvis must not move a user-paced run. In PRESENTATION mode an explicit "Jarvis, ..." is an admitted turn, so any aside, or the voice navigation Slice 21 will add, stops the user's own presentation and the cue follower with it. No test covers `speaks=False` + user turn. Fix: for `not run.speaks`, ignore `USER_TURN`/`FLOOR_TAKEN` unless a locked sequence is running (the policy then applies), plus a test.

### POLISH

**P1. False `speech_not_started` when a step line queues behind a long earlier line.** `_judge` (`:556-557`) times a PENDING line from its issue, but `_drive_sequence` (`:643`) issues the next step line while the previous one is still PLAYING (only an *unstarted* line blocks). Reproduced: intro playing 17 s, `wrap` issued at 6.5 s, run paused with `speech_not_started` at +10.5 s although nothing failed. Visible and retryable (not a hang) but wrong reason and a needless pause for any score whose spoken steps are closer than the TTS duration. Fix: count the start timeout only while no other line of the run is PLAYING.
**P2. Property test is blind to double-speech and to pause shift** (M1, M3 survive `presenter_property`). `issues <= 1 + resumes` counts the presenter's own `issue_log`; assert on `FakeBrain.calls` and add a pause/resume to the sequence walk.
**P3. Trace test never compares to the committed evidence**; it only writes it under an env var. Add a comparison of the structural keys so the file cannot drift. Also all times in the evidence are fake-clock (`lag_ms: 0`, `at_ms: 0`): it proves ordering and count, not latency (the file says so).

### ISSUE (non-blocking, for the PM Issue list)

**I1. "started" is not "audible", so the single-slot claim has a gap.** `mouth.speech.started` is recorded after `speak_reserved` returns (`speech_scheduler.py:2840-2843`, trace text "Speech generation requested"), while the output admission becomes non-invalidatable only at the first audio write (`realtime_audio.py:995`, `output_admission.invalidate` only acts in RESERVED). A same-key line issued in that window (two spoken steps a few hundred ms apart) can invalidate the line the presenter believes is PLAYING. The presenter would then see obsolete/interrupted and pause. Code reading only; not reproducible without the real stack. Add to the OPERATIONS human check 2 (spoken steps < 1 s apart). Also the docs say "the first words and the first visuals are together": t0 is generation request, so the visuals lead the audio by the voice latency; soften that sentence.
**I2. Authority.** The presenter run cannot start from ambient text or a brain tool today: no tool, route or intent starts playback besides `POST .../playback/start`; the relay forces `actor: user` and the explicit origin. A direct Core caller can: reproduced on the wire, `actor: brain` with no origin -> 409 `mode_switch_refused`; `actor: brain` with `origin: explicit_user_request` -> **200 applied**, a Jarvis presenter run starts. This is the Slice 12 start contract (the caller declares its origin; Slice 21 "sets it from the turn"), not new in S14, but S14 makes the run speak. Slice 21 must derive the origin from the admitted turn and never accept a model-supplied `origin`; Core cannot tell today. `skip_sequence` with `actor: brain` is refused (400), good.
**I3. Floor-taken is not noise-filtered.** While a line is outstanding or a sequence runs, any `mouth.floor.taken` pauses the run (`:472-479`); a cough on an `allow` item pauses it. Safe direction (explicit continue) but needs real-voice data.

## Contract checks (all pass unless listed above)

- Speech path: only `announce_notice` with `ScoreLineNotice.call_kwargs()` (`kind=progress`, `supersedes_key=presentation_studio:<run_id>`, `ttl_s=30`). Grep of the new code and the diff: no provider, TTS, speech-request or second speech call anywhere else. Silence items speak nothing but the bound actions run (machine, on entry). A `user` item: nothing spoken, `note` never read (code and M2).
- Locked sequence: t0 = first words started, else explicit start; steps due at `t0 + shift + offset`; pause adds its whole duration; no drift (own 30x1000 test + implementer's 1280). `allow/at_boundary/refuse` match the Slice 10 declarations (machine table test cell by cell; a locked host cannot declare `allow`). Recovery points land per `recovery_position`. `skip_sequence` user-only (400 for `brain`).
- Speech-id learning: bound only from `brain.speech.requested` with this run's key; stale ids kept in a bounded set; facts cleared on attach; verified with foreign/old events. Residual edge (negligible): an abandoned unbound line whose requested event arrives late could bind to its re-issue.
- Single slot: unstarted queued lines of the same key are dropped by the scheduler, but the presenter never has two unstarted lines (one pending at a time) so nothing is lost silently; a playing line is not cut by a new one once audio began (see I1 for the window before).
- Failure codes: announce False/raise, never starts 10 s, stalled, failed, obsolete, unconfirmed, line_invalid, presenter_crashed - each a paused run with a code, one retry per resume, no hang; crash ends the run cleanly (`finish`, mode restored).
- Core restart / mode: run and presenter are memory; documented, S12 owns the restore; manual mode change stops the run (reproduced). Closing order in `v2_app` (presenter first) is right.
- Interruption: floor-taken only counts with an outstanding line or a running sequence; admitted turn always (B1 for user runs); signals at or before `resumed_at_ms` are dropped (the "continue" turn). Attack: a genuine interruption in the same millisecond as the resume is dropped (`<=`), practically nil; a late-delivered pre-resume signal counts as new (safe direction). Nothing swallowed in the storm run.
- Privacy: no marker in diagnostics, events (`content="forbidden"`, code through `safe_error_class`), views, `action_log`, evidence. Exception text never copied (only class).
- Event `presenter_changed`: Python enum + spec `content=forbidden`, JS map `['system',I,D]`, left-rail set, French label "Presentateur Jarvis"; parity tests pass. The JS diff also repaired a duplicated/broken line in the rail set (two `edit_committed` lines) - fine.
- Playback additions (`epoch`, `resumes`, `resumed_at_ms`, `stage_scene_id`, `halt`, `finish`, `notify` verbs): 257+39+18 playback tests and the S14 random walk pass; `_ms` now `round()` (was `int()`), harmless.
- Module sizes: presenter 790 lines (the big one; `playback.py` is 1045, `brain_service.py` 2694, no repo limit found), sequence 270, line 125. Split not required.
- Docs: accurate on policy, failures, human checks, "Not run live by this Slice: nothing was spoken on a real voice stack" is honest. Corrections: I1 sentence on synchrony; B1 sentence once fixed.
- Agent trace: calls per line = 1 (4 lines, 4 announce, 0 retries, 0 duplicates), deterministic (two replays identical), 2 machine transitions per line for `speaking` (noted by the implementer as optimisation, acceptable), no unnecessary reads.

## Band UI (real headless Chrome, isolated Core on free ports, own data root; never 17653/17654)

- Jarvis run on a Core with no intention: band "Jarvis présente / En pause / Jarvis se tait (pause)", reason in French ("Jarvis n'a pas pu prendre la ligne ..."), button "Continuer" enabled, "Précédent/Suivant" disabled while paused, "Sortir de la séquence" hidden outside a sequence.
- Speaking indicator: forced the machine `speaking=jarvis`: band shows "Jarvis parle" (`data-state=speaking`). Progress bar: `role=progressbar`, text "Séquence 1/2 · .. / 30,0 s" advancing, `Sortir` leaves it (implementer's browser test, re-run green).
- HUD overlap: none at 1280x720 (band 202-782 x 445-702, HUD 18-186 x 648-698) and at 800x600 (band 212-782, HUD 18-186); HUD reachable at its centre. No console error or warning in my runs.
- Keyboard: unchanged code paths; the real-page key tests pass. My own attempt to focus the stage at 800x600 failed (selector not found), so keys on a paused Jarvis run were not re-checked by me.

## Answers to the three open questions

1. Target duration of speech items is never a minimum dwell: **agree, accept**. It matches the score contract (soft target) and keeps "end = mouth says completed". Authors who need dwell use a silence item or a locked sequence; add one sentence to the authoring doc.
2. Jarvis waits for the user's own items: **agree, accept**. Never reading a `note` is right. Note there is no timeout on a user item (no hang detection, by design: the user paces).
3. Noise-filtering floor-taken later: **accept the deferral**, track as I3 and decide with real-voice data (Slice 22 or the Human check): candidate rule is to require the cut/turn signal, or a short debounce, on `allow` items only.

## Residual Human checks (unchanged, correctly declared)

Audible output, real barge-in, latency between issue and first words (I1), the two spoken steps closer than ~1 s, projector look. Not run live by QA either.
