# Solo Owner + Core work state — workstation acceptance (Task 14)

**Status: PENDING USER.** Everything in this document needs the owner's own
voice, the real microphone and speakers, real background conversation and the
real provider. No agent can run it and no result may be invented. What *was*
automated (unit/integration suite, synthetic benchmark, defaults decision) is in
[`docs/fixes/solo-owner-duplex/final-implementation-report.md`](fixes/solo-owner-duplex/final-implementation-report.md).

Everything below is runnable as written. Fill the tables as you go; keep the
filled copy outside Git if it names people, and publish only scalars
(`docs/results/speaker-benchmark/` holds scores and timings, never audio).

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
