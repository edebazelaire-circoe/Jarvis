# Operator runbook — the three Human validation checks

Three things no automated test in this repository has ever done, deliberately: open the
real microphone and speaker, prompt a person, and let a human judge whether the evidence
is actually useful. Everything else about the Category 2 Test Lab has been machine-tested
against doubles. These three checks are the gate.

They are independent. Run them in any order, on any day. **HV-TL-E2E-01 is the cheapest
and safest** (no device, no provider, nobody prompted) and it is the one that tells you
whether the Test Lab is worth having, so if you only do one, do that.

| Check | What only a human can settle | Devices? | Money? | Roughly |
|---|---|---|---|---|
| [HV-TL-E2E-01](#hv-tl-e2e-01--from-a-real-incident-to-an-answer) | Is the evidence loop actually usable end to end? | no | no | 15 min |
| [HV-TL-UI-01](#hv-tl-ui-01--the-control-center-panel) | Can somebody do the job without the CLI or a log? | no | no | 15 min |
| [HV-TL-HW-01](#hv-tl-hw-01--the-guided-acoustic-check) | Does Jarvis cut himself off in THIS room, and does he hear you? | **yes** | no | 5 min |

Common rules, for all three:

- **Stop the live Jarvis Voice first**, or at least make sure it is not in a conversation.
  Only HV-TL-HW-01 strictly needs this (the contention detector refuses otherwise), but a
  quiet machine makes every reading easier to trust.
- **Unset the switches afterwards.** Each section says which.
- **An honest refusal is a result, not a failure.** `inconclusive` means "could not
  measure", and the failure detail says what was missing. It is never a Jarvis defect.
- **Write down what you saw in `tasks/jarvis-category2-test-lab/LOG.md`**, with the run
  ids and bundle ids. Those ids are how anybody re-reads the evidence later.

```powershell
# every command below assumes this, and nothing else
cd C:\Projects\jarvis\jarvis
```

---

## HV-TL-E2E-01 — from a real incident to an answer

> Capture one real voice session, create and inspect its `DiagnosticBundle`, run a
> targeted diagnostic, and review the resulting comparison and evidence. Expected: the
> workflow is reproducible end to end and needs no LLM inside the Test Lab and no
> permanent setting change.

**What to set:** nothing. The default authority is exactly the `virtual` profile: no
device, no provider, no human, no money. Do **not** set any `JARVIS_TESTLAB_*` switch for
this check — if a command here needs one, that is a finding.

**Before you start:** have a real conversation with Jarvis, or make sure there has been
one recently, so `runtime/trace.jsonl` has something in it. One where something felt
wrong is ideal; an ordinary one is fine.

**How long:** about fifteen minutes, most of it reading.

### The steps

```powershell
# 1. WHAT CAN BE MEASURED. Five diagnostics; note which profiles each one offers.
.venv/Scripts/python -m jarvis.testlab list

# 2. NORMALIZE THE REAL SESSION. Bounded read of the live journal; writes nothing to it.
#    Use --session-id for one voice session, or --conversation-id for a whole conversation.
.venv/Scripts/python -m jarvis.testlab capture --conversation-id <conversation id>

# 3. READ WHAT IT NOTICED. This is what chooses the diagnostic in step 4.
.venv/Scripts/python -m jarvis.testlab bundles --id <tlb-...>

# 4. REPRODUCE. Pick the diagnostic whose subject matches a finding (see the table below).
.venv/Scripts/python -m jarvis.testlab run voice.self_echo --profile virtual

# 5. THE RUN'S OWN EVIDENCE, in the same document shape as step 2's.
.venv/Scripts/python -m jarvis.testlab capture --run <tlr-...>

# 6. CHANGE ONE THING and run it again.
.venv/Scripts/python -m jarvis.testlab run voice.self_echo --profile virtual -p output.duration_ms=4000

# 7. PUT THE TWO SIDE BY SIDE.
.venv/Scripts/python -m jarvis.testlab compare <first tlr-...> <second tlr-...>
```

**If you do not know the conversation id**, `capture --start` / `--end` takes a time
window instead:

```powershell
.venv/Scripts/python -m jarvis.testlab capture --start 2026-09-19T09:00:00Z --end 2026-09-19T10:00:00Z
```

**Which finding points at which diagnostic:**

| Finding in the bundle | Run this |
|---|---|
| `voice.self_barge_in` | `voice.self_echo` |
| `speech.delivered_after_supersession` | `speech.stale_supersession` |
| `speech.duplicate_payload`, `speech.missing_delivery_outcome` | `speech.payload_integrity` |
| `latency.above_threshold` | `voice.queue_latency` |
| `events.reconstruction_anomaly` | none of them — that is a Conversation Events defect, not a voice one |

### When the live database is still schema v1

**This is the normal case today, and it is not an error.** Core's state database
(`data/state/jarvis.sqlite3`) only grows a `conversation_events` table when the live Jarvis
is restarted on a build with state schema v2. Until then, step 2 reports:

```text
source conversation_events: unavailable (conversation_events_table_absent)
```

The bundle is then **journal-only**: turns, speech, playback, barge-in, latency and
anomalies all still come from `runtime/trace.jsonl`, which is where the voice evidence
lives anyway. Conversation Events would add the durable turn records and the join ids, not
the voice measurements.

**What to run in that case:** exactly the commands above — `capture` already reports the
source as `unavailable` instead of failing. If you would rather not have the Test Lab open
the database at all:

```powershell
.venv/Scripts/python -m jarvis.testlab capture --conversation-id <id> --no-events
```

That reads the journal alone and records `not_requested` instead of `unavailable`. Either
is a valid HV-TL-E2E-01 run. **To make the events half real**, restart the live Jarvis on
current `main` once (the migration runs at startup) and re-run step 2; the coverage line
should then read `available` or `empty`.

### What a good result looks like

- step 2 prints a `tlb-...` id, `stored`, one line per source with its status, and a
  finding count. **A bundle with zero findings is a good result** — it means the
  normalizer found nothing wrong in that session, not that it failed;
- step 3 shows the same document without re-reading the journal;
- step 4 ends with a verdict (`passed`, `failed` or `inconclusive`) and a metric table
  where every number has a unit;
- step 5 prints `run <tlr-...> now references <tlb-...>`;
- step 7 prints one row per metric with the direction of the change, and lists
  `output.duration_ms` as an input **difference** — not as a reason the two runs cannot
  be compared;
- nothing anywhere asked you for a key, a device or a confirmation;
- `git status` is clean and your Control Center settings file is byte-identical.

### What to write down

- the bundle id from step 2, its source statuses and its findings;
- the two run ids and their verdicts;
- **the honest answer to: could somebody else have done this from the documentation
  alone?** If a step needed you to know something that is not written down, that is the
  finding, and it matters more than any number here.

### What NOT to re-run

- **Do not re-run step 2 hoping for a different bundle.** A bundle id is derived from its
  content: the same session gives the same id and `stored: duplicate`. That is correct.
- **Do not re-run a `failed` step 4** to make it pass. A failed diagnostic run is a
  measurement. Capture the run id and move on.
- **Do not run anything on `live` or `hardware:*` for this check.** They are a different
  check, they cost money or take the microphone, and they add nothing to this one.

### Afterwards

The runs, bundles and sweeps live under `runtime/testlab/`. They are gitignored and
retention is disabled by default, so nothing is deleted behind you. To see what retention
*would* delete:

```powershell
.venv/Scripts/python -m jarvis.testlab retention
```

---

## HV-TL-UI-01 — the Control Center panel

> Use the Control Center to choose one diagnostic, inspect the resources it needs, run
> it, inspect metrics and artifacts, and compare two runs. Expected: a human can complete
> the workflow without reading logs or using the CLI.

**What to set:** nothing, and that is part of what is being checked — with no switch set
the panel must show `virtual` as runnable and the other profiles as refused, **with the
reason**.

**What to run:** start the Control Center the way you normally do, open it in the browser,
and click the **LAB** tool in the dock.

**How long:** about fifteen minutes.

### The steps, and what to look at

1. **Préparer.** Pick a diagnostic. Before you can start anything, the panel must already
   show, for each profile: what it requires, what it costs, and whether it can run here.
   Read those without touching anything — then check one against
   `.venv/Scripts/python -m jarvis.testlab describe <id>` **once, at the end**, not while
   you work. The point of this check is that the screen is enough.
2. **Run** `voice.self_echo` on `virtual`. Watch the follow-along area: it must tell you
   the run is going, and it must not disappear when the list re-renders.
3. **Résultats.** Read the verdict, then the assertions (each with its threshold AND the
   measured value beside it), then the metrics with their units, then the artifacts as
   links. Open `trace.jsonl`.
4. **Run it again** with one parameter changed, then use **Comparer** on the two runs.
5. **Try to run something you are not allowed to** — pick `hardware:guided`. The panel
   must refuse it *before* the button, and say which capability is missing.

### What a good result looks like

- you never opened a terminal, a log file or the browser console;
- every refusal named its cause in a sentence you understood;
- a "could not measure" outcome, if you got one, read as *could not measure* and not as a
  failure;
- the device-contention line told you whether the microphone was free, and warned rather
  than blocked;
- nothing on the screen was a number without a unit or a verdict without a reason.

### What to write down

- the two run ids and what the comparison said;
- **every place where you had to guess.** Wording, ordering, a missing unit, a refusal
  you could not act on. This is the only check that can produce that finding, and the
  panel derives nothing on its own — so a wrong word on screen is a wrong word in the
  document behind it, and both get fixed.

### What NOT to re-run

- **Do not use the CLI to work around a confusing screen.** If you needed the CLI, the
  check has already told you something; write that down instead.
- **Do not start a sweep or a bundle capture from the panel** — it deliberately does not
  offer them (no API for the first, and the second belongs to HV-TL-E2E-01). Their absence
  is expected, not a finding.
- **Do not set `JARVIS_TESTLAB_HARDWARE` or `JARVIS_TESTLAB_LIVE` to "see what happens".**
  That turns this check into one of the other two, with real consequences.

---

## HV-TL-HW-01 — the guided acoustic check

> Run one `hardware:guided` scenario with normal speakers and microphone, following the
> silence / speak / interrupt cues. Expected: each step is clearly guided, the timestamps
> and actions are captured, the run completes with no resource left behind, and the
> metrics mean something.

**The full script is
[`slices/09-hardware-guided/operator-script.md`](slices/09-hardware-guided/operator-script.md)**
— it has the acoustics, the refusal table and the "what to report" list, and it is the
page to have open while you do this. What follows is the short form plus what changed
since it was written.

**What to set:**

```powershell
$env:JARVIS_TESTLAB_HARDWARE = "1"   # you may open my devices
$env:JARVIS_TESTLAB_GUIDED   = "1"   # I am sitting here
```

**What to run.** Two routes, both valid. The CLI is the one to prefer now that the
diagnostics are published:

```powershell
# the negative claim alone, no human needed: Jarvis must not cut himself off
.venv/Scripts/python -m jarvis.testlab run voice.self_echo --profile hardware:auto

# the guided pair: the same negative claim AND the positive one only you can make
.venv/Scripts/python -m jarvis.testlab run voice.barge_in_response --profile hardware:guided --guided
```

The pytest route in the operator script still works and prints more:

```powershell
.venv/Scripts/python -m pytest -q -s -p no:cacheprovider tests/integration/test_testlab_hardware_devices.py
```

**How long:** about five minutes, of which roughly ninety seconds is you doing something.

**What you are asked to do:** stay completely silent while Jarvis talks, then interrupt
him out loud, then say whether the session sounded right. Each prompt shows its own
countdown; `--guided` refuses to start if this is not a real terminal, because a presenter
that answers for you would be worse than no presenter.

### What a good result looks like

`barge_in.false_confirmed_count` is `0` (he did not cut himself off) **and**
`barge_in.true_confirmed_count` is `1` or more (he heard you). The operator script's
"What a good result looks like" has the full table.

### What to write down

- both counts, and the speaker volume you used;
- **if `barge_in.false_confirmed_count` is 1 or more: that is THE result of this whole
  task.** It settles the open question in
  [`Issues/self-barge-in-after-seconds-of-speech.md`](Issues/self-barge-in-after-seconds-of-speech.md):
  a double cannot tell whether Jarvis really does cut himself off after a few seconds of
  continuous speech in a real room, and your session can. Record the run id,
  `room_before_dbfs`, `room_after_dbfs` and `certain` from the transcript, and do **not**
  retry it away;
- whether any prompt was confusing. The wording is a deliverable too.

### What NOT to re-run

- **Do not re-run a `failed` run with `barge_in.false_confirmed_count >= 1`.** That is the
  defect the diagnostic was written to find. Retrying until it passes destroys the only
  evidence anybody has.
- **Do not re-run more than twice** after an honest `inconclusive`. About one session in
  ten measures nothing (`testlab_hardware_run_failed`, *answered none of the N provider
  onsets*); a third identical refusal is itself worth reporting.
- **Do not raise `output.duration_ms` to "get a better reading".** The declared default is
  what the Issue's measurements are about; a different duration answers a different
  question.
- **Do not use headphones.** The whole point is that the microphone hears the speaker.

### Afterwards

```powershell
Remove-Item Env:JARVIS_TESTLAB_HARDWARE, Env:JARVIS_TESTLAB_GUIDED
```

The run leaves `hardware_profile.json`, `guided_prompts.json` and `trace.jsonl` in its
store. No audio clip is kept unless `JARVIS_TESTLAB_AUDIO_ARTIFACTS=1` was set, and no
device name leaves the machine.

---

## If something goes wrong in any of the three

| What you see | What it means | What to do |
|---|---|---|
| `testlab_supervisor_work_root_busy` | Another process (the Control Center, or a CLI run) owns `runtime/testlab/work`. | Close the other one, or use a read command — `list`, `runs`, `show`, `bundles`, `compare` and `retention` never take the work root. |
| `device_contention` | The live Jarvis Voice is using the microphone. | Stop Voice and check `runtime/.voice_heartbeat` is stale, then retry. Never bypass this. |
| `human_presence_missing` | `JARVIS_TESTLAB_GUIDED` is not set in THIS process. | Set it in the same terminal you run from. |
| `live_opt_in_missing` | A `live` profile with no `JARVIS_TESTLAB_LIVE=1`. | Only set it if you mean to spend money, and set a budget with `JARVIS_TESTLAB_MAX_COST_USD`. |
| a bare traceback | The Test Lab broke, which is a defect of the Test Lab. | Report it with the command line; exit code 7 and a `testlab_cli_failed` message is the intended shape. |
