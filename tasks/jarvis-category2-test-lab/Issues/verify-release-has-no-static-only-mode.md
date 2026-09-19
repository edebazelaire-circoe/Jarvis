# `scripts/verify_release.py` has no static-only mode

Found during the Slice 01 QA (2026-09-17). This is a tooling defect, not a Test Lab regression.

`scripts/verify_release.py` ignores its arguments (`--help` included) and always runs the full single-process `pytest -q` before its AST and lock checks. On this host (~1–2 GB free RAM, several concurrent sessions), that run gets killed or starves other work. To run the static checks alone today, you have to import the script and stub `subprocess.run`.

Suggested fix, owned outside this task unless a later Slice needs it: add a `--static-only` flag, or let an env var skip the pytest step, and document chunked pytest as the full test gate in `docs/OPERATIONS.md`.
