# I-007 — Slice 06 leftovers (QA 2026-10-26)

Origin: Slice 06 QA (code review `slices/06-windows-private-runtime-packaging/qa/code-review.md`, runtime QA) and its
rework. The rework fixed the majors (corrupted docs, non-deterministic bytecode) and the cheap minors; what follows was
deliberately left out. Not blocking; owners:

1. **Slice 07 (repair)** — runtime QA m4: after the private Node is put back (`runtime\node` restored), the Remotion
   local capability stays `install_failed` until an explicit repair. The capability state is persisted and not
   re-evaluated when the runtime reappears. The Slice 07 readiness/repair action should re-check the capability after a
   runtime repair (or offer « Réparer » on that state).
2. **Observations of the code review (no action decided)**:
   - `process_tree.clean_env` now always writes a `PATH` key; in development a source without `PATH` gives
     `{"PATH": ""}` instead of no key. No effect on Windows.
   - Development messages changed slightly (`node_missing: node is no longer on PATH` → `… no longer available`,
     `Node.js >= 20 was not found on PATH` → `Node.js >= 20: Node.js was not found on PATH`). No consumer parses them.
   - `pip download` / `pip install` of the build run without `--no-cache-dir`: pip writes to the user cache
     (`%LOCALAPPDATA%\pip\Cache`), outside the build folder and its declared cache. Package validity does not depend on
     it (hashes re-verified). Owner: Slice 10 (CI build).
   - In the installed product, `clean_env` puts `runtime\node` first in the `PATH` of every child, the Claude CLI and its
     tools included. Coherent with the contract; Slice 07 should know it.
3. **Intermittent tests outside the Slice (pre-existing)**:
   - `tests/unit/test_presentation_render_service.py`: a race in the test. It asserts `("cleanup", job_id)` in the fake
     runner's calls as soon as the job is `complete`, while the service calls `cleanup` after publishing the final state
     (`jarvis/core/presentation_render_service.py:644`). Seen 1/8 (QA) and 2/7 (implementation) under load. Fix: wait
     for the cleanup call in the test, or publish after cleanup.
   - `tests/unit/test_remotion_isolation.py::test_every_rule_stays_fast_on_newline_separated_adversarial_input`
     (3 parameters): a timing assertion that fails in a large batch under load and passes alone (267/267).
4. **Human decisions (release gates, Slices 10/11)**: HV-PACKAGE-01..10 stay open with the safe default applied
   (clean-machine trial, Claude Code CLI not redistributed, FFmpeg GPL excluded, openWakeWord excluded, Picovoice
   excluded, Barehands/ai-visualizer AGPL excluded, legal review of the manifest, Remotion licence, system
   Chrome/Edge, signing/installer/location). See
   `slices/06-windows-private-runtime-packaging/human-validation.json` and the Slice 06 LOG entry.

## Rework counter-review (`qa/rework-review.md`, `950baca2`)
- m1: the determinism test checks `compileall_argv`, not that `precompile` uses it (`packaging/windows/build_package.py`).
- m2: no test covers "no `jarvis-barehands` in `presentation`" (`jarvis/app.py`); the only test going through it already fails on `main`.
- m3: the build-inputs test compares against `B.BUILD_INPUTS` itself (removing `pyproject.toml` survives); the `resolve().is_relative_to` extraction guard is never reached by the tested cases.
- Observation: in an installed product, a hand-set `JARVIS_PRODUCT_EDITION=full` re-enables `wake-word install` (decide with HV-PACKAGE-04). Cross-machine reproducibility not proven (both builds on the same machine/pip/cache).

## Slice 07 status (2026-10-26)
- Point 1: done. Readiness shows « Moteur de rendu : Réparer » on `install_failed` and the named action `render_repair` reinstalls at the pinned versions. Reproduced and fixed in the simulated install (private Node removed, restored by a repair reinstall, capability still `install_failed`, then ready in 61 s).
- Launcher `-B`: done (every child of the launcher). The MCP servers started by the Claude CLI from `*-mcp.json` still run without `-B`; `verify` of the installed folder stayed intact after two sessions and a render.

## Slice 10 status (2026-10-27)
- Point 2 (pip user cache): done, `--no-cache-dir` on both pip calls of the build (`test_release_tooling.py`).
- Point 3 (intermittents): done. `test_presentation_render_service.py` waits (bounded) for the `cleanup` call made
  after the final state; `test_remotion_isolation.py` measures the thread CPU time instead of the wall clock.
  Neither is in `tests/known_failures.json`.
- Point 4 and the counter-review observations: carried into the release gate table (`docs/release.md`).
  Cross-machine reproducibility is still not proven.
