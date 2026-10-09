# Third-party boundary

`third_party/LOCK.json` is the source of truth for upstream revisions used by Jarvis V1.
The runtime components are intentionally kept outside the `jarvis/` Python package:

- **Barehands** — AGPL-3.0-or-later, pinned source snapshot, locally hardened for Jarvis.
- **ai-visualizer** — AGPL-3.0-or-later, pinned source snapshot, unmodified runtime consumer of Jarvis' file signal bus.
- **Three.js 0.160.0** — MIT, vendored into the Barehands snapshot.
- **MediaPipe Tasks Vision 0.10.14** and the hand-landmarker model — Apache-2.0, vendored into the Barehands snapshot. The Control Center also serves a whitelist of these files (`/barehands/assets/…`) to its own "Barehands (mode test)" hand pointer; that pointer is an original reimplementation and copies no Barehands (AGPL) code. See `docs/OPERATIONS.md`, "Expérimental : Barehands en mode test".

`fullstack-agent`, `backtalk`, and `ai-memory-vault` are reference-only: Jarvis does not import or execute them.

## Speaker verification (Solo Owner)

Not vendored and not in `LOCK.json`: nothing here is committed, and none of it is fetched by `bootstrap_third_party.py`. The pins live in code and the artifacts stay in the git-ignored `runtime/`.

- **sherpa-onnx** — Apache-2.0, a prebuilt PyPI wheel (`sherpa-onnx>=1.13.8,<2`, measured at 1.13.8) declared by the optional `speaker` extra of `pyproject.toml`; it bundles its own ONNX runtime. Source and licence: <https://github.com/k2-fsa/sherpa-onnx>.
- **Speaker-embedding model weights** — the eight `.onnx` exports listed in [`docs/SPEAKER_BENCHMARK.md`](../docs/SPEAKER_BENCHMARK.md) § "Engines and adapter slots", downloaded on demand from the sherpa-onnx `speaker-recongition-models` release into `runtime/speaker-verification/models/` (git-ignored) and verified against the SHA-256 pinned in `jarvis/adapters/sherpa_model_catalog.py` **before** installation; a mismatch raises `speaker_model_mismatch` and installs nothing.
  - Seven 3D-Speaker models (CAM++ and ERes2Net families) — **Apache-2.0**, licence read from the ModelScope API on 2026-09-11 (`license_source` is recorded per engine in every benchmark result file).
  - `wespeaker_en_voxceleb_resnet34` — **CC-BY-4.0**, the licence of the VoxCeleb corpus per WeSpeaker `docs/pretrained.md`: **attribution is required** if this model is shipped or its outputs published. It is not the production default (the baseline is the Apache-2.0 CAM++ zh/en advanced) and is only ever loaded by the benchmark.
- **The owner's voiceprint** is neither third-party nor committed: it is derived locally, stays under the git-ignored `runtime/`, and never appears in a payload, a log or a result file.

## Wake word (openWakeWord)

Not vendored and not in `LOCK.json`: nothing here is committed, and none of it is fetched by `bootstrap_third_party.py`. The pins live in code and the artifacts stay in the git-ignored `runtime/`.

- **openwakeword** — Apache-2.0, a pure-Python PyPI wheel (`openwakeword>=0.6,<0.7`, measured at 0.6.0 on Python 3.14.6) declared by the optional `wakeword` extra of `pyproject.toml`, together with `onnxruntime>=1.30,<2` (measured 1.30.0) and `numpy`. It also pulls `scipy` and `scikit-learn` (about 160 MiB installed in total with onnxruntime). On Windows the ONNX runtime is used; `tflite-runtime` is required only on Linux and is not used by Jarvis. Source and licence: <https://github.com/dscripka/openWakeWord>.
- **Pre-trained models** — `melspectrogram.onnx`, `embedding_model.onnx` and `hey_jarvis_v0.1.onnx` from the upstream `v0.5.1` release, downloaded on explicit request into `runtime/wake-word/models/` (git-ignored) and verified against the size and SHA-256 pinned in `jarvis/adapters/wakeword_model_catalog.py` **before** installation; a mismatch raises `wake_model_mismatch` and installs nothing. No `.onnx` or `.tflite` file is ever committed.
- **Licence of the models: CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International). Verified at the source on 2026-10-07: the upstream `README.md` (default branch), section "License", states that all repository code is Apache-2.0 and that "all of the included pre-trained models are licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International license due to the inclusion of datasets with unknown or restrictive licensing as part of the training data" (<https://github.com/dscripka/openWakeWord#license>). The GitHub API reports the repository licence as Apache-2.0 (code only). The embedding backbone derives from a Google model under Apache-2.0 per the same README, but the released files are treated here as CC BY-NC-SA 4.0 like the others. The same licence text is recorded per model in `license_source` of the catalog.
- **Use** — private, non-commercial testing only ("tests privés, non commercial"). Attribution and share-alike apply if the models are redistributed, and Jarvis redistributes none. Do not ship, bundle or pre-install these models in any commercial distribution.
- **Replacement path** — the detector sits behind the `WakeWordEngine` contract (`jarvis/adapters/wakeword_shared_pcm.py`): a custom openWakeWord model trained on permissively licensed data, another local keyword-spotting engine, or Porcupine (with its own Picovoice key and terms) can replace it by editing the catalog pins and the engine factory, without touching the voice runtime. Remove the `wakeword` extra and the `runtime/wake-word/` folder to uninstall. Install, diagnostics and the model replacement procedure: `docs/OPERATIONS.md`, « Installer openWakeWord ».

Run `python scripts/bootstrap_third_party.py` once on a networked workstation. It downloads exact immutable/pinned inputs, verifies critical upstream Git blob IDs and package/model integrity, applies the small Barehands security patch, and writes `INSTALL-STATE.json` with resulting hashes. After that bootstrap, the Barehands camera page has no CDN/model runtime dependency.

Do not remove upstream `LICENSE`, copyright, or provenance files. AGPL obligations can depend on how you distribute or operate modified versions; obtain legal review before embedding these components into a closed-source distribution.
