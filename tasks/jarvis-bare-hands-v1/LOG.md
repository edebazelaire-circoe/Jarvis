# Execution log

Reserved for implementation agents. Record durable discoveries, decisions, migrations, validation evidence, and handoff notes here during execution. Do not treat this planning file as evidence of completed work.

## 2026-09-19 — Slice 00, agent 0

Branch `task/jarvis-bare-hands-v1` from `origin/main@6af6df91`, which is exactly the handoff's planning snapshot: zero drift. Handoff mirrored from Drive into `tasks/jarvis-bare-hands-v1/` as `S0` (`2550271`).

Blind audit done. Readiness recorded in `slices/00-project-manager/READINESS.md`, state **`HUMAN_DECISION_REQUIRED`** pending D1 (Task Type waiver), D2 (voice entry points have no substrate) and D3 (which representations accept edge/corner manipulation).

Durable discoveries, detailed in READINESS.md:

- **F1** No voice command registry or intent router exists. In the default `continuous_brain` architecture the Realtime surface gets zero tools, so voice must route through the brain over MCP, and no brain→page delivery channel exists for Bare Hands.
- **F2** `pointerId 9001` is a cross-module contract: `control_center_scene_page.js:1874,1726,819` and `control_center.html:2075` all depend on Bare Hands DOM/pointer identity. Replacing it is not a Bare Hands-internal refactor.
- **F3** New JS modules must be registered as markers in `control_center.py` + `control_center.html`, with load order asserted by tests. No Slice mentions this.
- **F4** "Frames" are scene objects; move/resize geometry already exists as pure functions in `control_center_scene_interact.js`, in scene units (±160×±90), not pixels.
- **F5** Bare Hands creates the "Expérimental" settings tab that `control_center_scene_settings.js` depends on; and `barehands_test_mode` is deliberately kept out of `/api/settings` behind its own hot-write route.
- **F6** No LogBroker in this repo — emit through `RuntimeJournal` to `runtime/trace.jsonl`; register benchmarks in the existing `jarvis/testlab/` harness.
- **F7** Clean-room boundary is structurally enforced by the six-name asset whitelist; V1 touches no hashed upstream file.

Baseline on `origin/main@6af6df91`, foreground chunks: 94 passed (barehands + scene logic) and 221 passed (control centre + settings). 315 passed, 0 failed. Host RAM ~2.9 GB free; node v24.18.0 present; MediaPipe assets complete.

Drive folder still in `to-do`: the connector cannot move folders, so the Human must move it to `current`.
