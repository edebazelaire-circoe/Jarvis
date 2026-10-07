# Solo Owner + Core work state — workstation acceptance (Task 14)

**Status: PENDING USER.** Everything in this document needs the owner's own
voice, the real microphone and speakers, real background conversation and the
real provider. No agent can run it and no result may be invented. What *was*
automated (unit/integration suite, synthetic benchmark, defaults decision) is in
[`docs/fixes/solo-owner-duplex/final-implementation-report.md`](fixes/solo-owner-duplex/final-implementation-report.md).

Everything below is runnable as written. Fill the tables as you go; keep the
filled copy outside Git if it names people, and publish only scalars
(`docs/results/speaker-benchmark/` holds scores and timings, never audio).

Section 12 is separate: the configurable wake word (openWakeWord) checks
`HV-WAKEWORD-UI-01` and `HV-WAKEWORD-MIC-01`, all **À FAIRE**.

Related: [`docs/OPERATIONS.md`](OPERATIONS.md) (settings, trace, Control Center),
[`docs/SPEAKER_BENCHMARK.md`](SPEAKER_BENCHMARK.md) (benchmark and how to read
it), [`docs/ACCEPTANCE_STATUS.md`](ACCEPTANCE_STATUS.md) (the older
`continuous_brain` workstation checklist — run it too, it is not replaced).

---

## 0. Record the setup first

A Solo Owner result without its hardware is not a result: echo, distance and
the microphone's own noise floor decide most of it.

| Item | Value |
| --- | --- |
| Date, operator | |
| OS build (`winver`), CPU, RAM | |
| Python (`.\.venv\Scripts\python.exe -V`), `pip list` for `sounddevice`, `livekit`, `numpy`, `sherpa-onnx` | |
| Input device name + sample rate (Control Center → Config) | |
| Output device: laptop speakers / headset model | |
| Voice stack + model (`voice.stack` in the trace: `arch`, `turn_mode`, `stack`) | |
| Echo cancellation state (Control Center → Mode vocal → **Annulation d'écho**) | |
| Verifier engine + model SHA-256 (Control Center → **Vérificateur de locuteur**) | |
| Owner profile: `profile_id`, `enrollment_ms`, `consistency`, `created_at` | |
| Settings snapshot: `conversation_mode`, `speaker_verification`, `owner_threshold`, `owner_evidence_ms`, `owner_short_evidence_ms`, `owner_short_margin`, `owner_buffer_ms` | |

```powershell
.\.venv\Scripts\python.exe -m jarvis health
.\.venv\Scripts\python.exe -m jarvis owner-voice show          # exit 0 = profile ready
Invoke-RestMethod http://127.0.0.1:17654/api/settings | ConvertTo-Json -Depth 6 > setup-settings.json
```

## 1. Prerequisites (once)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[speaker]"
.\.venv\Scripts\python.exe -m jarvis owner-voice download-model      # ~28 MB, SHA-256 checked
# Stop Voice first: the microphone must be free.
.\.venv\Scripts\python.exe -m jarvis owner-voice enroll --mic --seconds 30
.\.venv\Scripts\python.exe -m jarvis owner-voice show
```

Enroll in the usual position, with the microphone Voice uses, in a quiet room.
`consistency` below 0.8 means several voices or too much noise: enroll again
(`--replace`). Keep the reported `profile_id` in the table above.

## 2. Shadow measurement before enforcement

Set `conversation_mode = open_room` and `speaker_verification = shadow`
(Control Center → **Mode vocal** → *Qui peut parler à JARVIS*), restart Voice in
`continuous_brain`, then work normally for at least one long session with
colleagues around.

Read the result without opening the raw trace:

```powershell
.\.venv\Scripts\python.exe scripts\summarize_voice_trace.py runtime\trace.jsonl
.\.venv\Scripts\python.exe scripts\summarize_voice_trace.py runtime\trace.jsonl --json --since 2026-09-12 > shadow.json
```

| Check | Pass |
| --- | --- |
| `voice.owner.engine` present at the first wake (engine, model, threshold, window) | yes |
| `Propriétaire confirmé` count > 0 and `confirmation (ms)` P50 ≈ 1600 ms | yes |
| Your own utterances: `voice.owner.confirmed` with `owner_score` P50 clearly above the threshold (≥ +0.1) | yes |
| Colleagues: `voice.owner.rejected` with `reason = non_owner`; **no** `confirmed` on their turns | yes |
| `voice.owner.overrun` absent (the verifier thread kept up) and worker `dropped_ms` = 0 in the Control Center | yes |
| `voice.owner.unavailable` absent | yes |

If the owner's scores sit close to the threshold, do not enforce yet: re-enroll
or run the benchmark of §5 first and pick a threshold from it.

## 3. The ten scenarios (docs/04)

Switch to `conversation_mode = solo_owner` (verification follows: `enforce`) and
restart Voice. Keep the Control Center open (**TRC** panel) and a terminal on
`scripts\summarize_voice_trace.py`. For each scenario, note what you heard and
what the trace says. A scenario fails if either disagrees with the expectation.

| # | Scenario | Do this | Expected — heard | Expected — trace |
| --- | --- | --- | --- | --- |
| 1 | Quiet owner, JARVIS silent | Wake, say a normal sentence | Answer starts ≈ 1.6–2 s after you started | `voice.owner.candidate` → `confirmed` (`confirm_ms` ≈ 1600), `voice.owner.replay` once, `voice.transcript`, brain turn |
| 2 | Owner interrupts JARVIS | Ask for a long answer, speak over it | JARVIS stops ≈ 1.7–2 s after you start; your sentence is answered whole | `voice.barge_in.owner_confirmed` (`onset_to_stop_ms`, `stop_latency_ms`), `voice.owner.replay` with `clamped_ms = 0`, then `voice.barge_in.provider_advisory` `relation = after_owner_stop` |
| 3 | One colleague talks continuously while JARVIS speaks | Have someone talk for 30 s during an answer | JARVIS never ducks, never stops, never answers them | `voice.barge_in_pending` / `rejected` with `authority = owner`, `voice.input.non_owner_dropped` (`source = capture`, `reason = non_owner`), no `owner_confirmed` |
| 4 | Several colleagues converse while JARVIS speaks | Two people, 1 min | Same as 3 | Same as 3; no `voice.transcript` for their words |
| 5 | Owner starts during a colleague's sentence | Speak over a colleague | JARVIS answers you within ≈ 2 s | `owner_confirmed` with `after_non_owner = true`; `voice.owner.replay` `replay_from_ms` ≥ the colleague's start + ≈ 1 s (bounded leak, ≤ ≈ 1.2 s) |
| 6 | Owner + colleague overlap 1–3 s | Speak at the same time for 1, 2, 3 s | You are recognized; his words may ride your turn, never form one | `owner_confirmed`; at most one turn submitted |
| 7 | Keyboard, mouse, desk impacts | Type hard for 30 s, both while JARVIS speaks and while silent | Nothing happens | No `voice.owner.candidate`, no `non_owner_dropped` |
| 8 | JARVIS-only loudspeaker echo, several volumes | Let JARVIS speak alone at 30 %, 60 %, 100 % | He never cuts himself, never answers himself | No `owner_confirmed`, no `voice.transcript` of his own words, `voice.barge_in` absent |
| 9 | Headset path | Repeat 1, 2, 3 with the headset | Same behaviour, usually faster | Same events; compare `confirm_ms` P50 with §3 line 1 |
| 10 | Laptop speakers at 0.5 m, 1 m, 2 m | Repeat 1 and 2 at each distance | Recognition still works at your usual distance | `owner_score` P50 per distance; note where it falls below threshold + 0.05 |

Short replies (Task 07) — worth a line of their own:

| Say | Expected |
| --- | --- |
| « oui, vas-y » while JARVIS is silent | accepted ≈ 0.6–0.8 s after you stop; trace `voice.owner.confirmed` with `verdict = candidate_end` |
| « stop » while JARVIS speaks | he stops; same event, plus `voice.barge_in.owner_confirmed` |
| a lone « oui » (< 600 ms) | dropped, `voice.input.non_owner_dropped` `reason = insufficient_audio` — expected, not a bug |
| a colleague's short « non » | dropped, `reason = short_not_owner` |

Degraded states (must be explicit, never silent):

| Force this | Expected |
| --- | --- |
| Remove the owner profile (`owner-voice delete`), wake | refusal `solo_owner_unavailable`, alert on screen, red banner in the Control Center, **no** open-room fallback |
| `voice_arch = legacy` with `solo_owner` | refusal `solo_owner_requires_continuous_brain` at Voice start |
| Uninstall LiveKit (or set echo cancellation off) | Control Center shows `dégradée / aec_not_installed` (or `aec_disabled`); you must speak louder to be heard over JARVIS |
| Kill the verifier mid-session (rename the model file, wake again) | input closes, session returns to background with the French explanation, next wake retries |

Control Center checklist (task 08), settings window → **Mode vocal** → *Qui peut
parler à JARVIS*:

| Moment | Expected on screen |
| --- | --- |
| Before enrollment | red « refusé · Solo Owner configuré mais NON appliqué » with the exact command to run |
| After enrollment, Voice running | green « prêt · Solo Owner appliqué », *Constaté par Voice (activation, …)* |
| Profile block | `profile_id`, `created_at`, enrolled duration, consistency — and **no** voiceprint anywhere in `GET /api/settings` (check in DevTools) |
| Open room + shadow | grey « prêt · Salle ouverte, vérification en ombre »; *Fil de vérification (Voice)* `ready`, `dropped_ms` 0 after a long session |
| After changing a tuning field | « Redémarrez Voice pour appliquer »; after the restart, *Valeurs effectives* shows the new value with origin « réglage » |
| **Annulation d'écho** | `active · Constaté par Voice`; uninstall LiveKit → `dégradée · aec_not_installed` |
| Verifier killed mid-session | red banner, `status_source: voice`, phase `session` |
| Voice stopped | the screen falls back to the settings probe (`D'après la sonde des réglages`) |

## 4. Numbers to keep

After the scenarios, one command produces the acceptance numbers:

```powershell
.\.venv\Scripts\python.exe scripts\summarize_voice_trace.py runtime\trace.jsonl --json > acceptance-trace.json
```

| Measure | Where | Target |
| --- | --- | --- |
| Owner confirmation P50 / P95 | `owner.confirm_ms` | P50 ≤ 2000 ms, P95 ≤ 3000 ms |
| Onset → local stop P95 | `barge_in.onset_to_stop_ms` | ≤ 2500 ms |
| Local stop call | `barge_in.stop_latency_ms` | ≤ 50 ms (it is one PortAudio call) |
| Replays clamped | `replay.clamped` | 0 — otherwise raise `owner_buffer_ms` |
| False accepts | `input_gate.dropped` vs what you heard | no colleague turn ever answered |
| Owner misses | count of your sentences with no turn | ≤ 1 in 20; otherwise lower `owner_threshold` by one step |
| Verifier overruns | `owner.unavailable_codes` = {} and Control Center `dropped_ms` = 0 | yes |

Also record, with a stopwatch or a phone recording: **how long JARVIS keeps
making sound after you start speaking** (the trace measures the stop call, not
the loudspeaker).

## 5. Benchmark on real recordings

Synthetic TTS results (`docs/results/speaker-benchmark/2026-09-12-synthetic.*`)
are not evidence for production thresholds. Record real material instead — the
owner, real colleagues, the real room — and keep it out of Git:

```text
runtime/speaker-verification/benchmark/private/
  enroll-owner.wav           30 s, the enrollment material
  s01-owner-alone.wav        + s01-owner-alone.labels.txt   (Audacity label track)
  s02-owner-interrupts.wav   …
  manifest.json              copied from docs/speaker-benchmark-manifest.example.json, "evidence": "real"
```

Label with Audacity (`start<TAB>end<TAB>owner|non_owner|overlap|noise`), one
track per file, then:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_speaker_verification.py run `
    runtime\speaker-verification\benchmark\private\manifest.json `
    --sherpa-model campplus-zh-en-advanced --sherpa-model eres2net-en-voxceleb `
    --threshold-range 0.40:0.85:0.025 --gate-thresholds 0.45,0.5,0.55,0.6,0.65,0.7,0.75 `
    --evidence-ms 1000,1500,2000,2500 `
    --out-dir docs\results\speaker-benchmark --basename <date>-real
# then the same with --transition-guard-ms 1500 (pure speaker discrimination)
# and once with --realtime to confirm the thread keeps up (realtime_lag_ms)
```

Read it with §"Reading the results" of `docs/SPEAKER_BENCHMARK.md`. The
decision rule for Solo Owner is the **gate** block, not the hop rates: it is
what the provider would really receive.

| Question | Answer it with |
| --- | --- |
| Threshold | lowest `gate_sweep` row with `false_opens = 0` (that is `operating_points.gate_zero_false_open`) whose `owner_gate_miss_rate` you can live with (≤ 5 %); one step lower only if the miss rate is unacceptable, and check `noise_hops_accepted = 0` and `non_owner_forwarded_ms` at that threshold |
| Evidence window | shortest `--evidence-ms` variant holding that threshold with `gate_confirm_ms_p50` ≤ 2 s |
| Ring buffer | `owner_buffer_ms` ≥ `gate_confirm_ms_p95` + 750 ms, and `replays_clamped = 0`; raise it if `owner_start_lost_ms_p95` is a syllable or more |
| Short replies | `short_confirmations` > 0 and `drops_short_not_owner` low; tune `owner_short_evidence_ms` / `owner_short_margin` only after this |
| Engine | keep the baseline unless the other engine wins on `false_opens`, `owner_gate_miss_rate` **and** cost (`scoring_hop_ms.p95` well under 100 ms) |

Write the chosen values into the Control Center (**Réglages avancés — R&D**) and
restart Voice; the trace's `voice.owner.engine` line must show them.

## 6. Server VAD vs semantic VAD

Same owner, same room, two sessions of ten turns each, with hesitant speech
("euh… attends… en fait…") and one long sentence with a mid-sentence pause:

```text
Control Center → Mode vocal → (stack settings) → turn detection = server_vad, restart Voice
… ten turns …
Control Center → semantic_vad, restart Voice
… the same ten turns …
```

| Compare | Where |
| --- | --- |
| turns cut in the middle of a hesitation | count them by ear; `voice.transcript` fragments in the trace |
| time from end of speech to the answer | `voice.latency.surface_first_audio` and `voice.latency.brain_turn_accepted` |
| false turns on a breath | `voice.input_submitted` with a very short duration |

Keep the setting that cuts you off less; note that Solo Owner delays every turn
by the verification window, so a VAD that waits longer may now be free.

## 7. Work-state parity (Tasks 12/13)

1. Ask JARVIS, by voice, for two things that spawn background sub-agents.
2. Open the Control Center **Agents** panel: note "Source : état normalisé Core ·
   révision N".
3. `Invoke-RestMethod http://127.77.0.1:17653/v1/work/snapshot -Headers @{Authorization="Bearer $(Get-Content runtime\core.token)"}`
   (`JARVIS_CORE_HOST` / `JARVIS_CORE_PORT` change these defaults)
   — `revision` must equal N (or be newer), items identical.
4. Ask « où en sont mes tâches ? » — the answer must name the same labels,
   statuses and models; `core.brain.work_context` in the trace carries the same
   `store_id` and a revision ≥ N.
5. Kill one sub-agent: the card turns `interrompu`, one `core.work.attention` is
   traced, **nothing is spoken**.
6. Stop Core: the panel shows the yellow "Core indisponible" banner and
   `/api/agent/tasks` still answers. Restart Core: the panel relearns within
   ≈ 30 s and no card goes back from "terminé" to "en cours".
7. Switch the CLI to Codex: "Aucun sous-agent suivi pour ce CLI."

Pass = UI, brain and `/v1/work/snapshot` never disagree during the whole run.

## 8. Long session

One uninterrupted session of at least two hours with Solo Owner active, normal
office noise, at least one long brain job:

| Watch | Pass |
| --- | --- |
| Control Center → *Fil de vérification (Voice)* `dropped_ms` | 0 (CPU kept up) |
| Voice process memory (Task Manager) | stable within a few MB after the first minutes |
| `voice.owner.unavailable`, `voice.barge_in.authority` warnings | none |
| Recognition at the end of the session | as good as at the start (`owner_score` P50 in the last 15 min ≈ the first 15 min — compare with `--since`) |
| `Jarvis Mute` during a job | job survives in Core, nothing spoken, no auto-wake |

## 9. Full suite before declaring it done

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts\verify_release.py
```

## 10. Rollback (always available)

Control Center → **Mode vocal** → *Mode de conversation* = « Salle ouverte »
(or remove `conversation_mode` from `runtime/control-center-settings.json`),
then restart Voice. Barge-in returns to the acoustic rule, every voice reaches
the provider again, and no `voice.barge_in.authority` event is logged.
`speaker_verification = shadow` keeps measuring without deciding anything;
`speaker_verification = off` stops even that. The voice architecture is
independent: `legacy` remains the half-duplex fallback.

## 11. Result sheet to fill

```text
Date / operator:
Hardware (§0 table):
Shadow session: confirm P50/P95 = … ; owner score P50 = … ; colleague score max = …
Scenarios 1–10: PASS/FAIL each, with what was heard
Short replies: PASS/FAIL
Degraded states: PASS/FAIL
Numbers (§4): …
Benchmark (real): chosen engine / threshold / evidence / buffer + result file name
VAD comparison: chosen setting + why
Work-state parity: PASS/FAIL
Long session: PASS/FAIL
Suite: N passed, M skipped, duration
Decision: Solo Owner kept / rolled back, and why
```

Store the filled sheet next to the benchmark results
(`docs/results/speaker-benchmark/<date>-real.md` plus a short note), and update
`docs/ACCEPTANCE_STATUS.md` so the repository stops saying this is unverified.

---

## 12. Configurable wake word (openWakeWord)

Task `jarvis-wake-word`. **Mot d'éveil configurable (openWakeWord).** Status of
every check in this section: **À FAIRE** (not executed; nothing here is marked
validated, and no machine test replaces any of it). It needs the real microphone,
real speakers, the live JARVIS and the Human's own voice. No agent runs it; record
failures as failures, and never accept a feeling in place of a machine result:
each check below has a measured result (count, latency, trace line) kept apart
from the subjective impression.

What exists and what does not (so the checks test the shipped behaviour): the
wake word is **off by default**; the provider is `porcupine` or `openwakeword`;
SIMPLE runs a dedicated detector stream and thread, PRESENTATION reads the shared
hub; F9 and the wake word end in the same `activate()`; the sleep phrases are
exactly « Jarvis mute », « Jarvis stop listening » and « Jarvis arrête d'écouter »
(no « go to sleep »). The contract is `docs/presentation-audio-capture.md` §§ 6b-6c;
operations, install, licence and trace vocabulary are in `docs/OPERATIONS.md`
(« Mot d'éveil (bloc `wake_word`) », « Installer openWakeWord », « Diagnostic du
mot d'éveil »). The sub-check ids are those of
`tasks/jarvis-wake-word/slices/09-human-microphone-validation/human-validation.json`
and of `tasks/jarvis-wake-word/slices/07-control-center-ui/human-validation.json`.

### 12.0 Common prerequisites (once, then restart)

1. The three processes restarted from this commit (`core`, `control-center`, `voice`).
2. The extra installed in Voice's environment, **editable**, from the repository root, with
   the Python of Voice's virtual environment: `python -m pip install -e ".[wakeword]"`. Without
   `-e`, pip replaces the editable `jarvis` install of the live environment with a frozen copy.
3. The three models installed and verified (explicit command, network, asks first):
   `python -m jarvis wake-word install` (add `--yes` to skip the question); they land
   in `runtime/wake-word/models/`. Check with `python -m jarvis wake-word status`
   (no network; exit 0 only when the three models and the package are in place).
4. Control Center, Settings, *Mot d'éveil*: tick the switch, provider *openWakeWord*,
   word `hey_jarvis`, sensitivity and delay as the check says (**record the values**:
   defaults are sensitivity 0.5, threshold 0.5, delay 2000 ms), save, **restart
   Voice** (it reads the block at startup only).
5. Note the line count of `runtime/trace.jsonl` before each check, and read only
   what follows. Expected first lines after a restart: `wake.own_stream.started`
   (SIMPLE) or `wake.shared_pcm.started` (PRESENTATION), never a `.failed`.
6. PRESENTATION checks: mode PRESENTATION chosen in the Control Center on a
   continuous voice architecture (`presentation.runtime.entered` with
   `physical_input_owners: 1`).
7. No audio is recorded for any check. Success thresholds below are **proposed**
   defaults for the Human to confirm or change before the first run; change them
   in this table, not after seeing the result.

Reading a result: each line of `runtime/trace.jsonl` is JSON with `ts` (UTC ISO),
`kind`, `level`, `message`, `data`. A detection appears as `wake.own_stream.detected`
(SIMPLE) or `wake.shared_pcm.detected` (PRESENTATION), carrying `keyword`, `provider`,
`score` and `threshold`, then `voice.wake` (`source` = `wake_word` or `manual_key`,
the same score), `voice.connecting`, `voice.wake.outcome` (`state_before`,
`state_after`) and `voice.active`. A missed utterance leaves **no** line (the
engine keeps a below-threshold counter but writes no trace): hits are counted from
the trace, attempts from the Human's own tally. `scripts/measure_wake_word_validation.py`
does the counting from `runtime/trace.jsonl` (read only, no microphone, no speech text):
one run per series, the series being a range, for example
`python scripts/measure_wake_word_validation.py --since 2026-10-08T09:00 --until 2026-10-08T09:30`
(instants without a zone are UTC, `--until` excluded; `--json`, `--output-json <file>`,
`--runtime-dir <folder>`). It says what it cannot measure: **false negatives** (your
tally), acoustic latency, the engine build time, ignored cooldowns, and whether a
detection was deliberate. `scripts/check_wake_word_disabled.py` runs the `-i` owner
count on fake streams (it does not look at the live JARVIS). Each row below names
the command that reads its proof.

### 12.1 Checklist

| Id | Prerequisite (beyond 12.0) | Human gesture | Expected result | Where to read the proof | Success criterion (measurable) | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `HV-WAKEWORD-UI-01` | Settings open; Voice may be running or not | The six steps of `slices/07-control-center-ui/human-validation.json`: default screen, choose openWakeWord (licence line appears), enable and save (restart banner, badge « Activé dans le réglage »), reload, out-of-range sensitivity 1.5 refused with its code, read the detector's last event | Badge never says « en écoute »; licence only with openWakeWord; banner only after a save; a refused value keeps its input and shows its code | The screen itself; `GET /api/wake-word`; last `wake.*` line of `runtime/trace.jsonl` for the detector block | The three « expected » items of that file all observed | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-a` | 12.0; SIMPLE; JARVIS resting (BACKGROUND) | Say « Hey Jarvis » at about 1 m in your normal voice, 20 times, at least 5 s apart; return to rest between attempts with F9 or « Jarvis mute »; keep your own tally | Each hit opens the session | `wake.own_stream.detected` then `voice.wake` (`source: wake_word`, `keyword: hey_jarvis`, same `score`), `voice.connecting`, `voice.wake.outcome` (`state_before: background`, `state_after: active`), `voice.active` **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>` : « Détections » (SIMPLE) and « voice.wake source=wake_word » give the hits; « Latences » the activation chain. | At least 18 of 20 hits (90 %); every hit has all five lines; the score range of the hits is recorded | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-b` | 12.0 step 6; PRESENTATION | Same, 10 times; check the owner count at entry | The explicit address is armed on each hit; one microphone owner only | `presentation.runtime.entered` (`physical_input_owners: 1`); `wake.shared_pcm.detected`; `voice.wake`; the explicit-address admission line (`explicit_address.admitted`); the SIMPLE stream's own `wake.own_stream.stopped` at entry, then no `wake.own_stream.started` while PRESENTATION lasts **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>` on a range that starts after the PRESENTATION entry: « Détections » (PRESENTATION), « physical_input_owners », and « Réarmement du moteur : 0 démarrage(s) ». | At least 9 of 10 hits; `physical_input_owners` is 1 on every line that carries it; zero `wake.own_stream.started` between the entry and the exit | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-c` | 12.0; JARVIS resting; real ambient sound (room conversation, TV) | Leave JARVIS resting for one hour in SIMPLE, then one hour in PRESENTATION, with ambient speech and **without** saying the wake word; note the threshold in use | No activation | Count `wake.own_stream.detected` (SIMPLE) and `wake.shared_pcm.detected` (PRESENTATION) in each hour; each is a false positive candidate (the Human logged no deliberate utterance) **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end> --no-deliberate-activation`, once per hour and per mode: « Faux positifs candidats » gives the count and the rate per hour; « scores » and « seuils » give the threshold. | At most 1 false activation per hour per mode (proposed); the count and the threshold are recorded even when 0 | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-d` | 12.0; SIMPLE | Say « Hey Jarvis » 10 times at each of 0.5 m, 1 m, 2 m and 3 m, then 10 times at 1 m with the TV on at normal volume, then 10 times **in your own French-accented voice** (the model is trained on English; a French synthetic voice peaked at a score of 0.22 against a threshold of 0.5) | A rate per condition, not a feeling | Hits from `wake.own_stream.detected` per series; attempts from your tally **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>` once per condition: « Détections » gives the hits; the attempts are your tally. | Hit rate per condition recorded; proposed floors: 90 % at 0.5 m and 1 m, 70 % at 3 m; the accented series is **recorded as measured** and a rate under 70 % is reported as a limit (see `-l`), not hidden | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-e` | 12.0; SIMPLE, then PRESENTATION; speakers at normal volume, then headset | Ask JARVIS for answers of 20 s or more, then 5 times ask it to say « Hey Jarvis » aloud; 10 turns per mode and per output device; do not touch the keyboard | Its own voice never opens a session. There is **no tail guard** between the end of its playback and the detector resuming: this check measures that documented risk | Any `wake.*.detected` whose `ts` falls between the `voice.active` of a turn and 5 s after the following `voice.background`, with no deliberate utterance logged **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end> --echo-window-s 60 --tail-s 5`: « Indice d'écho » lists the detections after a speech end and inside a session or its 5 s tail. | Zero such detections in 10 turns per mode and device; one is a defect: open an Issue in `tasks/jarvis-wake-word/Issues/` proposing a tail guard (not implemented here) | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-f` | 12.0; SIMPLE (then PRESENTATION) | During an ACTIVE session press F9; also say « Hey Jarvis » once during ACTIVE; try both turn modes (auto, manual) | Automatic turn: F9 cancels (back to background); manual turn: the second press submits; the wake word opens no second session. In PRESENTATION the key keeps the session and arms the address | `voice.manual_cancel` then `voice.background` (auto), or `voice.manual_submit` with `source: manual_key` (manual), or `voice.presentation_address_key` (PRESENTATION); no second `voice.connecting` or `voice.active` for the spoken wake word **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>`: « Événements de touche » (`voice.manual_cancel`, `voice.manual_submit`, `voice.presentation_address_key`) and the `voice.wake` counts by source. | Behaviour identical to before the feature; zero extra sessions | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-g` | 12.0; ACTIVE session | Say, in three separate sessions, « Jarvis mute », « Jarvis stop listening », « Jarvis arrête d'écouter »; then « Hey Jarvis » each time; also say « go to sleep » and « stop listening » (without « Jarvis ») once: they must **not** end the session. **D2 to confirm**: whether « stop listening » and « arrête d'écouter » stay (two lines of `SLEEP_COMMANDS` in `realtime_audio.py`) | The three phrases end the session; the detector re-arms; the two other phrases do nothing | `voice.background` after each phrase; then `wake.*.detected`, `voice.wake`, `voice.active` for the next « Hey Jarvis »; no `voice.background` for the two negative phrases **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>`: « retour(s) au repos » counts the `voice.background` lines, « voice.background -> détection suivante » the re-wakes. | 3 of 3 sleep phrases end the session; 3 of 3 re-wakes; 0 of 2 negatives end it; the Human's decision on D2 written in the result sheet | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-h` | 12.0; stop Voice, rename `runtime/wake-word/models` to `models.off`, start Voice (repeat in PRESENTATION) | Press F9; open Settings and read the detector block; rename the folder back, run one ACTIVE then « Jarvis mute » cycle (SIMPLE) | Voice starts, F9 still opens a session, the cause is said, and in SIMPLE the next `resume()` rebuilds the engine without restarting Voice | `wake.own_stream.failed` (SIMPLE) or `wake.shared_pcm.failed` (PRESENTATION) with `code: wake_engine_unavailable`, `cause_code: wake_model_missing`; `voice.wake` with `source: manual_key` then `voice.active`; after the restore `wake.own_stream.started` **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>`: « Pannes du détecteur » (code, cause, lines, `suppressed`, one line per minute rule); `python -m jarvis wake-word status` for the model folder. | Cause code present; F9 session opened; no more than one failure line per minute for the same cause; SIMPLE re-arms without a Voice restart | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-i` | `wake_word.enabled` false (the default) and no Picovoice key; restart Voice; SIMPLE, resting | Let JARVIS rest for 10 minutes; look at the Windows microphone privacy page (Settings, Privacy and security, Microphone) while it rests; then enter PRESENTATION and read the owner count | No resting microphone stream. The ownership registry count is not exposed outside tests and the PRESENTATION entry line, so the proof is indirect (see note) | No `wake.own_stream.started` or `wake.shared_pcm.started` line; the privacy page does not show the Voice interpreter as using the microphone at rest; `presentation.runtime.entered` `physical_input_owners: 1`; automated count 0 in `tests/unit/test_simple_wake_word_wiring.py` **Read with:** `python scripts/check_wake_word_disabled.py` (owner count with fake streams, Issue 003); `python -m jarvis wake-word status`; `python scripts/measure_wake_word_validation.py --since <start> --until <end>` (« Réarmement du moteur : 0 démarrage(s) », « physical_input_owners »). | All three observations hold; any detector line with the switch off is a defect | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-j` | 12.0; SIMPLE | 20 activations by « Hey Jarvis » and, for the baseline, 20 by F9, same conditions | Latency from detection to ACTIVE, split in two | From each trace: `voice.wake` to `voice.active` (includes the Realtime session connect), and `wake.own_stream.detected` to `voice.wake` (queue to Voice); median and p95 per source **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end> --output-json <file>`: « voice.wake -> voice.active » and « détection -> voice.wake » (median, p95 per source), and the median difference wake word minus F9. | Medians recorded; proposed: wake-word median within 200 ms of the F9 median (same path), detected-to-`voice.wake` median under 100 ms. Acoustic latency (end of utterance to detection) is **not** observable from the trace; do not infer it | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-k` | 12.0; SIMPLE | 20 cycles: wake, then « Jarvis mute »; after each mute say « Hey Jarvis » after a delay you shorten from 3 s down to 0.5 s | The detector is back after each mute. Every `mute()` frees and **reloads the engine** (about 155 ms in a throwaway venv, never measured on this machine) | `wake.own_stream.stopped` / `.started` pairs; `.started` is written **before** `voice.background` (the engine is rebuilt inside `resume()`, then the state returns to rest), so the signed offset `.started` to `voice.background` is the tail only, and the build time itself is not traced; the shortest delay at which the next « Hey Jarvis » hits is `voice.background` to the next detection **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>`: « Réarmement du moteur » (signed started to background offset, background to next detection); the engine build time itself is not traced. | Median reload under 500 ms and p95 under 1.5 s (proposed); the shortest successful delay recorded; no deaf period longer than the reload | **À FAIRE** |
| `HV-WAKEWORD-MIC-01-l` | 12.0; SIMPLE | Repeat the one-hour false-positive count and the 1 m hit rate at sensitivity 0.3, 0.5 and 0.7 (restart Voice after each change); the default 0.5 (threshold 0.5) is **not calibrated** on a real microphone | A measured trade-off; the final default chosen from numbers | `score` and `threshold` of every detection; counts from `-a`, `-c` and `-d` per setting **Read with:** `python scripts/measure_wake_word_validation.py --since <start> --until <end>` once per sensitivity setting: « scores » and « seuils », combined with the `-a`, `-c` and `-d` series. | The lowest false-positive rate that keeps at least 90 % at 1 m; the chosen default (or « keep Porcupine ») written with the table | **À FAIRE** |

Note on `-i`: the ownership registry (`jarvis/audio/input_ownership.py`) has no
public reading at rest in the live SIMPLE process (Issue 003, still open); this is
recorded as a limit, not a pass. `python scripts/check_wake_word_disabled.py` composes
the SIMPLE wake word with the switch off on a fake stream and prints the owner count
(0, with a positive control at 1): it proves the code path, not the live process.
The live proof stays the three observations of the row.

### 12.2 Result sheet (copy outside Git if it names people; commit only scalars)

```text
Date / operator / OS build / input device / sample rate:
Extra and model versions (pip list, SHA-256 from the catalog):
Settings used (sensitivity, delay) and threshold read from the trace:
UI-01: observations per step
a: hits / 20, score range
b: hits / 10, physical_input_owners
c: false activations per hour, SIMPLE / PRESENTATION
d: hit rate per distance, with TV, accented voice
e: spurious detections per mode and output device
f: observed behaviour per turn mode
g: phrases that slept, re-wakes, negatives; D2 decision
h: failure code seen, F9 ok, re-arm ok
i: observations (no stream line, privacy page, owners)
j: median / p95, wake word vs F9
k: reload median / p95, shortest delay
l: table per sensitivity; chosen default
Decision: openWakeWord kept / sensitivity default / keep Porcupine / Issues opened
```

When a result comes in, update the status column here, the `HV-WAKEWORD-*` rows of
`docs/ACCEPTANCE_STATUS.md`, and `tasks/jarvis-wake-word/LOG.md`.
