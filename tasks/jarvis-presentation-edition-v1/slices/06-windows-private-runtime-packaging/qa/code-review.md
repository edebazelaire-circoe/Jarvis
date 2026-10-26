# Slice 06 — QA code review + qa-verification

Reviewer: independent QA agent (code-review + qa-verification). Date: 2026-10-26.
Range reviewed: `1992bf99..3f2ba594` (`5ed074e8`, `3d2f6231`, `18ec743e`, `27cda35f`, `ba61dcc5`, `f29d41cf`, `3f2ba594`), worktree `pev1`.
No product code modified. No JARVIS launched, no package built (the rebuild and the real run belong to the runtime QA).

## Summary

**PASS. No blocker.** One MAJOR finding: two Level 3 docs are corrupted by escape sequences and converted to CRLF. Fixing it takes a few minutes. There are also seven MINOR findings.

The core contract holds:
- The development path is strictly unchanged. Resolution was measured before and after, and is identical.
- The installed product never falls back to the PATH for owned tools.
- The build verifies SHA-256 before any extraction or execution.
- The third-party policy refuses any gap.
- Excluded components are absent: by construction (`git archive … jarvis`, lock) and by test.
- Most targeted mutations are killed.

## Scope reviewed

- `SLICE.md` (with the Slice 00 E4/E5/E6 amendments), `human-validation.json`, the S06 LOG entry, `READINESS.md` (E4–E6 release gates), `Issues/I-002-s02-leftovers.md`.
- Code: `jarvis/private_runtime.py`, the diffs of `process_tree.py`, `node_capability_runner.py`, `remotion_render_runner.py`, `remotion_studio_runner.py`, `screen_capture.py` and `app.py`, plus `packaging/windows/{build_package.py, runtimes.json, requirements.in, requirements.lock, third_party_policy.json}`.
- Tests: `tests/unit/test_private_runtime.py`, `tests/unit/test_windows_packaging.py`.
- Docs: `docs/windows-packaging.md`, the diffs of `local-data.md`, `remotion-runtime.md`, `capture.md`, `product-edition.md`, `third_party/README.md`.
- Surrounding code read to check exclusion and PATH use: `cli_catalog.py`, `routing_hook.py`, `wake_word_install.py`, `wakeword_model_catalog.py`, `feedback_sessions.py`, the `app.py` visualizer start, `protocol/server.py` health.

## Evidence (observed by this QA)

### Tests run
Run with `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest`, from `pev1`, in the foreground:

| Batch | Result |
| --- | --- |
| `test_private_runtime.py` + `test_windows_packaging.py` | 48 passed |
| process_tree (+kill, owned), node_capability_runner, local_capability host/routes, screen_capture, installed_product_root, data_root, product_edition, remotion_studio_runner, remotion_lifecycle, wake_word_docs | 363 passed, 3 skipped (ffmpeg absent from the `.venv`) |
| presentation_render_runner, the docs tests that cite the changed docs (13 files), remotion_isolation, remotion_media_tools | 431 passed, 2 skipped, 3 failed |
| `test_remotion_isolation.py` rerun alone | 267 passed |

The 3 failures were `test_remotion_isolation::test_every_rule_stays_fast_on_newline_separated_adversarial_input` (a timing test) under load. S06 touches no file on that path.

### Intermittent failure in `test_presentation_render_service`
Pair routes+service rerun alone 8 times: 7 × 85 passed, 1 × `1 failed, 84 passed`.

**Not caused by S06.**
- The range does not touch `jarvis/core/presentation_render_service.py`, its tests, or anything that file imports from S06 (`git diff --stat 1992bf99..3f2ba594 -- jarvis/core tests/unit/test_presentation_render*` is empty).
- The rig uses a fake runner, with no `process_tree` or `private_runtime`.
- The pattern matches a race in the test. For example, `test_the_runner_receives_…:103` asserts `("cleanup", job_id) in rig.runner.calls` as soon as the job is `complete`. But the service calls `cleanup` after publishing the final state (`presentation_render_service.py:644`).
- This is pre-existing (see Flagged).

### Development path unchanged
Measured from `pev1` with the repository `.venv`:
- `package_layout()` is `None`.
- `private_runtime.which(n) == shutil.which(n)` for `node`, `node.exe`, `npm`, `npm.cmd`, `npx`, `python`, `py`, `ffmpeg`, `ffprobe`, `git`, `claude` (all `True`, same paths: `C:\Program Files\nodejs\…`, `C:\Python314\python.EXE`, `C:\Windows\py.EXE`, …).
- `child_path(PATH) == PATH`, `clean_env()` PATH identical, `find_ffmpeg()` unchanged (`None`, the `capture` extra is absent).
- `setup.ps1`, `pyproject.toml`, `scripts/`, `.gitignore` are untouched.
- `jarvis/capabilities/remotion` (the Remotion lock) is untouched.

### Installed product, static review
- The owned names (`OWNED_TOOLS`) never fall back to the PATH.
- `npm`/`npx` give `None`; the runner uses `node npm-cli.js` next to the private Node.
- `ffmpeg` resolves only if the manifest declares it.
- The node refusals are typed (`node_missing: … repair or reinstall Jarvis`).
- The remaining `shutil.which` calls (`cli_catalog`, `routing_hook`, `barehands_replay`, `knowledge_codegraph`/`worktrees` `git`) concern external CLIs or development/excluded tools, not a Presentation path.
- The visualizer is off by default in the package (`app.py:1670-1676`: `third_party/` absent, so "non installé", without error).
- The feedback folder goes to the product home (`feedback_sessions.py`).

### Build integrity, static review
- `fetch_verified` hashes the cached archive at every build and removes it if it does not match. Extraction happens only after the check.
- Wheels go through `--require-hashes --no-deps --only-binary :all:` at both download and install.
- The packaged `python.exe` runs only in the final probe, after everything is verified.
- `git archive <rev> jarvis` only: no `third_party/`, `scripts/`, `tests/`.
- The policy refuses: an unlocked wheel, a wheel without policy, a policy without wheel, a non-`bundled` status, an excluded component present.
- No personal path or secret in `packaging/` (grep for `clarice`, `c:\users`, `token`, `secret`, `api_key`: empty).
- The lock has 64 wheels, as the LOG says.

### Excluded components
- openwakeword/onnxruntime, imageio-ffmpeg, pvporcupine and sherpa-onnx are absent from the lock (test plus mutation M9).
- `jarvis/runtime/control_center_barehands*.js` is a clean-room reimplementation (file header). The AGPL Barehands/ai-visualizer/MediaPipe code lives in `third_party/`, which is not archived.
- No `.onnx`, `.ppn`, `.exe`, `.dll` file under `jarvis/` (`git ls-tree`).
- The Claude Code CLI is not bundled (`external`).
- Exception: see m6 for the wake-word CLI.

### Mutations
Run on a copy `…\scratchpad\s06qa\mut` (via `git archive 3f2ba594`), never in the worktree. Scripts: `…\scratchpad\s06qa\mutate.py`, `mutate2.py`.

| # | Mutation | Result |
| --- | --- | --- |
| M1 | `which` installed: `current.tool(name) or fallback(name)` (PATH fallback reintroduced) | **killed** (`test_installed_node_is_the_private_one_and_never_the_path`) |
| M2 | `fetch_verified`: SHA-256 check bypassed | **killed** (`test_a_corrupt_cached_archive_is_removed_and_refused`) |
| M3 | build: "composant exclu présent" check removed | **killed** (`test_third_party_manifest_refuses_an_excluded_component`) |
| M4 | `find_ffmpeg`: installed-product branch disabled (back to `imageio_ffmpeg`) | **survived** (see m4) |
| M5 | `command_verify`: `app`/`licenses` trees no longer compared | **survived** (see m4) |
| M6 | `verify_runtimes`: tree digest ignored | **killed** |
| M7 | `clean_env` without `child_path` | **killed** |
| M8 | `import site` added to `._pth` | **killed** |
| M9 | `openwakeword` reintroduced into the lock | **killed** (2 tests) |
| M10 | build probe tolerates an importable excluded module | **survived** (see m4) |

Result: 7 of 10 killed.

## Findings

### MAJOR

**M1 — Two Level 3 docs corrupted by interpreted escape sequences, and converted to CRLF**

Location: `docs/local-data.md:48-49`, `docs/remotion-runtime.md:39` (commit `f29d41cf`).

Where the text was meant to be `<installation>\app\`, `<installation>\runtime\` and `runtime\node`:
- `local-data.md` contains a BEL byte (`\a`): `` `<installation>\x07pp\` ``.
- `local-data.md` also contains a lone CR (`\r`): `` `<installation>\runtime\` `` became `<installation>` + CR + `untime\`.
- `remotion-runtime.md:39` has `\runtime\r\node` turned into CR + `untime` + CRLF + `ode`. The line is cut and the text is lost.

In addition, both files went from LF to CRLF in the index:
- `git ls-files --eol` gives `i/-text`: git now treats them as non-text because of the lone CR.
- Hence the 1,146-line diff for `local-data.md` and 387 lines for `remotion-runtime.md`. With `-w --ignore-cr-at-eol` the real change is only 7+/2- lines.

Failure scenario:
1. A reader of the canonical contract sees a broken path and a cut line.
2. Any concurrent edit of `local-data.md` or `remotion-runtime.md` on `main` conflicts on the whole file at merge time. This is the risk of a silently lost side, already seen on this repository.
3. Git no longer applies its text heuristics to these files.

Proof: byte scan of the files at `3f2ba594`:
- `local-data.md`: crlf 575, lone_cr 1, BEL 1.
- `remotion-runtime.md`: crlf 194, lone_cr 1.
- Both: `i/lf` at `1992bf99`, `i/-text` at `3f2ba594`.

Recommendation: rewrite both files in LF, with literal backslashes (`\app\`, `\runtime\`, `\runtime\node`), and check `git ls-files --eol` gives `i/lf`.

### MINOR

**m1 — `private_runtime.diagnostics()` can raise at Core startup instead of returning `runtime_manifest_invalid`**

Location: `jarvis/private_runtime.py:257-262` (`_presence_problems`, `excluded`, `product`), called unguarded from `jarvis/app.py:882-883`.

Scenario: a manifest with a valid schema whose entries are not objects, for example `"runtimes": {"node": "x"}`, `"product": "p"` or `"excluded": ["a"]`.

Proof: all three cases raise `AttributeError: 'str' object has no attribute 'get'`, measured with `PackageLayout` on a temp folder. Core would then stop on a raw traceback instead of the typed problem promised by `docs/windows-packaging.md` › Consumers.

`verify_runtimes` has the same weakness (`entry.get`). It also accepts `"root"` taken from the manifest without bounds (an empty `root` hashes the whole installation).

Recommendation: validate the shape of `runtimes`/`product`/`excluded` in `PackageLayout.manifest()` (`ValueError`, which `diagnostics()` then reports as `runtime_manifest_invalid`).

**m2 — The build mixes the code of `--rev` with packaging inputs read from the working tree**

Location: `packaging/windows/build_package.py:488-503`.

Only `jarvis/` comes from `git archive <rev>`. The following come from the working tree:
- `runtimes.json`, `requirements.lock`, `third_party_policy.json`;
- the `pyproject.toml` version (`runtime_manifest`, l.403);
- `marker_payload()` and `private_runtime` (imported from `REPO`).

There is no dirty-tree check.

Scenario: `build --rev <older commit>`, or a build from an uncommitted change. The result is a package whose `source_revision` claims a commit while its lock, policy or marker do not match it. Reproducibility "from the revision" is then not guaranteed.

Recommendation: refuse a dirty tree (`git status --porcelain` on `packaging/`, `jarvis/`, `pyproject.toml`), or read these inputs from `git show <rev>:…`, and allow `--rev` only when it equals HEAD.

**m3 — Health and journal stay neutral when the package runtimes are broken**

Location: `jarvis/app.py:883-885`, `jarvis/protocol/server.py:362`.

With `runtimes.status` set to `degraded` or `invalid`:
- `/v1/health` still answers `ready: true`;
- the `core.installation` event is emitted at `info`;
- no `warning`/`error` event names the problem.

The information is there (the `installation.runtimes.problems` block), so this is not dishonest. But a broken installation is not visible in the error journal until a Remotion action fails.

Recommendation: emit a `warning` event (`core.installation.runtime_problem`) when `problems` is not empty. Slice 07 owns the readiness view.

**m4 — Test gaps (surviving mutations M4, M5, M10)**

- M4: `test_screen_recording_has_no_ffmpeg_in_the_presentation_package` (`test_private_runtime.py:156`) passes even with the installed-product branch removed, because `imageio_ffmpeg` is absent from the `.venv`. The test does not distinguish the contract. It should inject a fake `imageio_ffmpeg` module (`monkeypatch.setitem(sys.modules, …)`) that returns a path, and assert `None`.
- M5: `command_verify` (`build_package.py:510-529`) has no test. Tampering with `app\`, `licenses\`, `third-party-manifest.json` or `package_sha256` is not covered. Only `verify_runtimes` is tested, and only for an added file (deletion and modification are not tested).
- M10: the `expected` logic of the probe (`build_package.py:472-477`) has no unit test. It is only exercised by a real build.

**m5 — `extract_zip` does not refuse a root-anchored name**

Location: `packaging/windows/build_package.py:185-190`, and the same for the tar at l.288.

Proof: `Path('/evil.txt').parts == ('\\', 'evil.txt')` passes the check (no `..`, no `:`), and `Path(r'C:\build\out').joinpath(*parts) == C:\evil.txt`.

The risk is low: the archives are pinned by SHA-256 to official sources, and the tar comes from this repository's `git archive`. It is still a gap in the Zip Slip defence that the test `test_zip_extraction_refuses_escaping_paths` claims to cover.

Recommendation: check `destination.resolve().is_relative_to(target.resolve())`.

**m6 — The `wake-word install` subcommand stays shipped and can download the CC BY-NC-SA models in the product**

Location: `jarvis/app.py:50,2139`, `jarvis/runtime/wake_word_install.py`; `third_party_policy.json` › `openwakeword-models`.

The policy says the models are "jamais livrés ni téléchargés par le paquet". However, `<install>\runtime\python\python.exe -m jarvis wake-word install --yes` remains available in the package. It downloads the three models into the product home: `default_model_dir` resolves to `<maison>/runtime` (`wakeword_model_catalog.py:152-153`).

The models are unusable without `openwakeword`, so this is neither a redistribution nor a functional activation. But the policy text is inaccurate, and a non-commercial asset can still be fetched by the product.

Recommendation: refuse the subcommand in the `presentation` edition (typed refusal), or correct the policy text. Release gate HV-PACKAGE-04.

**m7 — "Every `.py` is precompiled" is not quite true, and there is no write guard for bytecode**

Location: `build_package.py:313-318`, `docs/windows-packaging.md` › The packaged Python.

Third-party files that fail to compile are ignored. Nothing (`-B`, `sys.dont_write_bytecode`) prevents the interpreter from writing `__pycache__` into the program folder if such a module, or a future non-precompiled file, is imported. In a per-user installation (`%LOCALAPPDATA%\Programs`) the write would succeed and `verify` would then report the package as altered.

The implementer proved `verify` stays intact after Core, the Control Center and a render. That holds for the paths exercised.

Recommendation: the Slice 07 launcher passes `-B`, or `app\jarvis\__main__` sets `sys.dont_write_bytecode = True` in installed product mode. The doc should mention the exception.

### OBSERVATION

- `process_tree.clean_env` now always writes a `PATH` key. In development, a source without `PATH` gives `{"PATH": ""}` where there used to be no key (`process_tree.py:51-52`). There is no practical effect on Windows (absent PATH and empty PATH behave the same), and the tests pass.
- Development messages changed slightly: `node_missing: node is no longer on PATH` became `… no longer available`, and `Node.js >= 20 was not found on PATH` became `Node.js >= 20: Node.js was not found on PATH`. No consumer parses this text (the tests pass).
- `pip download` and `pip install` run without `--no-cache-dir`: pip writes to its user cache (`%LOCALAPPDATA%\pip\Cache`), outside the build folder. The validity of the package does not depend on it (hashes are re-verified), but the build does write outside the build folder and its declared cache.
- In the installed product, `clean_env` puts `runtime\node` first in the PATH of every child, including the Claude CLI and its tools. This is coherent with the contract, but should be known (S07).

## Flagged (outside S06)

- `test_presentation_render_service`: an intermittent failure from a pre-existing test race. The test asserts `cleanup` as soon as `complete` is visible, while the service calls it afterwards (`presentation_render_service.py:644`). Observed 1 time in 8 here; the implementer saw 2 in 7. Not caused by S06 (no file on that path touched).
- `test_remotion_isolation::test_every_rule_stays_fast_on_newline_separated_adversarial_input` (3 parameters): a timing test that fails under load (in a large batch) and passes alone (267/267).
- `tasks/jarvis-presentation-edition-v1/LOG.md:115` contains a VT byte (`\x0b`): `outside\victim.txt` became `outside` + VT + `ictim.txt`. Commit `5484d8e4` (S04), not S06: the same kind of escape-sequence corruption as M1.

## Missing / Not verified

- No package build or rebuild: reproducibility (`package_sha256` identical across two builds), the probe with a reduced PATH, `safe_path`/`ignore_environment` of the real `._pth`, the real `verify`, the Remotion install/render through the private Node, and the absence of writes into the program folder were not reproduced here. They are left to the runtime QA.
- The licences in `third_party_policy.json` were not checked one by one against the wheel metadata (the build compares them at runtime; that is HV-PACKAGE-07, legal review).
- Code paths that might still write under `CODE_ROOT` in installed mode, beyond those read: not audited exhaustively (S02 + the implementer's real proof).
- No real Claude CLI turn, voice or Drive check in the package (outside this review; S07).

## Residual risks

- Integrity does not mean authenticity. `runtime-manifest.json` sits in the program folder and can be recomputed by whoever modifies the package. Signing is Slice 07/10 (HV-PACKAGE-10).
- The probe and `verify` are the only guards for the excluded components at runtime and for the trees, and both are untested in unit tests (m4).
- The HV-PACKAGE-02..10 decisions remain release gates (Slices 10/11). The safe default is applied everywhere.

## Recommendations (for the PM)

- Fix M1 before any merge into `main` (trivial fix, real merge risk).
- m1, m2 and m4: a short rework is desirable, or record them in an Issue for S07/S10.
- m3, m5, m6 and m7 can go to the Issues (S07/S10).
