# Slice 06 — Windows private runtime packaging

## Goal
Create the production package model for Windows so Jarvis Presentation Edition does not depend on Git, system Python, system Node/npm or a user-installed FFmpeg/codecs, while preserving pinned/integrity-checked Remotion behavior.

## Context
`setup.ps1` currently creates a `.venv`, installs editable Python dependencies and expects a working Python. The Remotion local capability pins packages and verifies Node/npm but deliberately does not install Node. Capture uses a pinned `imageio-ffmpeg` binary path. A distributed product needs a controlled runtime and license manifest.

## Canonical Concepts
- Python project dependencies: `pyproject.toml`;
- developer bootstrap: `setup.ps1`;
- local capabilities/Remotion: `docs/local-capabilities.md`, `docs/remotion-runtime.md`;
- capture/FFmpeg docs;
- product AppData root from Slice 02.

## Scope
### In Scope
- choose/document production packaging strategy and install layout;
- ship/manage a private pinned Python runtime or equivalent frozen runtime;
- ship/manage a private pinned Node/npm runtime used by Remotion instead of PATH lookup;
- ship/use the pinned FFmpeg needed by capture/render paths;
- keep Remotion package-lock/integrity checks and local-capability isolation;
- produce a dependency/license/notice manifest suitable for distribution;
- explicitly resolve components/models whose license is incompatible with intended V1 distribution;
- keep developer setup path separate unless intentionally unified.

### Out of Scope
- no framework rewrite;
- no macOS/Linux packages;
- no automatic updater yet beyond package metadata needed by Slice 10.

## Dependencies
Hard `depends_on`: `01-product-edition-and-board-lock`, `02-windows-data-root-context-global`, `03-internal-documents-and-export-boundary`, `04-agent-confinement-capability-policy`.

## Implementation Steps
1. Audit native wheels/binaries and external executables required by the V1 feature manifest.
2. Select production packaging technology based on actual Python/native dependency compatibility; record tradeoffs and reproducible build steps.
3. Define install layout under Program Files (or chosen per-user application location) separate from AppData.
4. Pin private Python runtime and dependency set; ensure no editable install or repository checkout at runtime.
5. Pin private Node/npm runtime and update Remotion capability runner to resolve this owned runtime in product mode. Keep dev PATH behavior only for development mode if useful.
6. Make FFmpeg/codecs resolve from owned packaged/runtime paths; verify licensing notices and executable integrity.
7. Build a third-party manifest: name, version, source, license, distribution status, hash/build provenance.
8. Resolve wake-word model licensing: do not ship/use the repository-documented non-commercial openWakeWord model in a commercial/distributed V1 unless a compatible license/model is chosen. Product may fall back to F9/another allowed wake path until resolved.
9. Decide whether legacy third-party Barehands/visualizer processes are needed in Presentation Edition. Exclude developer/legacy components not required by the product feature manifest.
10. Produce a deterministic package build and a machine-readable runtime manifest consumed by health/readiness.

## Files Likely Touched
- packaging/build scripts and manifests;
- `pyproject.toml`/lock strategy as needed;
- Remotion capability runner/runtime resolution;
- capture/FFmpeg runtime resolution;
- product launcher/bootstrap;
- license/third-party documentation.

## Architecture Constraints
- program binaries are replaceable; AppData user state is not part of the package payload;
- product runtime must not rely on PATH-installed developer tools;
- private runtimes must be pinned, integrity-checkable and diagnosable;
- do not silently redistribute incompatible third-party assets/models.

## Automated Validation
- package build reproducibility checks;
- runtime probes with PATH stripped of Python/Node/FFmpeg;
- Remotion install/health/render tests against private Node;
- capture/render tests against packaged FFmpeg;
- dependency manifest completeness test;
- clean temp-profile smoke without repository checkout.

## Acceptance Criteria
- package starts and exercises core Presentation paths with Git/Python/Node/FFmpeg absent from system PATH;
- Remotion still installs/repairs deterministically from pinned inputs;
- incompatible third-party assets are excluded or replaced explicitly;
- install binaries and user data have separate roots.

## Documentation Updates
Create Level 3 Windows production packaging/runtime contract and third-party manifest.

## Handoff Notes
Coding Slice: `/caveman`, `/coding-guideline`. QA: `qa-verification`, `code-review`, `runtime-validation`. Any unresolved licensing uncertainty is a release blocker, not an Issue to ignore.

## Slice 00 amendments (2026-10-26)
- E4: the brain is the **Claude Code CLI** (Codex optional). Pin and provision it privately, or record the decision, together with its terms of use for distribution. Authentication by a non-developer user is handled in Slice 07.
- E5: Remotion rendering uses the installed Chrome/Edge (`jarvis/adapters/remotion_render_runner.py:102-105,159`). Either accept it as a system dependency (Edge is present on Windows 10/11) or ship a private browser. Make it diagnosable.
- E6, release gates: the Remotion licence (`jarvis/domain/remotion_upstream.py:51`, "company licence may be required"), FFmpeg GPLv3 from `imageio-ffmpeg`, Barehands and ai-visualizer AGPL-3.0 (recommendation: exclude them from the Presentation package), and openWakeWord CC BY-NC-SA 4.0.
- Presentation FFmpeg already comes from Remotion's compositor (`jarvis/adapters/remotion_media_tools.py:1-5`); only screen capture uses `imageio-ffmpeg`.
