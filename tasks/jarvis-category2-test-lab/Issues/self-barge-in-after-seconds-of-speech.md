# Self barge-in after several seconds of continuous speech

- Opened: 2026-09-18, Slice 09 (hardware profiles), from QA's duration sweep.
- Status: **open question, not a confirmed product defect.** It cannot be settled with a
  double. HV-TL-HW-01 is the measurement that settles it.
- Blocking? **No** for Slice 09. It must be read before anyone acts on a
  `voice.self_echo` result taken at the seed's declared default.

## What was observed

Running the `voice.self_echo` seed at its own declared default — `output.duration_ms`
8 000, `echo.candidate_count` 7, coupling −12 dB, empty room — the near-end gate opens on
the echo canceller's own residual after a few seconds of continuous speech, and Jarvis
cuts himself off. Every test in this repository until now ran at about 1.2 s, which is
why nobody had seen it.

| Profile | Echo model | 1 000 ms | 3 000 ms | 8 000 ms |
|---|---|---|---|---|
| `audio` | exact copy, no delay (as shipped before this Slice) | 0 confirmed, passed | 0 confirmed, passed | **1 confirmed, FAILED**, cut off at 3 400 ms |
| `audio` | delay only, or drift only, or noise only | — | — | **1 confirmed, FAILED**, cut off at 3 200–3 500 ms |
| `audio` | delay **and** drift **and** noise (as shipped now) | 0, passed | 0, passed | 0, passed, full 8 000 ms — 5/5 repeats |
| `hardware:auto` (double: room noise floor, one block of delay, drift, noise) | — | 0 | 0 | 0 **usually**, 1 **intermittently** |
| `hardware:guided`, silent phase (same double, 8 000 ms, 3 candidates) | — | — | **1 in about half of runs** (10 in 20 replays) |

The learned near-end coupling reaches about −49 dB in every failing case, against an
initial clamp of −15 dB that `NearEndDetector` holds for its first `warmup_frames` (300
frames = 3 s of far-end audio). Every observed cut-off is at 3.2–3.5 s, i.e. immediately
after that clamp lifts.

## The mechanism, as far as a double can show it

`NearEndDetector.update` (`jarvis/audio/duplex.py`) calls a frame "near" when it exceeds
both the learned noise floor and `ref_env + coupling_db` by its margins. `coupling_db` is
learned from frames judged NOT near, and it ratchets toward whatever the residual actually
is. The better the canceller does, the lower the learned coupling goes, and therefore the
smaller the residual needs to be to count as a voice. `warmup_coupling_db` (−15 dB) holds
that off for the first three seconds and then releases it.

So: a canceller that cancels very well teaches the detector to expect almost nothing, and
after three seconds any excursion above that expectation reads as a person. With a
delay-free, exactly-scaled echo the canceller cancels essentially perfectly, the learned
coupling collapses to −49 dB, and the run trips reliably. With a realistic echo it cancels
less well, the learned coupling stays higher, and the margin survives — on the `audio`
profile, 5/5 at 8 000 ms.

## What is settled and what is not

**Settled: the deterministic failure was a defect of the DIAGNOSTIC, not of Jarvis.** The
`audio` profile injected a delay-free, exactly-scaled, noiseless copy of what was played.
No room does that, and giving an adaptive canceller one drives it into a state no room can
produce. Fixed in this Slice (`jarvis.testlab.audio.chain.room_response`,
`ECHO_DELAY_BLOCKS`, and the same model in the hardware double's `FakeRoom`).

**The rate is higher than first recorded, and the first figure was an artefact of the
measurement.** "About 1 run in 4" was measured while `require_silent_phase` still aborted
the run whenever the silent phase both suspected a near-end and confirmed a barge-in —
which is every run where the gate opened on the echo. Those runs were counted as refusals
rather than as findings. With that branch removed (Slice 09 rework 3, item S2), the silent
phase reports `barge_in.false_confirmed_count` and the blocking assertion decides: **10 of
20 replays at the declared default**. The defect did not get worse; it became visible.

**Not settled: whether a real room at −12 dB coupling trips it too.** The hardware double
still produces an occasional confirmation at 8 000 ms with a more realistic room, and a
double cannot tell us whether that is its remaining artefact or the product's real
behaviour. A real room sits somewhere between "perfect copy" and any model we invent, and
only the workstation can say where.

## What a fix would have to look at, IF hardware confirms it

Nothing here should change until hardware confirms it, and this task must not touch the
voice runtime in any case. For whoever picks it up:

- `NearEndDetector.coupling_db` has no floor other than −60 dB. A canceller that performs
  unusually well teaches it an expectation that leaves no headroom for its own variance.
  A floor relative to the canceller's measured residual variance, rather than to its mean,
  would be the obvious place to look.
- `warmup_frames` (300) ends the protection at exactly 3 s, which is where every failure
  observed here lands. Whether the clamp should decay rather than lift is a design
  question, not an implementation one.
- `floor_margin_db` (12) and `echo_margin_db` (10) are the two margins involved.

## How to reproduce

```powershell
# the `audio` profile, no device, no human, no provider: about 3 s per duration
.venv/Scripts/python -m pytest -q -p no:cacheprovider -s tests/integration/test_testlab_audio_runners.py -k defaults
# the hardware profiles over the double, at the seeds' declared defaults
.venv/Scripts/python -m pytest -q -p no:cacheprovider -s tests/integration/test_testlab_hardware_runners.py -k defaults
```

The decisive run is HV-TL-HW-01 at `output.duration_ms = 8000` on the real workstation.
Since Slice 12 the two manifests it needs are PUBLISHED, so it can also be run straight
from the CLI:

```powershell
$env:JARVIS_TESTLAB_HARDWARE = "1"; $env:JARVIS_TESTLAB_GUIDED = "1"
.venv/Scripts/python -m jarvis.testlab run voice.barge_in_response --profile hardware:guided --guided
```

The operator pages are
`tasks/jarvis-category2-test-lab/operator-runbook.md` (short form, what to write down)
and `slices/09-hardware-guided/operator-script.md` (the acoustics in detail). If
`barge_in.false_confirmed_count` is 1 or more there, with a real room and a real speaker,
this stops being an open question and becomes the defect `voice.self_echo` was written to
find.
