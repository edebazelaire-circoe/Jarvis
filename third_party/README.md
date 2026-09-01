# Third-party boundary

`third_party/LOCK.json` is the source of truth for upstream revisions used by Jarvis V1.
The runtime components are intentionally kept outside the `jarvis/` Python package:

- **Barehands** — AGPL-3.0-or-later, pinned source snapshot, locally hardened for Jarvis.
- **ai-visualizer** — AGPL-3.0-or-later, pinned source snapshot, unmodified runtime consumer of Jarvis' file signal bus.
- **Three.js 0.160.0** — MIT, vendored into the Barehands snapshot.
- **MediaPipe Tasks Vision 0.10.14** and the hand-landmarker model — Apache-2.0, vendored into the Barehands snapshot.

`fullstack-agent`, `backtalk`, and `ai-memory-vault` are reference-only: Jarvis does not import or execute them.

Run `python scripts/bootstrap_third_party.py` once on a networked workstation. It downloads exact immutable/pinned inputs, verifies critical upstream Git blob IDs and package/model integrity, applies the small Barehands security patch, and writes `INSTALL-STATE.json` with resulting hashes. After that bootstrap, the Barehands camera page has no CDN/model runtime dependency.

Do not remove upstream `LICENSE`, copyright, or provenance files. AGPL obligations can depend on how you distribute or operate modified versions; obtain legal review before embedding these components into a closed-source distribution.
