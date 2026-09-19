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

## 2026-09-19 — Slice 01, implementation agent

Contracts and schemas landed as one pure module,
`jarvis/runtime/control_center_barehands_contracts.js`
(`window.JarvisBarehandsContracts`), documented in `docs/barehands-contracts.md`
and covered by `tests/unit/test_barehands_contracts_js.py` (15 tests). No engine,
no visible behaviour change: the click experiment is byte-identical for a single
hand.

Durable discoveries for later Slices:

- **Pointer identity is now a range, not a literal.** `POINTER_ID_BASE = 9001`
  is slot 0, so one hand is exactly what it was; the second hand finally gets
  `9002` instead of speaking under the first hand's identity. Consumers must
  call `isBareHandsPointerId()` — a test forbids the literal `9001` in
  `control_center_barehands.js`, `control_center_scene_page.js` and
  `control_center.html`. F2 is closed: both scene-page consumers moved in this
  Slice.
- **Zones are modelled by sides, not by axes.** A corner controls two *sides*;
  two corners "share an axis" (decision 17) when they pull on the same side
  (bottom-right + top-right both hold the right side), not merely because both
  constrain x and y. Modelling them as axis sets made decision 17 undecidable
  and neutralised opposite corners, which must stay a free two-axis resize.
  `ZONE_SIDES` / `SIDE_AXIS` / `combineCaptures` in the contract module.
- **A CSS selector cannot read the contract.** `#jarvisHands .jh-badge` in
  `control_center_scene_page.js:819` and the whole Bare Hands style sheet stay
  literal — `test_scene_renderer_logic` parses that sheet as text. Agreement is
  enforced by `test_the_style_sheets_agree_with_the_dom_names_the_contract_owns`
  instead. Slice 06 must keep that test in mind before renaming anything in
  `DOM`.
- **Careful with backticks in `control_center_scene_page.js` comments.** Its
  style sheet is a JS template literal; a back-quoted identifier inside a
  comment there terminates the literal and breaks every node test that requires
  the module (42 failures, one character).
- **`GET /api/barehands` now announces `schema_version`** (`barehands_test_mode.SCHEMA_VERSION = 1`).
  The route still accepts only `enabled`; `toServerPayload()` is the sole path
  to it. Slice 07 must raise both versions together when it widens the payload.
- **Two page modules now share a registration ordering constraint**:
  `…_BAREHANDS_CONTRACTS_JS__` → `…_BAREHANDS_JS__` → `…_SCENE_PAGE_JS__`, and
  `confirmInertCandidate` in `control_center.html` calls the contract, so the
  contract must stay ahead of everything. Asserted in the new test file.

Tests, foreground chunks: new file 15 passed; baseline 1 (barehands + scene
logic) 94 passed; baseline 2 (control centre + settings) 221 passed; adjacent
scene/timeline suites 46 passed. No regression.
