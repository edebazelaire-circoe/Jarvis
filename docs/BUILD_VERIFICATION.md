# Jarvis V1 build verification

Date: 2026-08-31

Final source-tree verification before packaging:

- `python -W error::ResourceWarning -m pytest -q` -> **107 passed, 1 skipped**.
- Skipped test: opt-in real OpenAI integration smoke (`JARVIS_LIVE_OPENAI=1`).
- `python scripts/verify_release.py` -> **PASS**.
- `python -m compileall -q jarvis scripts tests` -> **PASS**.
- `sh -n setup.sh` -> **PASS**.
- coverage over `jarvis` + `scripts` -> **75% total**; the raw number intentionally includes hardware/keyboard entrypoints and process-launch paths not executable in the headless sandbox.
- source scan found no general `subprocess.run`/`Popen`, `os.system`, `shell=True`, `eval` or `exec` primitive inside the `jarvis/` package.
- runtime CDN references outside the bootstrap/lock/handoff exist only in bootstrap regression-test fixtures that assert they are removed.
- no actual OpenAI key was used or embedded in the artifact.

Environment limitations carried as manual gates rather than fabricated passes:

- no outbound network/DNS for real third-party bootstrap or OpenAI live calls;
- no physical microphone/speaker/camera acceptance;
- no Chrome physical-gesture smoke;
- no PowerShell executable in the Linux build sandbox, so `setup.ps1` is statically reviewed but not executed;
- no real-provider p50/p95 latency measurement.

The packaged ZIP is re-extracted after creation and the strict pytest/release verifier are executed again from that extracted copy. See the final response/checksum for the delivered artifact.
