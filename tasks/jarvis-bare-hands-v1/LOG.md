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

## 2026-09-19 — Slice 01 rework, implementation agent

Two independent reviews of `a0c3a75` found one defect, repeated eleven times:
**an invalid input was coerced into a plausible-looking valid output** instead
of raising the coded error the module already had machinery for. The rework
turns every one of those into a `BareHandsSchemaError` with a stable `code`.
No engine added; `control_center_barehands_contracts.js`,
`control_center_barehands.js` (two small consumer fixes), the contract doc and
the test file are the whole change.

Durable discoveries for later Slices:

- **The rule the module now states out loud: a coded refusal beats a plausible
  default.** Documented once, at the top of `docs/barehands-contracts.md`.
  *Absence* stays permitted everywhere a default has a meaning — a field
  nobody set takes its default. It is the *unknown* that refuses. Two
  deliberate exceptions, both normalising **stored schemas** rather than
  events: `normalizeSettings` / `normalizeHandProfile` still clamp
  out-of-range numbers, and `normalizeTool` still falls back to `pointer`. An
  interaction event refuses an unknown tool.
- **`combineCaptures` now returns `{mode, axes, byHand, reason}`.** `axes` is
  still the union; `byHand` is keyed by `handTrackId`, each entry
  `{sides, axes}`. It exists because the union alone **cannot express
  decision 16**: `edge:right + corner:top_right` and
  `edge:top + corner:bottom_right` returned byte-identical results while
  requiring opposite hand assignments, and the test that claimed to prove
  decision 16 passed under an implementation with no decision-16 handling at
  all. **Slice 06 reads `byHand[id].sides`** — the sides, not the axes, are
  the operative datum: two hands may legitimately hold the same axis through
  two opposite sides (bottom and top). Without it Slice 06 would re-derive
  `ZONE_SIDES` / `SIDE_AXIS` at its own call site.
- **BODY + BODY produces nothing** (`reason:'both_captures_are_body'`).
  Decision 8 was violated by a branch that fired when *either* capture was
  BODY: two hands in one window's content dragged the whole window. With one
  BODY, the move belongs to the single hand holding the zone (decision 10),
  and only that hand appears in `byHand`.
- **`handTrackId` `0` is an identity, not an absence.** Five sites used
  `String(x||'')`, so track id `0` — the first id any tracker that numbers its
  tracks emits — was destroyed and silently replaced by handedness. Two hands
  both reading `left` swap pointer ids mid-drag on the next frame. **Slice 03
  will pass integer track ids**: the helper is `trackId(value, message)`,
  rejecting only `null` / `undefined` / blank.
- **`pointersFromCoreTokens(tokens, allocator)` — the allocator is now
  required.** A fresh allocator per frame gives slot 0 to whoever is first in
  that frame's array. The old signature invited the omission and a test
  asserted it worked. Related: `retain()` keyed on `String(token&&token.id)`
  (`"null"`) while `slot()` keyed on `String((token&&token.id)||'')` (`""`),
  so one id-less token parked a phantom entry in slot 0 that `retain` could
  never evict — the next real single hand got `9002`, and the headline
  backward-compatibility guarantee was gone permanently and silently. All
  allocator entry points now normalise through the same helper.
- **The calibration profile has a third bucket, `hands.unknown`**, and
  `calibrated` reads **all seven** measured keys, derived from
  `HAND_PROFILE_DEFAULTS` itself. It read three, so a `releaseRatio`-only
  profile reported `calibrated:false` while carrying a measurement. **Slice 08
  gets both for free**: a key it adds counts automatically, and a hand the
  tracker cannot label keeps its calibration instead of losing it.
- **Units are in the names now**: `boundsPx` / `distancePx` (window pixels,
  like `clientX`), `jitterPx` (window pixels), `reachNorm` (normalised 0..1
  image coordinates, like `HandFrame` points). Scene geometry is in scene
  units (±160 × ±90) in `control_center_scene_interact.js`; a mixup in
  Slice 06 would have read as a geometry bug and been debugged in the wrong
  module.
- **Schema versions are read, not only stamped.** A foreign `schemaVersion`
  on settings or profile raises `barehands_schema_version_unsupported`. That
  refusal is the migration seam: when v2 arrives, accept the previous version
  there and convert it. Before, `{schemaVersion:99, newField:1}` came back as
  a clean v1 with the field dropped.
- **`createInteractionEvent` exists.** `INTERACTION` was ten strings with no
  factory, no payload, no refusals and no test, while six of the seven other
  structures had one. Shape:
  `{type, handTrackId, slot, pointerId, objectId, x, y, dx, dy, channel, tool,
  axes, t}`. **Slice 06 should publish through it** rather than inventing a
  local shape; `axes` takes `combineCaptures().axes` as-is.
- **Consistency beats silence when two paths disagree**:
  `handFrameFromMediapipe` sliced a third hand away while `createHandFrame`
  rejected it. The slice is gone — both refuse with
  `barehands_too_many_hands`. Unreachable while `numHands` equals `MAX_HANDS`;
  real the moment either number rises.
- **The `9001` sweep is now a glob** over `jarvis/runtime/*.js` plus
  `control_center.html`, excluding the contract that owns the range. It
  hard-coded three paths, so any module added later escaped it.
  `docs/ARCHITECTURE.md` no longer names the literal either.
- Slice 02's `LIFECYCLE.ERROR` was left exactly as `4fc9aa8` landed it; this
  rework only kept the doc consistent with it.

Tests, foreground chunks: baseline 1 (barehands + scene logic) **124 passed**
(122 before, two new test functions); baseline 2 (control centre + settings)
**221 passed**. No regression; Slice 02's 13 lifecycle tests untouched.
