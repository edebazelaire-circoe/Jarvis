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
  models\wake-word\       INTERNAL build only (see Channels): the three pinned openWakeWord models
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
  `--invalidation-mode unchecked-hash`, in one process (`compileall -j 1`:
  parallel workers gave different bytecode from one build to the next): Python
  does not rewrite `__pycache__` in the program folder (I-002 point 1), and the
  bytecode is identical from one build to the next. **Exception**: a
  third-party file that does not compile (a Python 2 example shipped in a
  wheel) is skipped with a build message; if such a module were ever imported,
  the interpreter would try to write its bytecode into the program folder and
  `verify` would then report the package altered. The Slice 07 launcher must
  therefore start `python.exe` with **`-B`** (no bytecode written), which
  makes the rule hold for every module.
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
| `product` | `name`, `edition` (`presentation`), `version` (pyproject), `source_revision` (Git commit), `channel` (`production` or `internal`; absent = `production`, V1 packages), `channel_warning` (internal only) |
| `runtimes.<python\|node>` | `version`, `root`, `executable` (relative), `tree_sha256`, `files`, `source` (`url`, archive `sha256`); `node.npm_version` |
| `app`, `licenses` | `root`, `tree_sha256`, `files` |
| `models` | internal build only: `root` (`models`), `tree_sha256`, `files`, `wake_word` (`models/wake-word`) |
| `third_party_manifest_sha256` | SHA-256 of `third-party-manifest.json` |
| `excluded`, `external`, `provisioned` | ids and reasons copied from the policy |
| `package_sha256` | SHA-256 of the canonical manifest body: one value identifies the whole package |

A tree digest is the SHA-256 of `relative path NUL file sha256` lines in path
order: independent of the install folder.

**Consumers.** `private_runtime.diagnostics()` (no hashing, no absolute path)
is the `runtimes` block of `installation` in `/v1/health` and of the
`core.installation` journal event: `mode`, `status` (`ok`/`degraded`/`invalid`),
`edition`, `channel`, `version`, runtime versions, excluded ids, typed `problems`
(`runtime_manifest_missing`, `runtime_manifest_invalid`,
`private_runtime_missing`). A manifest whose `runtimes`, `product` or
`excluded` blocks do not have the expected shape (an entry that is not an
object, a `root`/`executable` that is not a relative path inside the package)
is `runtime_manifest_invalid`, never a crash at Core startup.
`private_runtime.verify_runtimes()` recomputes the
runtime trees on demand (`private_runtime_integrity_failed`): for a repair or
readiness action (Slice 07), never at startup.

**Broken runtimes are never silent.** When the `runtimes` status is `degraded`
or `invalid` (`private_runtime.runtime_reserve`): the `core.installation`
event is logged at `error` (so it reaches the error journal) with a message
naming each problem, and `/v1/health` answers `status: "degraded"` with that
sentence in `detail` instead of `ok`. `ready` stays `true`: Core serves (the
conversation, the Boards), only what needs the missing runtime fails, with its
own typed refusal. The readiness view and the repair actions (Slice 07):
[product-install.md](product-install.md) › *Readiness*.

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
| `bundled`, internal channel only | the `wakeword` extra: `openwakeword` (Apache-2.0), `onnxruntime` (MIT; its `LICENSE` and `ThirdPartyNotices.txt` live in the package folder, copied through the policy's `license_files`) and 10 dependencies (scipy, scikit-learn, tqdm MPL-2.0 AND MIT, joblib, narwhals, threadpoolctl, cloudpickle, colorama, flatbuffers, packaging); the three openWakeWord models (`models`, CC-BY-NC-SA-4.0, with `licenses\openwakeword-models\NOTICE.txt`) |
| `excluded` | production channel: `openwakeword` + `onnxruntime` + its models (CC BY-NC-SA 4.0, HV-PACKAGE-04: keyboard wake; HD-V12-01 lifts it for the internal channel only), `imageio-ffmpeg` (GPLv3, HV-PACKAGE-03), `pvporcupine` (Picovoice terms, HV-PACKAGE-05), `sherpa-onnx` (Solo Owner, out of V1), Barehands and ai-visualizer (AGPL, HV-PACKAGE-06; the Control Center runs without the face), MediaPipe (ships with Barehands), developer tools |
| `external` | Claude Code CLI (not redistributed, HV-PACKAGE-02; installed with Anthropic's official installer, signed in by Slice 07), Chrome/Edge for Remotion renders (HV-PACKAGE-09) |
| `provisioned` | Remotion npm packages, fetched by `npm ci` from the pinned lock (Remotion licence, HV-PACKAGE-08) |

Human decisions: `tasks/jarvis-presentation-edition-v1/slices/06-windows-private-runtime-packaging/human-validation.json`.
Any open licence decision is a **release gate** (Slices 10/11), not a
build failure: the default applied is always the safe one (excluded or not
redistributed).

## Channels: production and internal builds

Decision HD-V12-01 (`tasks/jarvis-presentation-edition-v1-2/slices/00-project-manager/HUMAN-DECISIONS.md`):
V1.2 is tested internally with the current wake word technology (openWakeWord,
whose pre-trained models are CC BY-NC-SA 4.0, non-commercial), which must be
replaced before any production release. The build therefore has two channels,
`build --channel production|internal`:

| | `production` (default) | `internal` (explicit) |
| --- | --- | --- |
| Wheels | `requirements.lock` | `requirements.lock` + `requirements-internal.lock` (the `wakeword` extra; resolved with the production lock as constraint, so shared wheels keep the production version and hash) |
| Wake word models | none | `models\wake-word\` : `melspectrogram.onnx`, `embedding_model.onnx`, `hey_jarvis_v0.1.onnx`, downloaded **at build time** by `wakeword_model_catalog` (size and SHA-256 pinned there), never at first launch |
| Policy | entries without `channels`; `openwakeword`, `onnxruntime`, `openwakeword-models` are `excluded` | adds the entries `channels: ["internal"]` and the `models` section; those three exclusions (`channels: ["production"]`) do not apply |
| Manifests | `product.channel: "production"` | `product.channel: "internal"`, `product.channel_warning`, `models` tree; third-party manifest `channel`, `warning`, model components with `channels` |
| Default wake word of a blank profile | F9 only | « Hey Jarvis » armed in Sleep, plus F9 ([voice-lifecycle.md](voice-lifecycle.md)) |

The internal warning, everywhere it is written (policy, manifests, `verify`
output, `NOTICE.txt`, release info): « Usage interne non commercial ; à
remplacer avant production ». `channel_policy` filters the policy for the
channel being built: a reserved wheel installed in a production build has no
policy entry and is an excluded component, so the build stops. **`verify`
refuses a production package** (`private_runtime.channel_problems`, shared with
the installer) that holds a `models\` tree, an `openwakeword` or `onnxruntime`
folder or `dist-info` in `site-packages`, or a third-party component reserved
to another channel, and any unknown channel. A manifest without `channel` (V1
packages) is production.

Maintenance: `build_package.py lock --channel internal` regenerates
`requirements-internal.lock` from `requirements-internal.in` and refuses a
resolution that would change a production wheel. `scripts/verify_release.py`
fails when an internal wheel is also in the production lock or is not reserved
to the internal channel by the policy.

## Build

**Prerequisites**: a Git repository of the code (a clone or a worktree, not a
source archive: the code comes from `git archive`) with `git` on the `PATH`,
and the development Python of the **same version** as the pinned runtime
(3.14.6, the repository `.venv`): pip comes from it, and it produces the
bytecode (`PYTHONHASHSEED=0`; the packaged interpreter ignores the environment
and could not fix the hash seed, which orders `frozenset` constants). Without
Git the build stops with `git … a échoué (code N) : <git's full message>` and
these prerequisites.

**Inputs come from the revision.** The build reads the code (`git archive`),
`runtimes.json`, `requirements.lock`, `third_party_policy.json`, the marker and
the `pyproject.toml` version. It **refuses** to start when the working tree
differs from `--rev` on `jarvis\`, `packaging\windows\` or `pyproject.toml`
(uncommitted change, or `--rev` older than the checkout): commit first, or build
from a clean checkout of that revision. A package therefore never claims one
`source_revision` while carrying another revision's lock or policy.

```powershell
# from the repository; output and cache outside the repository
.\.venv\Scripts\python.exe packaging\windows\build_package.py build --out $env:TEMP\jarvis-pkg [--channel production|internal] [--rev HEAD] [--cache DIR]
.\.venv\Scripts\python.exe packaging\windows\build_package.py verify $env:TEMP\jarvis-pkg
.\.venv\Scripts\python.exe packaging\windows\build_package.py lock [--channel production|internal] [--constraints FILE]   # maintenance, network
```

Steps: download (or reuse from the cache, default
`%LOCALAPPDATA%\Temp\jarvis-build-cache`) and **re-verify** the SHA-256 of each
runtime archive; extract Python and write `._pth`; `pip download` then
`pip install --no-index --require-hashes --no-deps --only-binary :all: --target`
(both with `--no-cache-dir`: pip writes nothing to the user's cache, the only
cache is the declared one, Slice 10) of the lock (Windows `cp314` wheels only, no sdist); drop the console-script
launchers (they embed the build path) and their `RECORD` lines; copy the
pywin32 DLLs; extract Node; `git archive <rev> jarvis` + marker; precompile;
licences and manifests; then a **probe**: the packaged `python.exe` started with
`PATH` reduced to `System32;Windows;Wbem` must import the product (`jarvis.app`,
aiohttp, numpy, livekit, sounddevice, mcp, pywin32, Google clients), resolve
the private Node and run it, see no `python`/`node`/`npm`/`ffmpeg`/`git` on
`PATH`, have `sys.flags.no_site`, no `sys.path` entry outside the package, no
excluded module importable (`onnxruntime`, `openwakeword`, `imageio_ffmpeg`,
`pvporcupine`, `sherpa_onnx`; the internal channel drops the first two) and
report `diagnostics().status == "ok"`. The probe also reads the wake word of a
blank profile (`wake_word_settings.load({})`): disabled in production; in the
internal channel it must be armed (`openwakeword`), the models must be read
from `models\wake-word` and verified, and the real openWakeWord detector is
built from them and fed five frames of silence (zeros, no audio device
opened), which must not trigger.

**Reproducible**: two builds of the same revision into two folders give the
same `package_sha256` (proved in the Slice 06 LOG, then again after the QA
rework with `compileall -j 1`). The output folder must be empty and outside
the repository. Archive members are extracted only inside their target folder
(no `..`, no absolute name, no drive letter).

**`verify`** recomputes every tracked tree (`app`, `licenses`, `models` when
declared, each runtime), the third-party manifest digest and `package_sha256`,
reports any file or folder that belongs to no tracked tree (at the package
root, or directly under `runtime\` beside the declared runtimes) and any
departure from the package channel (see Channels); it names the channel and
repeats the internal warning. An unreadable manifest (invalid JSON,
a UTF-8 BOM, a wrong shape) is a clean `ÉCHEC : paquet altéré`, exit code 1.

### Trying the package (simulated installed product)

Never on the live JARVIS ports or data. Start the packaged `python.exe` with:
`PATH` reduced to `C:\Windows\System32;C:\Windows`; `LOCALAPPDATA` pointed at a
throw-away folder (the product home is created under it); free ports in
`JARVIS_CORE_PORT`, `JARVIS_UI_PORT`, `JARVIS_REMOTION_SANDBOX_PORT`,
`JARVIS_VISUALIZER_PORT`; `JARVIS_VISUALIZER_ENABLED=0`; and
**`JARVIS_OPEN_BROWSER=0`**, otherwise the Control Center opens its page in the
tester's own browser. Then `python.exe -B -m jarvis core` (and
`control-center`) and read `/v1/health`. Stop the processes by their exact PID.

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

- Unsigned folder package. The installer (one `.exe` built on top of this
  folder by `build_package.py installer`), shortcuts, the single launcher
  (`python -B -m jarvis launch`) and the uninstaller are Slice 07:
  [product-install.md](product-install.md) (HV-PACKAGE-10 recommendation there).
  The program folder must not be inside the product home
  (`%LOCALAPPDATA%\CIRCOE\Jarvis`): the export guard and the installer refuse
  that overlap. `verify` and the installer share one verification,
  `private_runtime.verify_package`.
- The `._pth` file also sets `sys.flags.safe_path`: the working directory is
  never on `sys.path` (a `plantedmod.py` in the current folder is not found by
  `python.exe -m plantedmod`, checked on the real package), so the Slice 07
  launcher may start processes from any folder.
- No updater. `verify_runtimes` detects a changed runtime tree; it does not
  repair it (the installer does). The CI build of a release candidate, its
  identity (`release-info.json`) and the installed-product smoke are
  [release.md](release.md).
- Excluded components stay unreachable from the product, not only absent:
  in the `presentation` edition the Control Center does not declare the
  `jarvis-barehands` MCP server (no `barehands-mcp.json` is written), and an
  installed `presentation` product refuses `python -m jarvis wake-word install`
  (`wake_word_install_unavailable_in_edition`: the CC BY-NC-SA models are never
  downloaded by the product; in an internal build the message says they are
  already shipped; `wake-word status` stays available and reads
  `models\wake-word` of the package).
- Readiness UI, repair actions and the Claude CLI sign-in: Slice 07,
  [product-install.md](product-install.md) › *Readiness*.
