# Speaker-verification benchmark (Solo Owner, Task 09)

Repeatable, engine-neutral comparison of speaker-verification engines on identical
audio (decision D12: the engine, threshold and evidence window are chosen from
measurements, not vendor claims). Task 14 used it to raise one production default
(`owner_threshold` 0.5 → 0.6, provisional) and to keep the others; the real
workstation data that settles them is collected with `docs/HARDWARE_ACCEPTANCE.md`.

| Piece | File |
| --- | --- |
| Command line | `scripts/benchmark_speaker_verification.py` (`python -m jarvis.runtime.speaker_benchmark` is equivalent) |
| Labelling, replay, metrics, engine protocol (engine-neutral) | `jarvis/audio/speaker_benchmark.py` |
| Manifest, engine resolution, RAM/CPU, JSON/CSV/Markdown output | `jarvis/runtime/speaker_benchmark.py` |
| Synthetic TTS fixtures (generated at runtime, never committed) | `jarvis/runtime/speaker_benchmark_fixtures.py` |
| Pinned sherpa-onnx model catalog | `jarvis/adapters/sherpa_model_catalog.py` |
| Example manifest for real recordings | `docs/speaker-benchmark-manifest.example.json` |
| Tests | `tests/unit/test_speaker_benchmark.py` |
| Published results (non-sensitive) | `docs/results/speaker-benchmark/` |
| Figures quoted by the docs, re-derived from those results | `scripts/speaker_benchmark_figures.py` (guard: `tests/unit/test_published_benchmark_figures.py`) |

## Quick start

```powershell
# 1. models (SHA-256 checked, stored in the ignored runtime/speaker-verification/models/)
.\.venv\Scripts\python.exe scripts\benchmark_speaker_verification.py models                 # list + presence
.\.venv\Scripts\python.exe scripts\benchmark_speaker_verification.py models --download all   # or --download <key>

# 2. synthetic fixtures (Windows TTS) -> runtime/speaker-verification/benchmark/synthetic/manifest.json
.\.venv\Scripts\python.exe scripts\benchmark_speaker_verification.py generate-synthetic

# 3. run every downloaded model on the same audio
.\.venv\Scripts\python.exe scripts\benchmark_speaker_verification.py run `
    runtime\speaker-verification\benchmark\synthetic\manifest.json --sherpa-model downloaded
```

`run` prints the Markdown summary and writes `<basename>.json`, `.csv` and `.md` to
`--out-dir` (default `runtime/speaker-verification/benchmark/results/`, basename
`<date>-<manifest name>`). Exit code: 0 all engines ran, 1 at least one engine is
`unavailable` or `error` (reported, never faked), 2 manifest / usage error (stable
`[code]` on stderr).

Useful `run` options:

| Option | Effect |
| --- | --- |
| `--gate-thresholds 0.5,0.6,0.65` / `none` | thresholds of the Solo Owner **gate replay** (default: the swept thresholds; `none` skips it) |
| `--short-evidence-ms N` (`0` disables), `--short-margin X`, `--owner-buffer-ms N` | override the production short-reply / handover / replay-buffer settings for every engine |
| `--sherpa-model KEY` (repeatable), `downloaded`, `all` | add catalog models as engines (missing files are reported `unavailable` with the download command) |
| `--engine NAME` (repeatable) | keep only these engines |
| `--thresholds 0.4,0.5,0.6` / `--threshold-range 0.30:0.80:0.025` | sweep (overrides the manifest's `thresholds`; default 0.05…0.95 step 0.05) |
| `--threshold T` | override every engine's own decision threshold |
| `--evidence-ms 1000,1500,2000` | one engine variant per evidence window (`name@ev1000`, …) |
| `--transition-guard-ms N` | scoring only: exclude hops whose last N ms straddle a label change (overrides the manifest; 0 = strict) |
| `--realtime` | feed hops at real-time cadence (default: accelerated offline) and report the lag |
| `--include-hops` | keep per-hop `[start_ms, class, status, score, detected, evidence_ms]` in the JSON |
| `--no-isolate` | run all engines in one process (default: one fresh process per engine, so RSS and load time are not polluted by the previous engine; each child gets a timeout derived from the audio and the number of replay passes — `speaker_benchmark.isolated_timeout_s`, 300 s + 2 × audio per pass — and a child that overruns it is killed and reported `error / engine_subprocess_failed`, never silently awaited) |
| `--ablation`, `--capture-rate N` | allow a preprocessing change (global or per engine); the result is flagged `ablation: true` |
| `--model-dir DIR`, `--out-dir DIR`, `--basename NAME`, `--quiet` | paths / output |

## Manifest (schema `jarvis.speaker_benchmark.manifest` v1, JSON or TOML)

See `docs/speaker-benchmark-manifest.example.json`. Relative paths are relative to
the manifest; keys starting with `_` are comments; unknown keys are rejected (typos
never pass silently).

- `evidence`: `real` (default) or `synthetic` (adds the "not evidence" disclaimer).
- `profiles.<id>.enroll`: WAV files enrolled for that owner profile, exactly like
  `jarvis owner-voice enroll --wav` (energy gate, ≥ 10 s voiced, 3 s segments).
- `engines[]`: `kind` `sherpa-onnx` (`model` = catalog key) or `factory`
  (`factory: "module:function"`, `options`), plus `threshold`, `evidence_ms`,
  `stride_ms`, `max_gap_ms`, `short_evidence_ms`, `short_margin`,
  `owner_buffer_ms`, `num_threads`. Defaults = production (engine threshold —
  0.6 since Task 14 —, 1500, 500, 600, 600, 0.1, 2500, 1).
- `scenarios[]`: `name`, `profile`, `audio` (PCM WAV, any rate / channels),
  optional `gain_db` (level / distance variation of the same recording), `tags`,
  `sha256` (checked before running), and either `intervals`
  (`[{start_ms, end_ms, label, speaker?}]`) or `labels` (an Audacity label track
  export: `start<TAB>end<TAB>label[:speaker]` in seconds).
- Labels: `owner`, `non_owner`, `overlap` (both at once, when speakers are not
  annotated separately), `noise` (no speech: any acceptance is a false one),
  `silence`. Overlapping `owner` and `non_owner` intervals are an overlap too.
  Unlabelled time is `silence` and is ignored by the rates. Label `noise` only where
  an acceptance would really be wrong (not the second after owner speech, where the
  previous verdict legitimately lingers).
- `evaluation`: `confirm_grace_ms` (200), `transition_guard_ms` (0 = strict),
  `min_label_coverage` (0.5), `event_merge_gap_ms` (1000).

**Private recordings never go to Git.** Put owner / office recordings, their labels
and the manifest under `runtime/speaker-verification/benchmark/private/` (ignored:
`/runtime/` and `speaker-verification/` are in `.gitignore`), and publish only the
result files, which contain scores, timings and metadata — never audio or voiceprints.
Manifest paths may point anywhere; outside the repository only the file name is
recorded in the result.

## What is replayed (identical for every engine)

WAV → mono float → `gain_db` → FFT resampling to `capture_rate` (24 kHz, the Voice
capture rate) → int16 PCM → contiguous 100 ms hops → `SpeakerVerifier.process()`
(the production port), `reset()` at the start of each scenario (= new voice session).
Embedding engines run through the production `EmbeddingSpeakerVerifier` (same energy
gate, sliding evidence window, stride, gap reset, cosine score); only the embedder
changes. The effective preprocessing is recorded in every result. Not modelled
offline: AEC, far-end echo, noise reduction, the capture worker's queue.

## Metric definitions

Every hop is classified from the labels: `overlap` (owner and another voice both
cover ≥ 50 % of the hop) > `owner` / `non_owner` (≥ 50 %, tie → owner) > `noise` >
`silence`. A hop is *judged* when the verifier returns `status = ok`; it is
*accepted* when judged and `owner_score ≥ threshold` (sweep), or when
`owner_detected` is true (engine decision, block `at_engine_threshold`).

| Metric | Definition |
| --- | --- |
| `far` | accepted / judged hops of class `non_owner` |
| `frr` | rejected / judged hops of class `owner` |
| `owner_judged_ratio` | judged / all owner hops (hops still gathering evidence are not judged) |
| `overlap_accept_rate` | accepted / judged overlap hops (owner present: higher = better barge-in) |
| `noise_hops_accepted` | accepted hops of class `noise` (must be 0) |
| owner event | merged `owner` ∪ `overlap` intervals (gaps ≤ `event_merge_gap_ms` merged); `overlapped` if another voice speaks during it |
| `owner_miss_rate` | owner events with no accepted hop ending in ]onset, end + `confirm_grace_ms`] |
| `confirm_ms_p50/p95/max` | first accepted hop end − event onset (hop-quantized), over confirmed events; same for overlapped events |
| `false_accept_event_rate` | non-owner events (merged `non_owner` intervals with ≥ 1 eligible hop) containing ≥ 1 accepted `non_owner` hop |
| `excluded_hops` | hops dropped from hop rates because a label boundary lies within the last `transition_guard_ms` of audio |
| `eer` | equal error rate from all judged owner vs non-owner hop scores (threshold-free: observed scores as candidates, linear interpolation at the FAR/FRR crossing) |
| `operating_points.zero_false_accept` | lowest swept threshold with no false accept at all (hops, events, noise), with its FRR, miss rate and confirmation latency |
| Percentiles | linear interpolation between ranks (NumPy default) |

Resources (`resources`): `model_verify_ms` (SHA-256 check), `model_load_ms`,
`enroll_ms_total`; process RSS before load / after load / after the run and the
deltas (`GetProcessMemoryInfo` on Windows, `/proc/self/statm` on Linux; best effort);
`hop_ms` (wall time of every `process()` call) and `scoring_hop_ms` (hops where an
embedding was computed; single ONNX thread, so wall ≈ CPU); `cpu_ms_total` (process
CPU time, accurate in aggregate only — Windows ticks are 15.6 ms), per hop, per
scoring hop, and `cpu_pct_one_core` = CPU / audio duration; `realtime_lag_ms` in
`--realtime` mode.

The sweep re-applies thresholds to the recorded scores of a single replay: valid for
every engine whose score does not depend on its own threshold (true for
`EmbeddingSpeakerVerifier`). An engine whose scoring depends on its threshold must be
run once per threshold (`--threshold`). Since Task 14 the hop score used by the sweep
and the EER is the **full evidence window** score (`window_score`), taken before the
handover sub-window rule of Task 07 lowers it: hop rates therefore keep measuring pure
speaker discrimination, while the engine's own decision (`at_engine_threshold`) and the
gate block below include every production rule.

## Solo Owner gate replay (what the provider would really receive)

Hop rates describe the verifier. They do **not** describe Solo Owner: the input gate
also involves the acoustic candidate of `NearEndDetector` (Task 04), the
end-of-candidate verdict for short replies and the handover sub-window (Task 07), and
the owner replay ring (Task 06). The harness therefore replays every scenario a second
time through those real components — `CaptureProcessor`, `SpeakerVerificationWorker`,
`ShadowOwnerTelemetry` — with the bridge's role (open the flow on confirmation, close
it on a stranger verdict or at the end of the candidate) played by the harness, JARVIS
silent. The result is the exact set of input intervals the provider would have
received, per threshold (`--gate-thresholds`).

| Metric | Definition |
| --- | --- |
| `owner_events_forwarded` / `owner_gate_miss_rate` | owner events (same merge rule as above) with, or without, forwarded audio |
| `gate_confirm_ms_p50/p95/max` | owner-event onset → confirmation that opened the flow |
| `short_confirmations` | flow openings decided at the end of a candidate (short replies) |
| `owner_start_lost_ms_p95/max` | owner speech before the first forwarded millisecond (onset estimate + ring clamping) |
| `owner_forwarded_ratio` | owner-only audio forwarded / owner-only audio |
| `openings`, `false_opens` | flow openings; those whose replayed span holds less than 20 % owner speech |
| `non_owner_events_opened` | non-owner events during which the flow opened |
| `non_owner_forwarded_ms`, `non_owner_run_ms_max`, `non_owner_forwarded_ratio` | colleague-only audio that reached the provider (handover leak), total, longest single run, share |
| `noise_forwarded_ms` | noise-only audio forwarded (must be 0) |
| `replays_clamped`, `clamped_ms_max` | replays the ring could not cover (`owner_buffer_ms` too small) |
| `drops`, `drops_short_not_owner` | candidates closed without ever being recognized (`voice.input.non_owner_dropped`) |
| `operating_points.gate_zero_false_open` | lowest gate threshold with **no false open at all**. `non_owner_events_opened` is informational (it also counts legitimate owner confirmations during an overlap) and noise forwarded inside an owner turn is not a false accept — `noise_hops_accepted` answers "was noise alone ever taken for the owner?" |

Not modelled offline: AEC and far-end echo (JARVIS is silent in the gate replay), the
capture worker's queue overflow, and the provider's own turn segmentation. Embeddings
are memoized between gate thresholds (identical audio), so gate numbers cost almost
nothing after the first threshold — and the cost figures in `resources` come from the
first replay only, without that cache.

## Result schema (`jarvis.speaker_benchmark.result` v2)

Top level: `schema`, `schema_version`, `generated_at`, `evidence`, `disclaimer`,
`mode`, `ablation`, `manifest` (name, path, SHA-256, counts, audio duration), `host`,
`preprocessing`, `evaluation`, `thresholds`, `engines`. Each engine: `name`,
`status` (`ok` / `unavailable` / `error`), `code`, `message`, `engine` (id, library,
version, model id / file / SHA-256 / size / license + source / card / URL, dim, sample
rate, threads), `verifier` (threshold, evidence, stride, gap, short-reply window and
margin, owner buffer), `preprocessing`, `ablation`, `resources`, `enrollment`
(voiced ms, segments, consistency — never the voiceprint), `at_engine_threshold`,
`sweep`, `eer`, `operating_points` (`zero_false_accept`, `gate_zero_false_open`),
`gate_at_engine_threshold`, `gate_sweep`, `scenarios` (per-scenario compact metrics +
score min / mean / max + its `gate` block). Unavailable engines keep every key
(null / empty). The CSV has one row per (engine, decision): `decision = engine` (own
threshold), one `sweep` row per threshold, then one `gate` row per gate threshold;
columns are fixed (`CSV_COLUMNS`). Any key removed, added or
redefined bumps `schema_version` (v2 = Task 14: gate blocks and verifier fields);
`tests/unit/test_speaker_benchmark.py` freezes the key lists.

## Reading the results and choosing (Task 14)

0. **Decide on the gate block, not on the hop rates.** `gate_sweep` /
   `operating_points.gate_zero_false_open` describe what the provider would receive
   with every production rule applied; the hop rates below describe the verifier alone
   and stay the tiebreaker. The full procedure, including how to record the material,
   is `docs/HARDWARE_ACCEPTANCE.md` §5.
1. Only `evidence: real` runs count. Check `enrollment.consistency` (≥ 0.8 expected on
   a clean enrollment) and that every engine ran with the same `preprocessing`.
2. Safety first (D07): for each engine, take `operating_points.zero_false_accept` —
   the lowest threshold without any false acceptance on office speech and noise —
   then add a margin (e.g. +0.05, or the next sweep step whose `non_owner_score_max`
   per scenario stays clearly below it). Reject an engine whose zero-FA threshold
   costs an owner miss rate above what the barge-in UX accepts.
3. At that threshold compare `owner_miss_rate`, `confirm_ms_p95` (the owner ring
   buffer, Task 06, must cover it), `overlap_events_confirmed`, then `eer` as a
   threshold-free tiebreaker, then cost (`scoring_hop_ms.p95` well under the 100 ms
   hop, `cpu_pct_one_core`, `model_load_ms`, RSS).
4. Evidence window: re-run with `--evidence-ms 1000,1500,2000,2500`; a longer window
   usually lowers FAR/EER but raises `confirm_ms_*` by about the same amount.
   Keep the shortest window that holds zero FA with margin. Run once with
   `--realtime` to confirm `realtime_lag_ms.max` stays low on the target machine.
5. Transitions: strict scoring (`transition_guard_ms: 0`) counts the ~evidence-window
   lag after a speaker change as errors — this is what the input gate will actually
   see. A second run with `transition_guard_ms` = evidence window isolates pure
   speaker discrimination.
6. A commercial engine is justified only if it clearly beats the local one on these
   numbers (06-provider-benchmark-plan). Record the chosen engine / threshold /
   window with the result file in the Task 14 report.

## Synthetic fixtures

`generate-synthetic` (Windows only) lists the installed voices through PowerShell —
OneCore voices via WinRT, plus SAPI voices OneCore does not have (the SAPI "Hortense
Desktop" and OneCore "Hortense" are the same speaker and counted once) — synthesizes
an enrollment paragraph for the owners and eight French test sentences per voice
(varied speaking rate), then mixes 13 scenarios per owner, rotating the French voices
as owner (`--owners 3`) with every other voice as impostor. Options: `--voices
hortense,paul`, `--only owner_alone,overlap_2s`, `--seed`, `--out`. WAVs and the
manifest (with SHA-256 per scenario) go to `runtime/speaker-verification/benchmark/synthetic/`;
TTS files are cached by a hash of voice + text + rate.

| Scenario | Content |
| --- | --- |
| `owner_alone` | two owner sentences separated by 2 s of silence |
| `owner_quiet` | same, owner 12 dB quieter |
| `owner_far` | owner 18 dB quieter + synthetic room reverberation |
| `non_owner_conversation` | three non-owners take turns (200–300 ms gaps), no owner |
| `non_owner_far` | one non-owner 12 dB quieter + reverberation |
| `non_owner_then_owner` | owner answers immediately after a non-owner |
| `owner_then_non_owner` | a non-owner speaks immediately after the owner |
| `overlap_1s` / `_2s` / `_3s` | owner starts 1–3 s before the end of a non-owner sentence (mixed) and continues alone |
| `keyboard_desk` | typing bursts and desk impacts over a −62 dBFS floor (all `noise`) |
| `owner_with_keyboard` | typing alone (`noise`), then typing under owner speech |
| `low_noise` | −50 dBFS pink noise throughout; noise-only part, owner, then a non-owner |

**Synthetic TTS voices are not evidence for production thresholds.** They are
cleaner and more separable than real people; two voices of the same TTS family and
language can also be abnormally close. Headset / laptop-speaker paths, JARVIS echo at
several volumes and real office chatter (docs 04, scenarios 2, 3, 8–10) need real
recordings (Task 14).

## Engines and adapter slots

An engine enters the benchmark without touching the harness:

- **Embedding engine** (most local engines): implement `SpeakerEmbedder`
  (`model_id`, `dim`, `sample_rate`, `embed(float32 samples) -> vector`, optional
  `load` / `close`) in `jarvis/adapters/`, and a factory
  `create(options, *, model_dir, num_threads) -> EmbeddingBenchmarkEngine(embedder,
  engine_id="name/version", description={...}, verify=...)`. It then runs through the
  production `EmbeddingSpeakerVerifier`.
- **Native verifier** (commercial SDKs with their own enrollment and scores):
  implement `BenchmarkEngine` (`describe`, `verify`, `load`, `enroll(clips) ->
  (reference, metadata)`, `open_verifier(reference, profile_id, params,
  preprocessing) -> SpeakerVerifier`, `close`); the verifier must normalize scores to
  [0, 1] and set `owner_detected` from `params.threshold`.
- Reference it from a manifest: `{"name": "...", "kind": "factory", "factory":
  "jarvis.adapters.<module>:create", "options": {...}}`. Import errors → `unavailable
  / engine_not_installed`.

Catalog (`models` subcommand), all 16 kHz sherpa-onnx exports from the
`speaker-recongition-models` release, SHA-256 pinned from its `checksum.txt`,
weights licenses verified on 2026-09-11 (ModelScope API for 3D-Speaker, WeSpeaker
`docs/pretrained.md`):

| Key | Model | Dim | License | SHA-256 (`jarvis/adapters/sherpa_model_catalog.py`) | Bytes |
| --- | --- | --- | --- | --- | --- |
| `campplus-zh-en-advanced` | 3D-Speaker CAM++ zh/en advanced (**production baseline**, Task 03) | 192 | Apache-2.0 | `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2` | 28 281 164 |
| `campplus-zh-cn-common` | 3D-Speaker CAM++ zh-cn common | 192 | Apache-2.0 | `f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1faedccd21fd11` | 28 281 138 |
| `campplus-en-voxceleb` | 3D-Speaker CAM++ VoxCeleb (rejected by Task 03) | 512 | Apache-2.0 | `357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b` | 29 596 978 |
| `eres2net-en-voxceleb` | 3D-Speaker ERes2Net VoxCeleb | 192 | Apache-2.0 | `c59158379255ad66e161679cca6af8d52d51e389e3224ab7d7a7baae295c2db5` | 26 485 263 |
| `eres2net-base-200k-zh-cn` | 3D-Speaker ERes2Net base 200k zh-cn | 512 | Apache-2.0 | `e2d2048292e055f7b61cdec3db010503f35369b245bf0b3bbad021c9a91e4053` | 39 593 765 |
| `eres2net-base-3dspeaker` | 3D-Speaker ERes2Net base (3D-Speaker set) | 512 | Apache-2.0 | `1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b` | 39 593 761 |
| `eres2netv2-zh-cn` | 3D-Speaker ERes2NetV2 zh-cn common | 192 | Apache-2.0 | `bf1a75b9930474cf3389ef415e6e5d38ca96fea4a3a00f7e301d080a58ee2239` | 71 441 526 |
| `wespeaker-resnet34-en-voxceleb` | WeSpeaker ResNet34 VoxCeleb | 256 | CC-BY-4.0 (attribution) | `5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94` | 26 534 365 |

The single source of truth for these hashes and sizes is
`jarvis/adapters/sherpa_model_catalog.py` (`MODELS`);
`tests/unit/test_speaker_benchmark.py::test_the_catalog_table_of_the_docs_matches_the_code`
fails if this page and the module ever diverge. The `models` subcommand lists the
same keys, dims, sizes and licences (without the hashes). The weights themselves are never
committed: they are downloaded into the git-ignored
`runtime/speaker-verification/models/`, checked against these hashes before being
installed, and recorded in `third_party/README.md` (§ « Speaker verification »).

Not in the catalog (large, 116–220 MB): `eres2net_large_…_3dspeaker`,
`eres2net_sv_zh-cn_16k-common`; adding one is a `SherpaModelSpec` line.

Slots left open (not installable or not accessible here — no results are claimed):

| Engine | What to implement | Where | Blocker on 2026-09-11 |
| --- | --- | --- | --- |
| Picovoice Eagle | native `BenchmarkEngine`: `EagleProfiler` enrollment (resample to 16 kHz, `frame_length` frames), `Eagle.process` scores → `SpeakerVerification` | `jarvis/adapters/eagle_speaker_benchmark.py:create_engine` (the name used in the example manifest) | `pveagle` not installed; needs a Picovoice access key and license terms review |
| SpeechBrain ECAPA | `SpeakerEmbedder` around `EncoderClassifier` (`speechbrain/spkrec-ecapa-voxceleb`) | `jarvis/adapters/speechbrain_speaker_embedder.py` + factory | requires PyTorch (heavy dependency, not installed) |
| Vivoka voice biometrics | native `BenchmarkEngine` over the SDK | `jarvis/adapters/vivoka_speaker_benchmark.py` | SDK under trial / commercial agreement |
| Sensory speaker verification | native `BenchmarkEngine` over the SDK | `jarvis/adapters/sensory_speaker_benchmark.py` | SDK under commercial agreement |

## Latest results

See `docs/results/speaker-benchmark/` (JSON + CSV + Markdown per run). Latest:
`2026-09-12-synthetic*` (schema v2, with the Solo Owner gate block) — synthetic
TTS voices, the basis of the provisional defaults; the real-voice run is the one
`docs/HARDWARE_ACCEPTANCE.md` produces.
