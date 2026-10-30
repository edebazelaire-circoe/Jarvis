# Human QA preview helper

`preview.py` reuses S05's `LiveAcceptance` class. It starts real isolated Core,
SQLite and Control Center HTTP on loopback ephemeral ports, with clearly
synthetic notes/image/agent facts and one controlled blocking job. No model
call, user's runtime, browser profile, live data or product code is involved.
The S05 `/qa/*` driving routes remain present in this local-only sandbox.

Launch only after PM's final machine gates. Example from the accepted worktree:

```powershell
C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/preview.py --manifest C:/Temp/jarvis-human-review-unique.json --duration 1200
```

The manifest path must be explicit and new. It records observed `review_url`,
Python PID, start/ready/expiry timestamps, unique temporary root and separate
data/runtime paths. Core and UI both run within this one Python process, so
there are no unrelated process IDs to discover or terminate. Async sandbox
startup has a120-second deadline after imports. The helper stays
alive for 1..7200 seconds (default600), then closes only its own `LiveAcceptance`
objects in `finally` and updates the manifest with stop time/reason. Ctrl+C
also closes owned objects. It never scans or kills process names/trees.

For a hidden launch, the PM can use PowerShell `Start-Process -WindowStyle
Hidden` with the absolute interpreter, helper, worktree and new manifest
paths. Use the observed manifest URL; do not guess a fixed port. No persistent
preview was launched while preparing this helper. The one-second disposable
smoke is recorded separately in `preview-helper-smoke.json`.

The synthetic temporary root remains after shutdown, including its databases;
the helper does not delete SQLite files. A stopped URL is not reusable.
Launching again requires a fresh explicit manifest and creates a new root.
The helper is QA tooling only and does not represent Human acceptance or
authorize a main merge/Drive completion.
