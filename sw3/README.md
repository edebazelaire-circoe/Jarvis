# Speaker-verification benchmark results

Produced by `scripts/benchmark_speaker_verification.py` (usage and metric definitions:
[`docs/SPEAKER_BENCHMARK.md`](../../SPEAKER_BENCHMARK.md)). Each run = `<name>.json`
(full, schema `jarvis.speaker_benchmark.result` — v1 for the 2026-09-11 runs, v2 since
2026-09-12), `<name>.csv` (one row per engine × threshold, plus the gate rows since v2) and
`<name>.md` (generated summary). Files contain scores, timings and metadata only — no
audio, no voiceprint.

## 2026-09-12 — synthetic, with the Solo Owner input gate (Task 14)

> **SYNTHETIC TTS VOICES — NOT evidence for production thresholds.** The real
> workstation protocol is `docs/HARDWARE_ACCEPTANCE.md` (PENDING USER).

Same fixtures, same host and same command as the 2026-09-11 run (two engines only:
the production baseline and the one candidate worth re-measuring), plus
`--gate-thresholds 0.45,…,0.75`. Two changes make the numbers differ from
2026-09-11 and matter more than the engines:

1. the replayed verifier now carries the Task 07 rules (end-of-candidate verdict for
   short replies, handover sub-window), so its own decisions are production's;
2. a second replay drives the **real capture, worker and telemetry** and reports what
   the provider would actually receive (`gate_*` metrics).

Sources of the table below, column group by column group: **hop FAR / FRR** =
`2026-09-12-synthetic.json` (strict) `engines[].sweep[]`; **EER** = `eer.eer` of
`2026-09-12-synthetic.json` and `…-settled.json`; **every `Gate:` column** =
`2026-09-12-synthetic.json` `engines[].gate_sweep[]` — the settled run was
launched without `--gate-thresholds` and carries no gate block at all.

| Engine | Thr. | Hop FAR / FRR (strict) | EER strict / settled | Gate: owner turns forwarded | Gate: openings (false) | Gate: non-owner events opened | Gate: leaked ms (max run) | Gate: confirm P50 / P95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **campplus-zh-en-advanced** (production baseline) | 0.5 | 6.6 % / 3.3 % | 5.3 % / 1.1 % | 39/39 | 47 (4) | 4/24 | 11 100 (4 700) | 1600 / 2720 |
| campplus-zh-en-advanced | 0.55 | 5.1 % / 5.3 % | — | 37/39 (miss 5.1 %) | 48 (3) | 1/24 | 8 200 (4 700) | 1600 / 3600 |
| campplus-zh-en-advanced | **0.6** (new default) | 3.2 % / 6.8 % | — | 36/39 (miss 7.7 %) | 54 (3) | **1/24** | 6 700 (3 200) | 1650 / 3825 |
| campplus-zh-en-advanced | 0.65 | 1.9 % / 9.1 % | — | 35/39 (miss 10.3 %) | 60 (**0**) | 1/24 | 2 500 (700) | 1700 / 4290 |
| eres2net-en-voxceleb | 0.5 | 5.6 % / 5.4 % | 5.6 % / 1.1 % | 39/39 | 45 (2) | 4/24 | 11 400 (4 700) | 1600 / 3460 |
| eres2net-en-voxceleb | 0.6 | 3.7 % / 8.5 % | — | 38/39 (miss 2.6 %) | 47 (2) | 1/24 | 6 800 (3 200) | 1600 / 3310 |
| eres2net-en-voxceleb | 0.65 | 1.9 % / 11.4 % | — | 37/39 (miss 5.1 %) | 46 (**0**) | 0/24 | 2 300 (700) | 1700 / 4680 |

Hop FAR / FRR above are the swept **window** scores (pure discrimination). The
generated summaries also show `at_engine_threshold`, where the Task 07 rules apply:
there the baseline reads 1.3 % / 28.0 % at 0.6. Both figures matter and neither
replaces the other:

- **28.0 % is real.** More than one judged 100 ms window in four, over the owner's
  own speech, is refused at the chosen default — mostly on his quieter passages,
  where the recent-window rule briefly closes the flow.
- It does **not** mean a quarter of his turns are lost, because a later window of
  the same turn reopens the flow: at the gate, 87.6 % of his owner-only audio is
  still forwarded and 3 of his 39 turns are never forwarded at all (miss 7.7 %).
- So decide on the gate columns, but read 28.0 % as the margin being spent: it is
  what degrades first on a worse microphone, a noisier room, or a voice less
  separable than a TTS voice.

Cost, from `2026-09-12-synthetic-settled.json` `engines[].resources` (i7-12700H,
one ONNX thread):

| Figure (`resources` key) | campplus-zh-en-advanced | eres2net-en-voxceleb |
| --- | --- | --- |
| Scoring hop P50 (`scoring_hop_ms.p50`) | 30.1 ms | 76.9 ms |
| CPU, share of one core (`cpu_pct_one_core`) | 3.51 % | 8.30 % |
| Model load (`model_load_ms`) | 517.6 ms | 339.8 ms |
| Steady RSS delta (`rss_steady_delta_mb`) | +107.4 MB | +133.5 MB |

The strict run of the same code on the same host reports 588.2 ms / 359.0 ms for
the load and +107.9 MB / +132.4 MB of RSS: timings are orders of magnitude, not
specifications.

Gate confirmation latency, from `2026-09-12-synthetic.json`
`gate_sweep[].gate_confirm_ms_p50`, thresholds 0.45 → 0.75: baseline 1600, 1600,
1600, **1650**, 1700, 2100, 2450 ms; ERes2Net-VoxCeleb 1600, 1600, 1600,
**1600**, 1700, 1700, 1750 ms. Up to the 0.6 default it is set by
`owner_evidence_ms` (1500 ms + one 100 ms hop), not by the model; above it the
threshold itself adds the delay.

**What is machine-checked on this page.** Every cell of the two tables above, of
the 2026-09-11 table below, and every measurement quoted in the paragraphs and
observations around them, is re-derived from the named JSON by
`.venv\Scripts\python.exe scripts\speaker_benchmark_figures.py` and compared
**cell by cell, row by row, engine column by engine column** by
`tests/unit/test_published_benchmark_figures.py`: swapping two engines' columns,
substituting a whole row, deleting a row or altering a single count makes that
file fail, and a measurement whose key is missing from a result file raises
instead of printing `0.0`. `--key <clé>` prints one figure with its source file
and JSON path.

**What is not.** Four kinds of statement are transcribed by hand and **not**
asserted: the two loose approximations `0.8–0.9 for up to ~1.5 s` and
`strict zero-FA thresholds ≈ 0.9 → FRR > 90 %` (observation 3) and `≈ 2 % FRR`
(observation 2); the counts restated in words ("one judged 100 ms window in
four", "a quarter of his turns", "one owner turn in ten", "the three short
replies"), each the plain-language form of a figure the tables do carry; the
fixture parameters (seed, voice list, gains `12 dB` / `−18 dB` / `−50 dBFS`,
sweep step), which come from the manifest rather than from a measurement; and the
configuration constants (`owner_evidence_ms` 1500, `owner_buffer_ms` 2500,
`owner_short_evidence_ms` 600, `owner_short_margin` 0.1, the 100 ms hop), which
come from the code. Read those as commentary; the tables are the evidence.

What it changed (decision record: the final report, §"Defaults decision"):

- **`owner_threshold` 0.5 → 0.6** (provisional, `sherpa_speaker_embedder.DEFAULT_THRESHOLD`).
  At 0.5 the gate opened the provider flow during 4 of the 24 colleague turns and
  forwarded 11.1 s of their speech, with 4 openings whose replayed span holds less
  than 20 % owner speech (`false_opens`); at 0.6 that drops to 1 turn, 6.7 s and 3
  such openings, for a confirmation P50 moving from 1600 to 1650 ms. 0.65 is where
  `false_opens` reaches zero (`operating_points.gate_zero_false_open`), but it
  misses one owner turn in ten (10.3 %) and loses 2.79 s of sentence start
  (`owner_start_lost_ms_p95`) — too aggressive to ship on synthetic evidence alone.
- `owner_evidence_ms` (1500), `owner_buffer_ms` (2500), `owner_short_evidence_ms`
  (600) and `owner_short_margin` (0.1) unchanged: `replays_clamped` is 0 at every
  threshold for both engines, the three short replies were still confirmed at the
  0.6 default by the baseline (`short_confirmations` 3 from 0.45 to 0.65 and 2 at
  0.70–0.75; ERes2Net-VoxCeleb is already at 2 at the 0.6 default and at 0 at
  0.75), and shortening the evidence window is what would raise FAR.
- Engine unchanged (baseline). ERes2Net-VoxCeleb behaves slightly better at the gate
  for 2.4× the CPU; it stays the one candidate to re-measure on real voices.
- If the owner is missed too often on real voices, **0.55** is the fallback: on this
  set it buys the same drop in colleague turns opened (4 → 1) for half the owner cost
  (miss 5.1 %, 91.3 % of his audio forwarded), but leaves the worst-case handover leak
  at 4.7 s instead of 3.2 s.

## 2026-09-11 — synthetic (Windows TTS), all local sherpa-onnx candidates

> **SYNTHETIC TTS VOICES — NOT evidence for production thresholds.** Nothing here
> changes a default; Task 14 re-runs the benchmark on the owner's real recordings.

- Fixtures: `generate-synthetic` (seed 20260911), 7 voices (OneCore Hortense, Julie,
  Paul, George, Susan, Hazel; SAPI Zira), owners in turn Hortense / Julie / Paul, 39
  scenarios, 516 s. Every voice reads French text.
- Command: `run runtime/speaker-verification/benchmark/synthetic/manifest.json
  --sherpa-model downloaded` (one process per engine), then the same with
  `--transition-guard-ms 1500`.
- Host: i7-12700H laptop, Windows 11, Python 3.14.6, sherpa-onnx 1.13.8, one ONNX
  thread. The live JARVIS runtime and other agents' test suites were running: the
  strict run's timings for the ERes2Net models are ~2–3× the settled run's (same
  code) — use timings as orders of magnitude only.
- [`2026-09-11-synthetic`](2026-09-11-synthetic.md): strict scoring (a speaker change
  counts as an error until the 1.5 s evidence window has refilled).
- [`2026-09-11-synthetic-settled`](2026-09-11-synthetic-settled.md): hops within 1.5 s
  after a label change excluded — pure speaker discrimination.

| Engine (dim) | EER strict / settled | FAR / FRR @ 0.5 (settled) | Confirm P50 / P95 @ 0.5 | Zero-FA thr. (settled) → FRR, miss, P95 | Scoring hop P50 ms* | CPU % core* | Load ms* |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **campplus-zh-en-advanced** (192, production baseline) | 5.3 % / **1.1 %** | 4.8 % / 0.0 % | 1600 / 2330 | **0.65 → 2.2 %, 0.0 %, 2940 ms** | 34 | 3.5 | 866 |
| campplus-zh-cn-common (192) | 7.7 % / 4.6 % | 14.4 % / 1.2 % | 1600 / 2470 | 0.65 → 10.5 %, 7.7 %, 4425 ms | 34 | 3.5 | 708 |
| campplus-en-voxceleb (512) | 38.8 % / 39.3 % | 26.5 % / 56.2 % | 1600 / 4100 | none usable (FRR 100.0 %) | 34 | 3.5 | 736 |
| eres2net-en-voxceleb (192) | 5.6 % / **1.1 %** | 3.7 % / 0.0 % | 1600 / 2680 | **0.65 → 2.1 %, 0.0 %, 3430 ms** | 88 | 8.6 | 398 |
| eres2net-base-200k-zh-cn (512) | 4.0 % / 1.2 % | 15.6 % / 0.0 % | 1600 / 2200 | 0.70 → 10.7 %, 5.1 %, 4500 ms | 90 | 8.8 | 463 |
| eres2net-base-3dspeaker (512) | 6.9 % / 1.5 % | 13.5 % / 0.2 % | 1600 / 3420 | 0.70 → 9.2 %, 2.6 %, 5100 ms | 91 | 8.9 | 461 |
| eres2netv2-zh-cn (192) | 5.7 % / 3.6 % | 26.9 % / 0.0 % | 1600 / 2200 | 0.75 → 21.2 %, 12.8 %, 5275 ms | 175 | 16.7 | 790 |
| wespeaker-resnet34-en-voxceleb (256) | 6.2 % / 3.5 % | 58.5 % / 0.0 % | 1600 / 1930 | 0.90 → 64.2 %, 41.0 %, 6440 ms | 75 | 7.3 | 187 |

\* settled run. FAR/FRR are hop-level; "miss" = owner events never confirmed. The
sweep step is 0.05, so zero-FA thresholds are quantized.

Observations (synthetic only):

1. The production baseline is the best trade-off here: best EER with ERes2Net-VoxCeleb
   at a third of its CPU (one scoring hop ≈ 34 ms per 500 ms of new speech).
   ERes2Net-VoxCeleb is the only candidate worth re-measuring on real voices; the
   512-dim VoxCeleb CAM++ again fails (confirms Task 03), ERes2NetV2 is too slow
   for its accuracy (175–536 ms per scoring hop vs a 100 ms hop).
2. The production threshold 0.5 still lets false accepts through on this set
   (baseline: 4 of 24 non-owner events): the closest impostors are another French
   female TTS voice (Julie vs Hortense: up to 0.65 in a 3 s overlap, 0.56 far-field
   with reverberation). With a 1.5 s window, 0.65 is the lowest swept threshold with
   zero false accepts at ≈ 2 % FRR and no missed owner event.
3. Strict scoring shows a structural effect of the sliding window, independent of the
   engine: when a colleague speaks immediately after the owner, the window still
   holds the owner's speech and scores 0.8–0.9 for up to ~1.5 s (`owner_then_non_owner`).
   No threshold removes it (strict zero-FA thresholds ≈ 0.9 → FRR > 90 %); the input
   gate (Task 07) must not treat a lingering confirmation as permission for the next
   speech segment.
4. Confirmation latency P50 = 1.6 s **at 0.5** for every engine (1.5 s evidence + one
   hop): at that threshold it is set by `owner_evidence_ms`, not by the model. It is
   **not** threshold-independent — `sweep[].confirm_ms_p50` rises further up the
   sweep (baseline 1700 ms at 0.75 and at 0.80, 2200 ms at 0.90; campplus-zh-cn-common
   1950 ms at 0.80; eres2netv2-zh-cn 2000 ms at 0.85) — and P95 moves earlier and
   further (baseline 2330 ms at 0.5, 2940 ms at 0.65, 6475 ms at 0.85): both grow
   because exceeding a higher threshold after a non-owner or in overlap takes longer.
   All 9 overlap events were confirmed by the baseline at 0.5 and at 0.65.
5. Keyboard / desk transients and −50 dBFS noise never produced an owner acceptance
   at any engine's **own** threshold (`at_engine_threshold.noise_hops_accepted` = 0
   of 354 for all eight). Only swept thresholds ≤ 0.35 accept any at all, and only
   for CAM++ zh-en advanced (≤ 0.10), CAM++ VoxCeleb (≤ 0.35) and WeSpeaker
   ResNet34 (≤ 0.05) — 11 hops each. A 12 dB quieter owner scored as well as the
   nominal level; −18 dB + synthetic reverberation lowered the baseline's owner scores
   (mean ≈ 0.75, minimum 0.62) but every owner event was still confirmed at 0.65.
