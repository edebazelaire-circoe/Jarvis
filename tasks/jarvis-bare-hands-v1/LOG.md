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

## 2026-09-19 — Slice 02, implementation agent

OFF/SLEEP/ACTIVE lifecycle and the C-pose wake flow landed in the two existing
Bare Hands modules — no new page module, so **F3 does not apply to this Slice**
and the load order `contracts → barehands → scene page` is untouched. New
engine functions are all in `jarvis/runtime/control_center_barehands.js`
(`cPoseScore`, `createWakeDetector`, `STATE`/`STATES`, a rewritten
`createController`), covered by `tests/unit/test_barehands_lifecycle_js.py`
(13 tests, injected clock, no sleeps).

Durable discoveries for later Slices:

- **`LIFECYCLE` has a fourth name: `ERROR`.** Three states silently erased
  camera failures: `lifecycleOfControllerState('error')` returned `'off'`, so a
  refused camera, a busy webcam and missing MediaPipe assets all read as "the
  user turned it off". `ERROR` means *stopped without being asked*. It holds
  nothing — `teardown` runs before it is published — and the specific reason
  survives beside it in the status `code` (`camera_denied`, `camera_busy`,
  `camera_ended`, `camera_missing`, `assets_missing`, `tracking_failed`), never
  flattened into the state. Recovery is an explicit re-enable; `activate()`
  from `ERROR` powers on first. Added `LIVE_LIFECYCLES` / `isLiveLifecycle()`
  because `!== OFF` now means "running **or** broken" and would read a failure
  as a working system. Every later Slice that switches on the enum must handle
  four cases.
- **Powering on lands in SLEEP, never in ACTIVE.** `enabled` still means "not
  OFF", so the server payload is untouched (Slice 07 still owns widening it).
  Interaction requires an explicit wake: the C-pose, the new
  "Activer l'interaction" button in the Expérimental tab, or
  `window.JarvisBarehands.activate()`. **Slice 12 should call
  `window.JarvisBarehands.activate()` / `.sleep()` / `.lifecycle()`** rather
  than the controller: they carry the busy flag, the error surface and the
  panel refresh.
- **The pure block still cannot read the contract**, so `DEFAULTS.wakeHoldMs`
  and `DEFAULTS.sleepTimeoutMs` restate `WAKE_HOLD_MS` / `SLEEP_TIMEOUT_MS`,
  and `STATE` restates `LIFECYCLE`. A parity test
  (`test_the_controller_states_and_timings_still_match_the_contract`) is what
  forbids the drift; the browser block additionally passes the contract values
  into `createController({options:…})`. Any Slice adding a shared constant to
  the core owes that test a line.
- **The wake posture is two palm-relative measurements, not a classifier.**
  Thumb-index gap in `[0.46, 0.85]` palms (the floor sits above the pinch
  `releaseRatio` of 0.42 so a pinch in progress can never wake) and index reach
  above 1.35 palms from the wrist (which is what rejects a fist — its
  thumb-index gap lands inside the band). Both ends soften over `wakeSoft` of
  the range, so a borderline posture scores low and simply never completes its
  hold instead of flickering. Slice 08's calibration can tune all four.
- **SLEEP is cheap by cadence, not by a cheaper model.** The controller keeps
  one RAF loop, but in SLEEP `detectForVideo` runs at most once per
  `wakeIntervalMs` (200 ms → 5 fps), and nothing else runs: no smoothing, no
  tokens, no hover, no clicks. Measured by
  `test_sleep_runs_a_fraction_of_the_inferences_that_interaction_runs`: 5
  inferences against ACTIVE's 60 over the same 60 frames. 1000 ms of hold still
  leaves five samples.
- **The 30 s idle check runs *before* reading the video clock.** Put after it,
  a frozen camera would keep ACTIVE alive forever, because the `currentTime`
  guard returns early. There is a test for the frozen camera.
- **`MESSAGES.running` is gone**, replaced by `sleep` / `active` / `woken` /
  `idle_sleep`. `lifecycleOfControllerState('running')` still maps to `active`
  so older journal lines stay readable, but nothing emits it any more.
- **Test doubles for the controller now need `overlay.watch(state|null)`** in
  addition to `render(tokens)`. `tests/unit/test_barehands_pointer_js.py` was
  updated in place: its `enable()` assertions became `sleep` plus an explicit
  `activate()`, since powering on no longer interacts.
- Per the coordinator's note, this Slice uses none of `combineCaptures`,
  `normalizeProfile` or the optional-allocator path of
  `pointersFromCoreTokens`; their rework is unaffected by it.

Tests, foreground chunks: new file 13 passed; baseline 1 (barehands + scene
logic) 109 passed; baseline 2 (control centre + settings) 221 passed. No
regression.
