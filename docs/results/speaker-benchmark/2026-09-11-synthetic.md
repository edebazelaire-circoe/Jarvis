# Speaker verification benchmark — synthetic

> **SYNTHETIC TTS VOICES - NOT evidence for production thresholds. Windows TTS voices are far more separable than real people in a real office; Task 14 must re-run this benchmark on the owner's own recordings and real office background speech before choosing an engine, threshold or evidence window.**

- Generated: 2026-09-11T20:07:10+00:00 · schema `jarvis.speaker_benchmark.result` v1 · mode offline · evidence **synthetic**
- Manifest: `runtime/speaker-verification/benchmark/synthetic/manifest.json` (SHA-256 `9330e09d58f6…`), 3 profile(s), 39 scenario(s), 516 s of audio
- Host: Windows-11-10.0.26200-SP0 · Intel64 Family 6 Model 154 Stepping 3, GenuineIntel · 20 logical CPUs · Python 3.14.6
- Preprocessing (identical for all engines): capture 24000 Hz, 100 ms hops, energy gate +10.0 dB over floor (min -55.0 dBFS), no AEC / noise reduction
- Scoring: {"confirm_grace_ms": 200, "transition_guard_ms": 0, "min_label_coverage": 0.5, "event_merge_gap_ms": 1000}

## Engines at their configured threshold

| Engine | Model (dim) | Thr. | FAR | FRR | Owner miss | Confirm P50 / P95 ms | Overlap confirmed | Non-owner FA events | EER (thr.) | Zero-FA thr. → FRR, P95 | Scoring hop P50 / P95 ms | CPU % core | Load ms | RSS Δ MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| campplus-zh-en-advanced | 3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced (192) | 0.5 | 6.6 % | 3.3 % | 0.0 % | 1600 / 2330 | 9/9 | 6/24 | 5.3 % (0.545) | 0.9 → 97.3 %, 3150 | 29.6 / 32.7 | 3.0 | 570 | 85.0 |
| campplus-zh-cn-common | 3dspeaker_speech_campplus_sv_zh-cn_16k-common (192) | 0.5 | 15.9 % | 4.3 % | 2.6 % | 1600 / 2470 | 9/9 | 10/24 | 7.7 % (0.542) | 0.85 → 93.0 %, 4560 | 29.3 / 32.3 | 3.0 | 521 | 85.2 |
| campplus-en-voxceleb | 3dspeaker_speech_campplus_sv_en_voxceleb_16k (512) | 0.5 | 26.4 % | 55.6 % | 25.6 % | 1600 / 4100 | 8/9 | 14/24 | 38.8 % (0.469) | 0.65 → 100.0 %, — | 29.3 / 32.2 | 3.0 | 563 | 86.1 |
| eres2net-en-voxceleb | 3dspeaker_speech_eres2net_sv_en_voxceleb_16k (192) | 0.5 | 5.6 % | 5.4 % | 0.0 % | 1600 / 2680 | 9/9 | 6/24 | 5.6 % (0.504) | 0.9 → 99.6 %, 1600 | 73.3 / 202.0 | 8.1 | 338 | 111.2 |
| eres2net-base-200k-zh-cn | 3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common (512) | 0.5 | 16.7 % | 2.1 % | 0.0 % | 1600 / 2200 | 9/9 | 9/24 | 4.0 % (0.614) | 0.9 → 100.0 %, — | 204.5 / 284.1 | 16.2 | 365 | 128.5 |
| eres2net-base-3dspeaker | 3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k (512) | 0.5 | 14.4 % | 4.3 % | 0.0 % | 1600 / 3420 | 9/9 | 9/24 | 6.9 % (0.584) | 0.9 → 100.0 %, — | 156.7 / 295.6 | 15.3 | 364 | 127.8 |
| eres2netv2-zh-cn | 3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common (192) | 0.5 | 27.7 % | 2.1 % | 0.0 % | 1600 / 2200 | 9/9 | 13/24 | 5.7 % (0.608) | 0.9 → 98.7 %, 1695 | 536.0 / 687.0 | 52.0 | 694 | 212.6 |
| wespeaker-resnet34-en-voxceleb | wespeaker_en_voxceleb_resnet34 (256) | 0.5 | 59.2 % | 0.1 % | 0.0 % | 1600 / 1930 | 9/9 | 18/24 | 6.2 % (0.680) | 0.95 → 99.6 %, 1600 | 239.0 / 347.8 | 22.1 | 245 | 80.9 |

FAR = accepted / judged hops where only another voice speaks; FRR = rejected / judged hops where only the owner speaks; owner miss = owner events never confirmed; confirm = first accepted hop end − owner onset; EER from all judged hop scores; zero-FA thr. = lowest swept threshold with no false accept at all (hops, events, noise). Definitions: `docs/SPEAKER_BENCHMARK.md`.
