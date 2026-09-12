# Speaker verification benchmark — synthetic

> **SYNTHETIC TTS VOICES - NOT evidence for production thresholds. Windows TTS voices are far more separable than real people in a real office; Task 14 must re-run this benchmark on the owner's own recordings and real office background speech before choosing an engine, threshold or evidence window.**

- Generated: 2026-09-11T20:14:12+00:00 · schema `jarvis.speaker_benchmark.result` v1 · mode offline · evidence **synthetic**
- Manifest: `runtime/speaker-verification/benchmark/synthetic/manifest.json` (SHA-256 `9330e09d58f6…`), 3 profile(s), 39 scenario(s), 516 s of audio
- Host: Windows-11-10.0.26200-SP0 · Intel64 Family 6 Model 154 Stepping 3, GenuineIntel · 20 logical CPUs · Python 3.14.6
- Preprocessing (identical for all engines): capture 24000 Hz, 100 ms hops, energy gate +10.0 dB over floor (min -55.0 dBFS), no AEC / noise reduction
- Scoring: {"confirm_grace_ms": 200, "transition_guard_ms": 1500, "min_label_coverage": 0.5, "event_merge_gap_ms": 1000}

## Engines at their configured threshold

| Engine | Model (dim) | Thr. | FAR | FRR | Owner miss | Confirm P50 / P95 ms | Overlap confirmed | Non-owner FA events | EER (thr.) | Zero-FA thr. → FRR, P95 | Scoring hop P50 / P95 ms | CPU % core | Load ms | RSS Δ MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| campplus-zh-en-advanced | 3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced (192) | 0.5 | 4.8 % | 0.0 % | 0.0 % | 1600 / 2330 | 9/9 | 4/24 | 1.1 % (0.630) | 0.65 → 2.2 %, 2940 | 33.9 / 39.9 | 3.5 | 866 | 85.3 |
| campplus-zh-cn-common | 3dspeaker_speech_campplus_sv_zh-cn_16k-common (192) | 0.5 | 14.4 % | 1.2 % | 2.6 % | 1600 / 2470 | 9/9 | 8/24 | 4.6 % (0.550) | 0.65 → 10.5 %, 4425 | 33.8 / 41.4 | 3.5 | 708 | 84.8 |
| campplus-en-voxceleb | 3dspeaker_speech_campplus_sv_en_voxceleb_16k (512) | 0.5 | 26.5 % | 56.2 % | 25.6 % | 1600 / 4100 | 8/9 | 14/24 | 39.3 % (0.471) | 0.65 → 100.0 %, — | 33.8 / 38.8 | 3.5 | 736 | 86.5 |
| eres2net-en-voxceleb | 3dspeaker_speech_eres2net_sv_en_voxceleb_16k (192) | 0.5 | 3.7 % | 0.0 % | 0.0 % | 1600 / 2680 | 9/9 | 4/24 | 1.1 % (0.606) | 0.65 → 2.1 %, 3430 | 88.2 / 108.2 | 8.6 | 398 | 114.5 |
| eres2net-base-200k-zh-cn | 3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common (512) | 0.5 | 15.6 % | 0.0 % | 0.0 % | 1600 / 2200 | 9/9 | 9/24 | 1.2 % (0.626) | 0.7 → 10.7 %, 4500 | 89.8 / 115.0 | 8.8 | 463 | 127.0 |
| eres2net-base-3dspeaker | 3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k (512) | 0.5 | 13.5 % | 0.2 % | 0.0 % | 1600 / 3420 | 9/9 | 7/24 | 1.5 % (0.628) | 0.7 → 9.2 %, 5100 | 90.7 / 112.5 | 8.8 | 461 | 125.0 |
| eres2netv2-zh-cn | 3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common (192) | 0.5 | 26.9 % | 0.0 % | 0.0 % | 1600 / 2200 | 9/9 | 13/24 | 3.6 % (0.620) | 0.75 → 21.2 %, 5275 | 175.4 / 192.4 | 16.7 | 790 | 210.8 |
| wespeaker-resnet34-en-voxceleb | wespeaker_en_voxceleb_resnet34 (256) | 0.5 | 58.5 % | 0.0 % | 0.0 % | 1600 / 1930 | 9/9 | 18/24 | 3.5 % (0.729) | 0.9 → 64.2 %, 6440 | 75.3 / 80.8 | 7.3 | 186 | 79.5 |

FAR = accepted / judged hops where only another voice speaks; FRR = rejected / judged hops where only the owner speaks; owner miss = owner events never confirmed; confirm = first accepted hop end − owner onset; EER from all judged hop scores; zero-FA thr. = lowest swept threshold with no false accept at all (hops, events, noise). Definitions: `docs/SPEAKER_BENCHMARK.md`.
