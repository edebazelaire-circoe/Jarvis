# Windows packaging and private runtimes (contract)

Canonical contract, documentation **Level 3**: vocabulary, contract, one
reusable implementation (build + runtime resolution) and conformance tests.
Handoff `tasks/jarvis-presentation-edition-v1/` (Slice 06). Product home and
install marker: [local-data.md](local-data.md#produit-installé--localappdatacircoejarvis).
Edition: [product-edition.md](product-edition.md).

| What | Code | Proof |
| --- | --- | --- |
| Package layout, tool resolution, child `PATH`, diagnostics, integrity | `jarvis/private_runtime.py` | `tests/unit/test_private_runtime.py` |
| Pinned runtimes (official URL + publisher SHA-256) | `packaging/windows/runtimes.json` | `tests/unit/test_windows_packaging.py` |
| Python dependency set (top level) and hashed lock | `packaging/windows/requirements.in`, `requirements.lock` | same |
| Third-party distribution policy (licence, status, exclusions, external deps) | `packaging/windows/third_party_policy.json` | same; the build refuses any gap |
| Build, verify, lock | `packaging/windows/build_package.py` | same, plus the real build of the Slice 06 LOG |
| Consumers | Node runners (`node_capability_runner.py`, `remotion_render_runner.py`, `remotion_studio_runner.py`: default `which`), `process_tree.clean_env` (child `PATH`), `screen_capture.find_ffmpeg`, Core `/v1/health` › `installation.runtimes` (`app.py`) | same |

## Two modes, one rule

The install marker (`jarvis-product.json`, `jarvis/installation.py`) decides.

- **Development checkout** (no marker): nothing changes. `setup.ps1`, `.venv`,
  `python -m jarvis …`, Node/npm and FFmpeg from the developer's `PATH`.
  `private_runtime.which` is exactly `shutil.which`; `child_path` returns the
  `PATH` unchanged.
- **Installed product** (marker present): the product **never** uses a
  developer tool found on the machine `PATH`. Owned tools (`node`, `npm`,
  `npx`, `python`, `py`, `ffmpeg`, `ffprobe`) resolve **only** inside the
  package, or are absent. A missing private runtime is an installation to
  repair (`private_runtime_missing`), never a reason to look elsewhere. Every
  other name (the Claude Code CLI, a browser on Linux) still resolves on the
  `PATH`: those are declared **external** dependencies.

## Install layout

The program folder is replaceable and holds no user state; user state lives in
`%LOCALAPPDATA%\CIRCOE\Jarvis` (Slice 02). The layout is relative, so the same
package works from any folder (Program Files or a per-user folder, Slice 07
picks; paths with spaces are supported).

```text
<install>\
  app\                    CODE_ROOT: jarvis\ (git archive of the build revision) + jarvis-product.json
  runtime\python\         Python 3.14.6 embeddable (python.org), python314._pth, Lib\site-packages (locked wheels)
  runtime\node\           Node.js 24.21.0 (nodejs.org) with its own npm
  licenses\               licence texts (runtimes, every wheel's dist-info licence files)
  third-party-manifest.json
  runtime-manifest.json   machine-readable runtime manifest (below)
```

Nothing else: no `scripts\`, `tests\`, `docs\`, `third_party\`, `setup.ps1`,
`.venv` or Git metadata.

### The packaged Python

- `python314._pth` lists only package paths: `python314.zip`, `.`,
  `Lib\site-packages` (+ the three pywin32 folders) and `..\..\app`. **No
  `import site`**: the interpreter runs as `-S`, so neither the user site
  (`%APPDATA%\Python\Python314\site-packages`, which on a developer machine
  carries for example `onnxruntime`) nor `.pth` files are read; a `._pth`
  file also makes the interpreter ignore `PYTHONPATH`/`PYTHONHOME` and every
  `PYTHON*` variable (`sys.flags.ignore_environment`). The pywin32
  DLLs are copied next to `python.exe` (what `pywin32.pth` would have done).
- Every `.py` of `app\` and `site-packages\` is precompiled with
  `--invalidation-mode unchecked-hash`: Python never writes `__pycache__` in
  the program folder (I-002 point 1), and the bytecode is identical from one
  build to the next.
- Child processes (MCP servers, routing hook) are launched with
  `sys.executable`, i.e. the packaged `python.exe`; their `*-mcp.json` name it
  (I-002 point 2).

### The private Node

The Remotion local capability (`docs/remotion-runtime.md`) runs `npm ci` with
`node npm-cli.js` next to the resolved Node, so in the product both come from
`runtime\node`. `process_tree.clean_env` puts `runtime\node` first in every
child's `PATH`, so any `node` looked up by npm or Remotion is the private one.
The Remotion npm packages themselves are **not** in the package: they are
installed on demand into `%LOCALAPPDATA%\CIRCOE\Jarvis\data\local_capabilities\remotion\runtime`
from the shipped lock (sha512 integrity), unchanged.

### FFmpeg

- Remotion renders use the FFmpeg of its own compositor npm package (fetched
  by `npm ci`, `jarvis/adapters/remotion_media_tools.py`): nothing to ship.
- Screen recording uses `imageio-ffmpeg` (FFmpeg GPLv3). The `presentation`
  package **excludes** it (decision HV-PACKAGE-03): `find_ffmpeg` returns the
  package's own `runtime\ffmpeg\ffmpeg.exe` only when the runtime manifest
  declares an `ffmpeg` runtime, so recording is refused `source_unavailable`
  and screenshots still work. `JARVIS_FFMPEG_EXE` remains an explicit
  administrator override.

## Runtime manifest (`runtime-manifest.json`)

Schema `jarvis.runtime-manifest` v1, written by the build, read by
`PackageLayout.manifest()`:

| Key | Content |
| --- | --- |
| `product` | `name`, `edition` (`presentation`), `version` (pyproject), `source_revision` (Git commit) |
| `runtimes.<python\|node>` | `version`, `root`, `executable` (relative), `tree_sha256`, `files`, `source` (`url`, archive `sha256`); `node.npm_version` |
| `app`, `licenses` | `root`, `tree_sha256`, `files` |
| `third_party_manifest_sha256` | SHA-256 of `third-party-manifest.json` |
| `excluded`, `external`, `provisioned` | ids and reasons copied from the policy |
| `package_sha256` | SHA-256 of the canonical manifest body: one value identifies the whole package |

A tree digest is the SHA-256 of `relative path NUL file sha256` lines in path
order: independent of the install folder.

**Consumers.** `private_runtime.diagnostics()` (no hashing, no absolute path)
is the `runtimes` block of `installation` in `/v1/health` and of the
`core.installation` journal event: `mode`, `status` (`ok`/`degraded`/`invalid`),
`edition`, `version`, runtime versions, excluded ids, typed `problems`
(`runtime_manifest_missing`, `runtime_manifest_invalid`,
`private_runtime_missing`). `private_runtime.verify_runtimes()` recomputes the
runtime trees on demand (`private_runtime_integrity_failed`): for a repair or
readiness action (Slice 07), never at startup.

## Third-party policy and manifest

`packaging/windows/third_party_policy.json` is the distribution decision per
component; the build writes `third-party-manifest.json` (schema
`jarvis.third-party-manifest` v1: one line per shipped runtime and wheel with
version, SPDX licence, declared licence and classifiers from the wheel
metadata, source, SHA-256, notes, licence files) and copies the licence texts
under `licenses\`.

The build **refuses** (and `test_windows_packaging.py` fails) when: a wheel is
installed without a policy entry, a policy entry has no wheel, a status is not
`bundled`, an excluded component is installed, or the lock and the install
differ.

| Status | Components (presentation edition) |
| --- | --- |
| `bundled` | Python 3.14.6 (PSF-2.0), Node.js 24.21.0 (MIT + bundled deps, npm Artistic-2.0), 64 wheels (licences in the policy; notes for pynput LGPL-3.0, certifi MPL-2.0, numpy's GCC runtime) |
| `excluded` | `openwakeword` + `onnxruntime` + its models (CC BY-NC-SA 4.0, HV-PACKAGE-04: keyboard wake), `imageio-ffmpeg` (GPLv3, HV-PACKAGE-03), `pvporcupine` (Picovoice terms, HV-PACKAGE-05), `sherpa-onnx` (Solo Owner, out of V1), Barehands and ai-visualizer (AGPL, HV-PACKAGE-06; the Control Center runs without the face), MediaPipe (ships with Barehands), developer tools |
| `external` | Claude Code CLI (not redistributed, HV-PACKAGE-02; installed with Anthropic's official installer, signed in by Slice 07), Chrome/Edge for Remotion renders (HV-PACKAGE-09) |
| `provisioned` | Remotion npm packages, fetched by `npm ci` from the pinned lock (Remotion licence, HV-PACKAGE-08) |

Human decisions: `tasks/jarvis-presentation-edition-v1/slices/06-windows-private-runtime-packaging/human-validation.json`.
Any open licence decision is a **release gate** (Slices 10/11), not a
build failure: the default applied is always the safe one (excluded or not
redistributed).

## Build

Run with the development Python of the **same version** as the pinned runtime
(3.14.6, the repository `.venv`): pip comes from it, and it produces the
bytecode (`PYTHONHASHSEED=0`; the packaged interpreter ignores the environment
and could not fix the hash seed, which orders `frozenset` constants).

```powershell
# from the repository; output and cache outside the repository
.\.venv\Scripts\python.exe packaging\windows\build_package.py build --out $env:TEMP\jarvis-pkg [--rev HEAD] [--cache DIR]
.\.venv\Scripts\python.exe packaging\windows\build_package.py verify $env:TEMP\jarvis-pkg
.\.venv\Scripts\python.exe packaging\windows\build_package.py lock [--constraints FILE]   # maintenance, network
```

Steps: download (or reuse from the cache, default
`%LOCALAPPDATA%\Temp\jarvis-build-cache`) and **re-verify** the SHA-256 of each
runtime archive; extract Python and write `._pth`; `pip download` then
`pip install --no-index --require-hashes --no-deps --only-binary :all: --target`
of the lock (Windows `cp314` wheels only, no sdist); drop the console-script
launchers (they embed the build path) and their `RECORD` lines; copy the
pywin32 DLLs; extract Node; `git archive <rev> jarvis` + marker; precompile;
licences and manifests; then a **probe**: the packaged `python.exe` started with
`PATH` reduced to `System32;Windows;Wbem` must import the product (`jarvis.app`,
aiohttp, numpy, livekit, sounddevice, mcp, pywin32, Google clients), resolve
the private Node and run it, see no `python`/`node`/`npm`/`ffmpeg`/`git` on
`PATH`, have `sys.flags.no_site`, no `sys.path` entry outside the package, no
excluded module importable (`onnxruntime`, `openwakeword`, `imageio_ffmpeg`,
`pvporcupine`, `sherpa_onnx`) and report `diagnostics().status == "ok"`.

**Reproducible**: two builds of the same revision into two folders give the
same `package_sha256` (proved in the Slice 06 LOG). The output folder must be
empty and outside the repository.

### Changing a pin

- Python dependency: edit `requirements.in`, run `lock` (with the `.venv`
  freeze as constraints to keep transitive versions), update the policy for
  any new wheel (the build tells which), rebuild, run the tests.
- Python runtime: change `runtimes.json` (version, URL, SHA-256 from
  `https://www.python.org/api/v2/downloads/release_file/?release=<id>`) **and**
  the development `.venv` to the same version; relock (the ABI tag follows).
- Node: change `runtimes.json` (SHA-256 from `SHASUMS256.txt`); must stay
  `>= NODE_MINIMUM` of `jarvis/domain/remotion_capability.py`.

## Limits and what later Slices own

- Unsigned folder package; no installer, shortcut, launcher or uninstaller
  (Slice 07, HV-PACKAGE-10). The program folder must not be inside the product
  home (`%LOCALAPPDATA%\CIRCOE\Jarvis`): the export guard refuses that overlap.
- The `._pth` file also sets `sys.flags.safe_path`: the working directory is
  never on `sys.path` (a `plantedmod.py` in the current folder is not found by
  `python.exe -m plantedmod`, checked on the real package), so the Slice 07
  launcher may start processes from any folder.
- No updater (Slice 10). `verify_runtimes` detects a changed runtime tree; it
  does not repair it.
- Readiness UI, repair actions and the Claude CLI sign-in: Slice 07.
