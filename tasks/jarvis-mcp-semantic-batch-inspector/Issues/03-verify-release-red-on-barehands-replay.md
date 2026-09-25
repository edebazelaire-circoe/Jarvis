# `scripts/verify_release.py` fails on `barehands_replay.py`

Found by Slice 08 (2026-09-25). This was already true at `ddcdb71` and was not caused by this task.

The static check "dangerous execution primitive in Jarvis package" fails on `subprocess.run(` in `jarvis/runtime/barehands_replay.py:144`. That file runs a replay binary with a fixed argument list and no shell. The release script therefore fails on `main` itself, before its own pytest step even matters. Every other static check passes (see `slices/08-integration-release-qa/qa/release-qa.md` §2).

Fix options, for the owner of Bare Hands tooling:

- add `barehands_replay.py` to an explicit allow-list, the same way the speaker-benchmark tooling is handled in `verify_release.py`;
- or move the replay runner out of the `jarvis/` package.
