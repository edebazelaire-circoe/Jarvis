# Independent S05 runtime evidence

Date2026-10-30; actual product integration `5feebb58` (source
`80607352b141b26501a8d39d54016d9dfbaa6a79`), merged into QA worktree at
`bd8490df`. Focused checks only; no full suite or user runtime/data involved.

## What actually ran

`qa/test_live_acceptance.py` starts real isolated Core/SQLite and the actual
Control Center HTTP application with production Scene/Work/Mission/Session
transports. Node CDP drives actual Chromium while Python's event loop stays
live. Scene mutations and job cancellation are never fetch doubles. Network
events independently record actual POST bodies/statuses. QA-only routes expose
owned state and deliberately introduce external edits/restart/completion.

Eight distinct scenarios have passing final evidence:

| Scenario | Observed result | Evidence |
|---|---|---|
| Actual page/scene preflight | Seven seeded objects render, no browser exception | live-preflight.json |
| Ctrl-select three and mouse-drag title | One `layout_selection`, explicit three IDs/targets; revision20→21; common nonzero stored displacement, dimensions/selection retained; no member pin/set_geometry calls | live-group-drag.json |
| Organize row, view/layout/close, undo — fixed | One forward and one compared reverse command; revisions20→21→22; viewer leaves geometry/revision/selection unchanged; undo restores all boxes | live-layout-viewer-undo-fixed.json |
| Same organization/view/undo with orbit enabled | Same one-revision transaction and exact round trip with canonical hold conversion enabled | live-layout-viewer-undo-orbit.json |
| External edit before undo | Refused stale entry does not overwrite the external geometry or add a revision; visible feedback | live-stale-undo.json |
| Registered PNG/text + agent + artifact/Back + completion/restart | Actual PNG payload naturalWidth128; canonical explains Artifact opens real text; Back returns to running agent; public completion refreshes; Core restart becomes truly unknown while durable mission remains | live-artifacts-agent-states.json |
| Actual Core job Stop + main-chat Ask | One actual `/api/jobs/cancel`; JobService becomes cancelled; true outcome inside dialog. Hydrated existing draft retained and target appended; no turn or Voice-switch POST | live-stop-ask.json |
| Registered native text wheel/layout | Actual wheel scroll280px; same native DOM and scroll280 after layout; scene revision20 unchanged, zero scene POST, selection/boxes retained | live-document-scroll.json |

The group baseline was independently reproduced before S05: three
`set_geometry` writes, revision20→23. Its separate
`live-group-drag-baseline.json` is retained. The corrected scenario now proves
the shared hold commit seam in the actual page, not merely an old static test.

The agent's running/completed/unknown observations are deliberate canonical
facts in this sandbox. The separate real CLI attempt was honestly quota
blocked; see `trace-analysis.md`. This report does not claim a successful
real-model execution or full React/Remotion rendering.

## Execution history and harness corrections

All invocations used the main venv Python from mov3, with
`-m pytest <S05>/qa/test_live_acceptance.py -q --assert=plain --tb=short`.
Artifacts include exact JUnit results rather than hiding preparatory failures:

- Initial seven-case run: **3 passed,4 failed in90.72s**
  (`live-acceptance-junit.xml`). Failures were prepared-harness assumptions:
  S05 native document provider uses `.scv-document`, rather than the shell's
  text-only `.jvov-text`; explains source must be canonical `kind:artifact`,
  rather than a window; an existing-draft test must wait for conversation
  hydration before typing, rather than reading the initial editable DOM.
- Affected four-case rerun after those corrections: **3 passed,1 failed
  in60.91s** (`live-acceptance-corrected-junit.xml`). Fixed/orbit layout and
  Stop/Ask passed. Remaining assertion read the agent's initial
  `data-status=unknown` placeholder while its public read was still loading.
- Tightened the unknown predicate to the rendered public status, added actual
  native-text scroll/layout proof, and reran group under the corrected
  canonical Artifact seed: **3 passed in42.97s**
  (`live-final-artifact-scroll-group-junit.xml`). No product edits were made by
  QA. Only affected/new scenarios were rerun.

Final evidence JSON files above contain zero browser Runtime exceptions.
I visually inspected the real documents, scrolled documents, unknown agent and
cancelled job screenshots: contained controls/panes, readable public content,
honest unknown duration, and cancellation feedback visible in the native
top-layer surface. `live-documents.png`, `live-documents-orbit.png`,
`live-document-scroll.png`, `live-agent-unknown.png`, `live-job-stopped.png`.

## Remaining verification

The scoped stale-conversation prefill finding is being fixed separately. Only
that rework diff and its focused regression/prefill scenarios need verification
before the S05 recommendation is finalized. PM owns orchestration/acceptance.
