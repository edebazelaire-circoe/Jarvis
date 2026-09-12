# Speaker verification benchmark — synthetic

> **SYNTHETIC TTS VOICES - NOT evidence for production thresholds. Windows TTS voices are far more separable than real people in a real office; Task 14 must re-run this benchmark on the owner's own recordings and real office background speech before choosing an engine, threshold or evidence window.**

- Generated: 2026-09-11T23:03:05+00:00 · schema `jarvis.speaker_benchmark.result` v2 · mode offline · evidence **synthetic**
- Manifest: `runtime/speaker-verification/benchmark/synthetic/manifest.json` (SHA-256 `9330e09d58f6…`), 3 profile(s), 39 scenario(s), 516 s of audio
- Host: Windows-11-10.0.26200-SP0 · Intel64 Family 6 Model 154 Stepping 3, GenuineIntel · 20 logical CPUs · Python 3.14.6
- Preprocessing (identical for all engines): capture 24000 Hz, 100 ms hops, energy gate +10.0 dB over floor (min -55.0 dBFS), no AEC / noise reduction
- Scoring: {"confirm_grace_ms": 200, "transition_guard_ms": 0, "min_label_coverage": 0.5, "event_merge_gap_ms": 1000}

## Engines at their configured threshold

| Engine | Model (dim) | Thr. | FAR | FRR | Owner miss | Confirm P50 / P95 ms | Overlap confirmed | Non-owner FA events | EER (thr.) | Zero-FA thr. → FRR, P95 | Scoring hop P50 / P95 ms | CPU % core | Load ms | RSS Δ MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| campplus-zh-en-advanced | 3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced (192) | 0.6 | 1.3 % | 28.0 % | 0.0 % | 1700 / 3690 | 9/9 | 4/24 | 5.3 % (0.545) | 0.9 → 97.3 %, 3150 | 30.4 / 46.6 | 3.6 | 588 | 107.9 |
| eres2net-en-voxceleb | 3dspeaker_speech_eres2net_sv_en_voxceleb_16k (192) | 0.6 | 1.7 % | 16.4 % | 0.0 % | 1600 / 3240 | 9/9 | 4/24 | 5.6 % (0.504) | 0.9 → 99.6 %, 1600 | 76.7 / 110.8 | 8.3 | 359 | 132.4 |

## Solo Owner input gate (what the provider would really receive)

| Engine | Thr. | Owner turns forwarded | Miss | Confirm P50 / P95 ms | Short replies | Start lost P95 ms | Owner audio forwarded | Openings (false) | Non-owner events opened | Non-owner leaked ms (max run) | Noise ms | Replays clamped | Zero-false-open thr. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| campplus-zh-en-advanced | 0.6 | 36/39 | 7.7 % | 1650 / 3825 | 3 | 2325 | 87.6 % | 54 (3) | 1/24 | 6700 (3200) | 410 | 0 | 0.65 → miss 10.3 % |
| eres2net-en-voxceleb | 0.6 | 38/39 | 2.6 % | 1600 / 3310 | 2 | 1810 | 92.8 % | 47 (2) | 1/24 | 6800 (3200) | 410 | 0 | 0.65 → miss 5.1 % |

Gate replay = the production path (near-end candidates, rolling verification, end-of-candidate short replies, handover sub-window, owner replay ring), JARVIS silent. A false open is a flow opening whose replayed span holds no owner speech; leaked ms are non-owner-only audio forwarded after a handover.

FAR = accepted / judged hops where only another voice speaks; FRR = rejected / judged hops where only the owner speaks; owner miss = owner events never confirmed; confirm = first accepted hop end − owner onset; EER from all judged hop scores; zero-FA thr. = lowest swept threshold with no false accept at all (hops, events, noise). Definitions: `docs/SPEAKER_BENCHMARK.md`.
