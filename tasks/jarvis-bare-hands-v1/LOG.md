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
  Thumb-index gap (its floor sits above the pinch `releaseRatio` of 0.42 so a
  pinch in progress can never wake) and index reach from the wrist (which is
  what rejects a fist — its thumb-index gap lands inside the band). Both ends
  soften over `wakeSoft` of the range, so a borderline posture scores low and
  simply never completes its hold instead of flickering.
  **`wakeGapMin` 0.46 / `wakeGapMax` 0.85 / `wakeIndexMin` 1.35 are the score's
  zero-crossings, not the wake thresholds** — this LOG, the contract doc and
  Slice 02's commit message all quoted them as if they were. Because the ends
  soften and `wakeScore` 0.5 must be sustained, the band that actually holds is
  **gap ∈ [0.499, 0.811], reach ≥ 1.485** — `wakeGapMin + s·wakeScore` …
  `wakeGapMax − s·wakeScore` and `wakeIndexMin·(1 + wakeSoft·wakeScore)`, with
  `s = (wakeGapMax − wakeGapMin)·wakeSoft = 0.078`. **That is what Slice 08
  calibrates**; the reach figure was 10 % off. A sweep re-derives it and
  compares it to the published table
  (`test_the_band_that_actually_sustains_a_hold_is_the_one_documented`).
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

## 2026-09-19 — Slice 02 rework, implementation agent

- **A hold detector must never credit time it did not observe.** `dt` was the
  unbounded wall-clock gap between the two most recent `update()` calls, so
  **two held samples 60 s apart completed the one-second hold** and Bare Hands
  entered ACTIVE and started firing synthetic clicks. Two live routes, both
  reachable without a bug anywhere else: a frozen camera (the watcher
  early-returns on `time === lastVideoTime` *before* calling the detector, so
  the was-holding flag survives the whole stall) and a backgrounded tab or a
  closed lid (RAF stops, `performance.now()` does not). **The fix is to read a
  gap beyond `wakeGraceMs` as the loss it is, not to clamp the credit at
  `wakeGraceMs`.** Clamping neutralises the 60 s case and passes every test,
  but it still pays for unobserved time, it lets a hold be assembled from
  samples minutes apart, and it still cannot draw decision 5's ring. The
  invariant above `createWakeDetector` already said *d'affilée* — consecutively
  — and a gap and an explicitly-not-held sample are the same absence of
  evidence, so they get the same tolerance. **Any future hold/dwell/long-press
  in this repo inherits this**: bound the clock against observation, not
  against a number.
- **Two overlapping mechanisms, on purpose.** The detector bound catches a
  stopped frame loop; the watcher now declares a stalled video clock instead of
  returning in silence, so the ring keeps telling the truth during a freeze
  rather than sitting on a progress nothing feeds. Neither can be stuck the way
  the other can.
- **The published wake thresholds were the score's zero-crossings.** The commit
  message, the contract doc and this LOG all quoted `wakeGapMin` 0.46 /
  `wakeGapMax` 0.85 / `wakeIndexMin` 1.35 as the wake band. They are where the
  score reaches **zero**. Because both ranges soften over `wakeSoft` and
  `wakeScore` 0.5 must be sustained, the band that actually holds is
  **gap ∈ [0.499, 0.811], reach ≥ 1.485** — `wakeGapMin + s·wakeScore` …
  `wakeGapMax − s·wakeScore` and `wakeIndexMin·(1 + wakeSoft·wakeScore)` with
  `s = (wakeGapMax − wakeGapMin)·wakeSoft`. **Slice 08 calibrates that band**,
  and a sweep now re-derives it and compares it to the published table.
- **`!== OFF` was two questions wearing one predicate.** "Bare Hands works"
  (`isLiveState` / the contract's `isLiveLifecycle`) excludes ERROR — otherwise
  switching off after a refused camera announces « caméra libérée » over
  « Caméra refusée ». "Something is held and must be released"
  (`isEngagedState`) **includes STARTING**, because cancelling an in-flight
  start is exactly what releases the camera that is on its way. Converting the
  three browser call sites to the live predicate, as the review suggested,
  would have silently broken the audited 18-path camera release. Two names, two
  jobs.
- **A name that promises validation must perform it.** `usableHand` checked
  `landmarks.length > 9` and never looked at the entries, so one undefined
  landmark threw inside `cPoseScore` and `tick`'s catch converted it to
  `tracking_failed` — full teardown, ERROR, 9 s toast, for a single frame. It
  also disagreed with the token path (`> 8`), while decision 7's 30 s timer
  re-arms on tokens: two definitions of "usable hand" in one controller. One
  `usableLandmarks` now, validating the four points actually read.
- **The overlay is not the tracker.** `teardown` wrapped every consumer call;
  the lifecycle transitions did not, so a throwing overlay surfaced as
  `tracking_failed` / `start_failed` — a cause invented in place of the real
  one. It carries `overlay_failed` now, and the contract owns the whole failure
  vocabulary (`FAILURE_CODES` / `isFailureCode`) with parity tested in both
  directions, so a code cannot be published without being documented.
- **A figure promised on screen belongs in the contract.** `wakeIntervalMs`
  200 (the "5 images/s") lived only in the engine defaults, and the budget test
  passed it as an explicit override — mutating the default to 500 left all 13
  tests green. `WAKE_INTERVAL_MS` joined `SLEEP_TIMEOUT_MS` / `WAKE_HOLD_MS`,
  the panel computes its sentence from it, and the default is covered.
- **`settings.sleepTimeoutMs` is exposed and inert.** Normalised and persisted,
  but the controller takes `SLEEP_TIMEOUT_MS`. **Slice 07 owns settings** and
  must wire it; until then nothing may assume it is live. Recorded in the
  contract, the module and the settings table.
- **`getUserMedia` cannot have a deadline** — behind it is a permission prompt
  a human takes as long as they like to answer. So STARTING gets the other half
  of Rule Zero instead: it says how long it has been waiting and that the
  switch above cancels it. It no longer renders as « Éteint » under a button
  that returned `starting` without awaiting the start and settled in SLEEP.
- **Untouched on purpose**, per the review's verified-sound list: the 18-path
  camera release, the SLEEP frame budget, the wake-once latch, the
  un-farmable grace window, the 30 s ordering, ERROR semantics, and the two
  strengthened pointer tests. Also carried forward, not fixed: SLEEP's 60 Hz
  RAF loop and the per-frame `viewport()` layout read.
- **Still open for Slice 11 runtime validation**: a flat hand with fingers
  together and the thumb adducted may land inside the effective band and wake
  after a genuine second. The synthetic fixture is axis-aligned at aspect 1;
  the device runs 640×480.

Tests, foreground chunks: baseline 1 (barehands + scene logic) **129 passed**
(124 before, five new test functions); baseline 2 (control centre + settings)
**221 passed**. Each new test was mutation-checked against the defect it
targets.

## 2026-09-19 — Slice 03, implementation agent

Identité de main persistante, filtrage adaptatif et traits de mouvement, dans
les deux modules existants — **aucun module de page ajouté, donc F3 ne
s'applique pas** et l'ordre `contracts → barehands → scene page` est intact.
Le moteur est dans `jarvis/runtime/control_center_barehands.js`
(`createHandTrackManager`, `createPointerFilter`, `createStillness`,
`handQuality`, `usableQuality`, `createHandTracker` réécrit) ; le contrat gagne
`HAND_QUALITY_FLOOR` / `isUsableQuality` / `createMotionSample` /
`adapters.motionFromCoreToken`. Couverture :
`tests/unit/test_barehands_tracking_js.py` (10 tests) plus un test de cycle de
vie. Contrat lisible : `docs/barehands-contracts.md` §3 bis.

Découvertes durables pour les Slices suivantes :

- **La dérivée interne d'un filtre One Euro n'est pas une vitesse.** Publiée
  telle quelle — ce qu'a fait mon premier jet — elle lit **1 400 px/s pour une
  main à 900**, et jusqu'à **40 px/s sur une main immobile** qui tremble de
  trois pixels. La formule publiée mesure sa dérivée contre sa **propre sortie
  précédente**, qui traîne : elle lit donc la vitesse *plus* le retard divisé
  par dt. C'est un signal de commande — il sert à ouvrir la coupure — et rien
  d'autre. `vxPxPerSec` / `vyPxPerSec` sont la dérivée du **point filtré**,
  relissée au même `dCutoffHz` : 899 px/s mesurés pour 900 réels, et ≤ 5,5 px/s
  au repos. **Les Slices 04-06 en dépendent directement** : avec la dérivée
  interne, `stillness` n'aurait jamais valu 1 (40 > `stillSpeedPx` 28) et
  aucun clic ne se serait distingué d'un glissement.
- **La porte d'appariement se juge sur la distance seule, jamais sur le coût.**
  La latéralité entre dans le coût (prime `handednessBonusPalms` 0,35) mais pas
  dans la porte (`matchRadiusPalms` 1,6). C'est cette séparation, et le fait
  que la prime reste **sous** la séparation typique de deux mains, qui fait
  qu'une étiquette qui bascule ne peut pas voler une identité. Monter la prime
  à 1,2 suffit à rendre le vol possible — il y a un test de mutation pour ça.
- **L'attribution minimise le coût total, pas la meilleure paire d'abord.** Au
  croisement de deux mains, le glouton prend la paire la plus proche et impose
  la pire à l'autre. Recherche exhaustive, légitime parce que `MAX_HANDS` vaut
  2 ; au-delà de quatre détections l'image **se refuse** (`tracking_failed`)
  plutôt que de laisser une factorielle grandir en silence. Une Slice qui monte
  `numHands` doit remplacer la recherche par un algorithme hongrois.
- **La prédiction de vitesse est ce qui tient le croisement**, pas la distance.
  À l'image du croisement, chaque détection est plus proche de la dernière
  position de *l'autre* piste. `predictMs: 0` fait échanger les deux identités,
  donc les deux `pointerId`, les deux pincements et les deux captures.
- **Purger les pistes mortes AVANT d'apparier, jamais après.** Purger après ne
  regarde que les images reçues : une boucle d'images arrêtée (onglet en
  arrière-plan, écran rabattu, caméra figée) ne purge rien, et la première
  image du retour retrouve une piste vieille de dix secondes encore posée là où
  la main était — **ressuscitée avec sa capture**. Troisième occurrence de la
  leçon de la Slice 02 dans ce module (les deux autres : le filtre repart
  au-delà de `filterResetMs`, `stillMs` ne crédite pas un intervalle non
  observé). **Formulation générale : toute grâce se compte contre
  l'observation, pas contre le nombre d'appels.**
- **Le repère d'identité est le centre de la paume, pas le bout de l'index.**
  L'index parcourt plusieurs paumes pendant un pincement : associer dessus
  ferait lire une main qui pince comme une main qui saute, c'est-à-dire comme
  une autre main. Le jeton, lui, suit toujours l'index — les deux points ont
  deux rôles.
- **`quality` est le minimum de ses témoins, pas leur moyenne.** Échelle,
  cadrage, complétude, continuité. Une moyenne laisse trois bons chiffres
  cacher celui qui dit que la main sort du cadre, et c'est précisément
  celui-là qu'il fallait lire — la mutation « minimum → moyenne » fait tomber
  trois tests. Le **score de latéralité du traqueur n'y entre pas** : il répond
  à « suis-je sûr que c'est une main *gauche* », pas à « suis-je sûr que c'est
  une main » ; une main vue de profil a une latéralité ambiguë et des points
  parfaits.
- **La bande de cadrage est étroite (4 %) exprès.** La marge de `toScreen`
  (12 %) existe pour qu'on puisse viser le bord de l'écran : une qualité qui
  s'effondrerait là endormirait une session en plein usage — une panne pire que
  celle qu'on corrige. Même raison pour un plancher bas (0,25) : il écarte une
  main devinée, pas une main mal placée. Une main qui vient d'apparaître vaut
  1/3 et **compte**.
- **L'approximation de la décision 7 est fermée.** Le minuteur de 30 s se
  réarme sur `usableQuality(token.quality)` et non plus sur « un jeton
  existe ». Ce que la Slice 03 n'a **pas** fait, à dessein : les clics et le
  survol ne sont pas filtrés par la qualité — l'intention appartient aux
  Slices 04/05, qui lisent `quality` et `stillMs` ; et le guetteur de `SLEEP`
  ne lit pas la qualité, son budget d'images est intact. Conséquence observée
  en écrivant le test : un C tenu hors cadre s'endort à 30 s puis **se réveille
  aussitôt**, les deux mécanismes étant indépendants. À trancher par la
  Slice 08 ou la validation runtime de la Slice 11, pas ici.
- **Un changement de comportement invisible est un défaut.** Le plancher de
  qualité fait arriver la veille alors que l'utilisateur voit son jeton. Le
  jeton sous le plancher se dessine donc **pâle et pointillé**
  (`.jh-token.faint`) et la pastille compte les mains crues à part
  (« MAINS · 1/2 ») — un chiffre exact et une information fausse était le
  risque. Une qualité **absente** (jeton posé à la main depuis la console)
  reste crue : c'est la règle d'absence du contrat.
- **`smoothing` est retiré, pas laissé inerte.** `options()` lève un
  `RangeError` nommant son remplacement. Un réglage sans effet serait
  indiscernable d'un réglage appliqué — le défaut même que la reprise de la
  Slice 01 a chassé partout ailleurs. Trois tests le passaient ; ils ont été
  mis à jour en place.
- **Les identifiants de piste sont des entiers à partir de 0.** Le correctif
  `trackId()` de la reprise de la Slice 01 est désormais exercé pour de vrai :
  `slots.retain([0,1])`, `allocator.slot(0)` et
  `handFrameFromMediapipe(result,{trackIds:[0,1]})` voient tous `0` et le
  gardent. `createHandTracker().update()` rend `trackIds` aligné sur
  `result.landmarks`, trous compris — **c'est l'entrée du `HandFrame` neutre
  pour la Slice 06**.
- **Le jeton porte trois couples de coordonnées, et les trois servent** :
  `rawX/rawY` (traqueur), `filteredX/filteredY` (filtre), `x/y` (affichage et
  visée — le filtré, ou l'ancre gelée pendant un pincement). Pendant un
  pincement `x/y` ne dit plus rien de la main : la Slice 08 doit mesurer
  `jitterPx` sur l'écart brut ↔ filtré, jamais sur `x/y`.
- **`lostGraceMs` (250 ms) est devenu la grâce d'identité.** Un seul nombre
  décide combien de temps une main perdue reste la même main, et l'état par
  main (pincement, filtre, ancre) vit exactement aussi longtemps que son
  identité — une horloge au lieu de deux qui se répondaient à quelques
  millisecondes près.
- **Quinze réglages nouveaux, tous épinglés** par
  `test_the_controller_states_and_timings_still_match_the_contract` et
  republiés dans `docs/barehands-contracts.md` §3 bis. Leçon N4 de la
  Slice 02 : un défaut que personne n'affirme se mute sans rien faire tomber.
  Seul `qualityFloor` est partagé avec le contrat. **La Slice 08 calibre ces
  nombres** et `window.JarvisBarehands.diagnostics()` est ce qu'elle lira.
- **Le bloc navigateur avait zéro test ; il en a un.** Un harnais de DOM
  minimal (30 lignes) vide le cache de `require` et recharge le module avec un
  `window`, ce qui installe la surimpression. Toute Slice qui touche
  `createOverlay` / `createInteraction` peut le réutiliser.

Tests, chunks en avant-plan : nouveau fichier **10 passed** ; baseline 1
(barehands + scene logic) **130 passed** (129 avant, un test de cycle de vie
ajouté) ; baseline 2 (control centre + settings) **221 passed**. Aucune
régression. Neuf mutations vérifiées, chacune reprise par le seul test visé :
`predictMs`→0, `handednessBonusPalms`→1,2, `betaCutoff`→0, `minCutoffHz`→12,
purge après appariement, latéralité comme porte, qualité minimum→moyenne,
décision 7 réarmée sur n'importe quelle main, vitesse publiée depuis la dérivée
interne — plus deux sur le bloc navigateur (classe `faint` retirée, pastille
qui cache le compte des mains non crues).
