# HV-TL-HW-01 — operator script

> Part of [`../../operator-runbook.md`](../../operator-runbook.md), which covers all three
> Human checks. This page is the detailed one for the acoustic check; the runbook has the
> short form, the CLI route and what to write down.

**What this proves:** that Jarvis, speaking out loud through this laptop's own speaker
and hearing itself through this laptop's own microphone, does not mistake its own voice
for yours — and that it still hears you when you really do cut in. No automated test can
make the second claim: it needs a person in the room.

**How long:** about five minutes, of which you spend maybe ninety seconds actually doing
something. **What you need:** the room reasonably quiet, normal speakers (not headphones
— the point is that the microphone hears the speaker), and nothing else using the
microphone.

> **If a run ends with no result, do not debug it — jump to
> [If it stops without a result](#if-it-stops-without-a-result) and do what the table
> says.** About one session in ten simply measures nothing, and the only correct response
> is to run it again. That is expected, not a fault of yours and not a fault of Jarvis.

---

## Before you start

1. **Stop the live Jarvis Voice**, or make sure it is not in a conversation. The run
   refuses to start if the contention detector sees a voice heartbeat, so the worst case
   is a skip with a clear message, not a stolen microphone. Checking first saves you the
   round trip.

   To confirm it really stopped, look at the same file the detector reads — `runtime/.voice_heartbeat`,
   a single number rewritten every second while Voice runs. If it is more than five
   seconds old (or absent), Voice is not running:

   ```powershell
   # seconds since the last heartbeat; over 5 means Voice is gone. "no heartbeat file" is also fine.
   if (Test-Path runtime/.voice_heartbeat) {
     [math]::Round(([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000) - [double](Get-Content runtime/.voice_heartbeat), 1)
   } else { "no heartbeat file" }
   ```

   Also check `runtime/.voice_state`: `idle`, or an old file, is what you want. A recent
   `speaking` or `listening` means a conversation is still open and the run will refuse.
2. Open a terminal in `C:\Projects\jarvis\jarvis`.
3. Set the two switches. They are separate on purpose: the first says "you may open my
   devices", the second says "I am sitting here".

```powershell
$env:JARVIS_TESTLAB_HARDWARE = "1"
$env:JARVIS_TESTLAB_GUIDED = "1"
```

4. Run it, and leave the terminal visible:

```powershell
.venv/Scripts/python -m pytest -q -s -p no:cacheprovider tests/integration/test_testlab_hardware_devices.py
```

**Where the prompts appear, and what you press.** The run itself has no screen: it
publishes each step and waits. What shows it to you is a *presenter*. This test has a
little one built in — it prints the step in **this terminal** and waits for **Enter** —
and `-s` in the command above is what lets it print and read your keystroke; without it
pytest swallows both and every step will time out.

Since Slice 10 there are two other presenters for exactly the same prompts, and either is
a valid way to do this check: the CLI (`python -m jarvis.testlab run voice.barge_in_response
--profile hardware:guided --guided`, with a real countdown), and the Control Center LAB
panel. The runbook lists both.

Nothing else is required of you — no id to type, no file to touch.

### If it stops without a result

**Read the code it printed and act on this table** — you should not have to read the rest
of this page to know what just happened:

| What it printed | What it means | What to do |
|---|---|---|
| `testlab_hardware_run_failed` … *answered none of the N provider onsets* | Nothing was measured. Not your fault and not a Jarvis defect. Happens about one session in ten. | **Run it again.** Nothing else. |
| `testlab_guided_claim_unmeasured` | Your voice was not picked up. | Run it again, louder and squarely at the microphone. |
| `testlab_guided_step_not_followed` | A voice was measured in the room while you were asked to be silent. | Find somewhere quieter, then run it again. |
| the run says **`failed`** with `barge_in.false_confirmed_count` ≥ 1 | Jarvis interrupted himself on his own echo. **This is a RESULT, not a broken test.** | Do not retry to make it go away. Report it — see "What a result you should report looks like". |

---

## What you will be asked to do

Four steps. Each one prints what to do, how long you have, and waits for **Enter**.

| # | Prompt | What you actually do | Why |
|---|---|---|---|
| 1 | *(automatic)* `hardware:auto` runs first | Nothing. Stay quiet for a few seconds while a short tone plays. | The no-human baseline: Jarvis's own sound in this room, and nothing confirmed as a barge-in. |
| 2 | **REMAIN_SILENT** | Press Enter, then **say nothing at all** until Jarvis stops talking. Do not move the laptop. | Every barge-in confirmed in this window is a FALSE one. The run also measures the room's own level first: if it is already as loud as a voice, it says so instead of pretending. |
| 3 | **INTERRUPT** | Press Enter. Jarvis starts talking again — **cut it off out loud**, at a normal voice, with the phrase shown (by default *"jarvis arrete toi"*). Saying it once is enough; you do not have to keep talking. | The only claim a machine cannot make: a real voice DOES get through the echo gate. |
| 4 | **ACKNOWLEDGE** | Press Enter if the session sounded right: Jarvis spoke twice, it did not stammer or cut itself off, and it stopped when you spoke over it. | The one judgement no metric makes. |

Each step shows how long you have. That deadline is **derived from the diagnostic's
`output.duration_ms`** — it is that, plus thirty seconds. The two manifests this check uses
are now PUBLISHED (`voice.self_echo` v3 for the `hardware:auto` half, `voice.barge_in_response`
v1 for the guided half) and default to 8 seconds of speech, so you are asked to hold still
for well under a minute. If somebody
raises that parameter, this script gets proportionally more tedious; it is not a bug, but
it is worth knowing before you agree to run it.

You may **refuse** any step (Ctrl-C at a prompt, or let it time out). That is a legitimate
answer: the run ends `inconclusive`, never "failed". Nothing you do can make this report
a defect in Jarvis that is not there.

---

## What a good result looks like

The test passes, and the printed run log shows four things:

- `devices: input=... output=...` — it opened what you expected, and it says whether
  that came from the diagnostic, from your Control Center settings, or from the system
  default;
- `audio chain: aec_engaged=True` — the real echo canceller was in the chain. If it says
  `False`, the measurement is still honest but it is **not** a measurement of the
  canceller, and the reason is printed beside it;
- `silent phase: ... confirmed=0` — Jarvis did not interrupt itself. This is the negative
  claim;
- `interrupt phase: ... signals=['near_end'] confirmed=1` — your voice was heard and the
  barge-in was confirmed. This is the positive claim.

And the assertions:

| Metric | Expected |
|---|---|
| `barge_in.false_confirmed_count` | `0` — Jarvis never cut itself off on its own echo |
| `barge_in.true_confirmed_count` | `≥ 1` — your voice did get through |
| `guided.prompt_count` | `3` |
| `guided.late_prompt_count` | `0` (a late answer is recorded, not fatal, except on the interrupt step) |

## What a result you should report looks like

Any of these is worth writing down rather than re-running:

- **`barge_in.false_confirmed_count` is 1 or more, and the run reads `failed`.** Jarvis
  interrupted itself on its own voice in this room. **This is the defect the whole
  diagnostic exists to find, and a `failed` run here is a RESULT, not a broken test.**
  Note the speaker volume, because it matters, and read
  `Issues/self-barge-in-after-seconds-of-speech.md` — this is precisely the open question
  your session settles. The transcript says which it was: `room_before_dbfs` and
  `room_after_dbfs` near -65 dBFS with `certain: false` mean the room was quiet and the
  confirmation was Jarvis's own echo; a loud figure there means something in the room
  triggered it and the run will have said so instead.
- **`barge_in.true_confirmed_count` is 0 although you spoke**, or the run ends
  `inconclusive` with `testlab_guided_claim_unmeasured`. The echo gate did not open for a
  real person. That is the opposite defect, and it is the one the `audio` and
  `hardware:auto` profiles cannot see at all. The run says "could not measure" rather than
  passing quietly, which is the point: try once more, a little louder and squarely at the
  microphone, and if it still does not open, that is the finding.
- **The run ends `inconclusive` with `testlab_guided_step_not_followed`.** A voice was
  *measured* in the room — with nothing playing, so it cannot have been Jarvis — while you
  were asked to be silent. A neighbour, a fan that started, a chair. Try again somewhere
  quieter; the printed dBFS figure is the number to report if it persists. Note this is
  NOT the echo case above: an echo-triggered confirmation is reported as a finding, never
  as this.
- **The run ends `inconclusive` with `testlab_guided_claim_unmeasured` or
  `testlab_hardware_run_failed`.** The run could not measure the thing it came for —
  usually because your voice was not picked up, occasionally because the stack answered
  none of the stimuli. Honest, and cheap: run it again. About one attempt in ten ends this
  way at the default, and a retry is the right response.
- **The run ends `inconclusive` with a `testlab_device_*` code.** Something about the
  devices: the message names which end and why. Not a Jarvis defect.

## After

Unset the switches so nothing opens your microphone by accident later:

```powershell
Remove-Item Env:JARVIS_TESTLAB_HARDWARE, Env:JARVIS_TESTLAB_GUIDED
```

The run leaves its evidence in the test's temporary store: `hardware_profile.json` (what
was exercised, on which device), `guided_prompts.json` (every prompt, when it was shown,
when you answered, and what the microphone heard while it was open) and `trace.jsonl`.
Nothing is recorded permanently, no audio clip is kept unless it was explicitly asked
for, and no device name leaves the machine.

## Note for whoever reads the result

This check is the FIRST time this code has opened a real microphone or spoken to a human.
Everything it exercises has been run end to end against a `sounddevice` double with a
simulated room, so what is being validated here is the part a double cannot stand in for:
the acoustics of this workstation, and the usability of the prompts. If a prompt was
confusing, that is a finding too — Slices 10 and 11 build the CLI and the UI that will
present these same steps, and this is the moment to say the wording is wrong.
