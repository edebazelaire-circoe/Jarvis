# Third-party boundary

`third_party/LOCK.json` is the source of truth for upstream revisions used by Jarvis V1.
The runtime components are intentionally kept outside the `jarvis/` Python package:

- **Barehands** — AGPL-3.0-or-later, pinned source snapshot, locally hardened for Jarvis.
- **ai-visualizer** — AGPL-3.0-or-later, pinned source snapshot, unmodified runtime consumer of Jarvis' file signal bus.
- **Three.js 0.160.0** — MIT, vendored into the Barehands snapshot.
- **MediaPipe Tasks Vision 0.10.14** and the hand-landmarker model — Apache-2.0, vendored into the Barehands snapshot.

`fullstack-agent`, `backtalk`, and `ai-memory-vault` are reference-only: Jarvis does not import or execute them.

## Speaker verification (Solo Owner)

Not vendored and not in `LOCK.json`: nothing here is committed, and none of it is fetched by `bootstrap_third_party.py`. The pins live in code and the artifacts stay in the git-ignored `runtime/`.

- **sherpa-onnx** — Apache-2.0, a prebuilt PyPI wheel (`sherpa-onnx>=1.13.8,<2`, measured at 1.13.8) declared by the optional `speaker` extra of `pyproject.toml`; it bundles its own ONNX runtime. Source and licence: <https://github.com/k2-fsa/sherpa-onnx>.
- **Speaker-embedding model weights** — the eight `.onnx` exports listed in [`docs/SPEAKER_BENCHMARK.md`](../docs/SPEAKER_BENCHMARK.md) § "Engines and adapter slots", downloaded on demand from the sherpa-onnx `speaker-recongition-models` release into `runtime/speaker-verification/models/` (git-ignored) and verified against the SHA-256 pinned in `jarvis/adapters/sherpa_model_catalog.py` **before** installation; a mismatch raises `speaker_model_mismatch` and installs nothing.
  - Seven 3D-Speaker models (CAM++ and ERes2Net families) — **Apache-2.0**, licence read from the ModelScope API on 2026-09-11 (`license_source` is recorded per engine in every benchmark result file).
  - `wespeaker_en_voxceleb_resnet34` — **CC-BY-4.0**, the licence of the VoxCeleb corpus per WeSpeaker `docs/pretrained.md`: **attribution is required** if this model is shipped or its outputs published. It is not the production default (the baseline is the Apache-2.0 CAM++ zh/en advanced) and is only ever loaded by the benchmark.
- **The owner's voiceprint** is neither third-party nor committed: it is derived locally, stays under the git-ignored `runtime/`, and never appears in a payload, a log or a result file.

Run `python scripts/bootstrap_third_party.py` once on a networked workstation. It downloads exact immutable/pinned inputs, verifies critical upstream Git blob IDs and package/model integrity, applies the small Barehands security patch, and writes `INSTALL-STATE.json` with resulting hashes. After that bootstrap, the Barehands camera page has no CDN/model runtime dependency.

Do not remove upstream `LICENSE`, copyright, or provenance files. AGPL obligations can depend on how you distribute or operate modified versions; obtain legal review before embedding these components into a closed-source distribution.
