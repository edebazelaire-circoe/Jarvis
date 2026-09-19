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

- **L'ordre de la liste n'est pas une identité non plus.** Rien ne promet que
  le traqueur rende ses mains dans le même ordre d'une image à l'autre :
  l'appariement porte sur **toutes** les paires, pas rang par rang. Apparier
  par position dans le tableau fait tomber le test dédié.

Tests, chunks en avant-plan : nouveau fichier **11 passed** ; baseline 1
(barehands + scene logic) **130 passed** (129 avant, un test de cycle de vie
ajouté) ; baseline 2 (control centre + settings) **221 passed**. Aucune
régression. Neuf mutations vérifiées, chacune reprise par le seul test visé :
`predictMs`→0, `handednessBonusPalms`→1,2, `betaCutoff`→0, `minCutoffHz`→12,
purge après appariement, latéralité comme porte, qualité minimum→moyenne,
décision 7 réarmée sur n'importe quelle main, vitesse publiée depuis la dérivée
interne, appariement par position dans le tableau — plus deux sur le bloc
navigateur (classe `faint` retirée, pastille qui cache le compte des mains non
crues).

## 2026-09-19 — Slice 02 rework (reprise), implementation agent

Trois restes de la revue de régression de `6713a4f` / `0e8fdba`, corrigés avant
la Slice 04 et commités à part.

- **Un guetteur plus lent que sa propre grâce désactive le réveil, en silence.**
  Le guetteur de veille n'appelle `createWakeDetector` qu'une fois par
  `wakeIntervalMs` : le `dt` que voit le détecteur **est** cette cadence.
  Au-delà de `wakeGraceMs`, chaque mesure arrive après un trou plus long que la
  grâce, le maintien repart de zéro à chaque image et la posture en C ne peut
  plus jamais aboutir — **0 ms crédité sur dix secondes de C parfait**. Aucune
  erreur, aucune trace, aucun test rouge : tous les tests de réveil passent la
  cadence en surcharge explicite, donc muter le défaut ne fait rien tomber. Le
  réglage livré (200/400) est sain ; c'est la *forme* qui est un piège, armé le
  jour où quelqu'un baisse la cadence pour le processeur ou où la Slice 08
  descend la grâce. `options()` le refuse désormais à la construction, à côté
  des deux invariants de paire qui existaient déjà. **`interval === grace` reste
  permis et réveille encore** : un trou *égal* à la grâce n'est pas au-delà.
  **Leçon générale, quatrième occurrence dans ce module : deux nombres dont
  l'un borne l'autre ne se règlent pas séparément — l'invariant se pose là où
  on les construit.**
- **Un refus codé dans un chemin par image vaut la fin de la session.**
  `identityOf` appelle l'allocateur par jeton et par image, dans le `try` de la
  boucle : le `barehands_hand_track_id_missing` de la reprise de la Slice 01 y
  devenait `tracking_failed` — caméra rendue, ERROR, toast de 9 s — pour un
  jeton sans identité. C'est la règle que la reprise de la Slice 02 avait posée
  côté points et laissée ouverte côté identité. **Le contrat continue de
  refuser ; c'est le consommateur qui garde.** La main reste suivie et dessinée,
  simplement sans pointeur.
- **Annuler un démarrage est un arrêt voulu, et ça se dit.** `disable()`
  demandait « Bare Hands **fonctionne** » (`isLiveState`) là où la question est
  « quelque chose est-il **tenu** ? » (`isEngagedState`). STARTING tombait du
  mauvais côté : décocher l'interrupteur pendant l'invite de permission
  n'émettait aucun toast. Or la caméra est rendue **de façon asynchrone** —
  `track.stop()` n'arrive qu'une fois `getUserMedia` résolu — donc l'utilisateur
  annulait sans aucune confirmation que la webcam s'était éteinte (RÈGLE ZÉRO).
  ERROR reste muet, ce qui était l'objet du correctif de la Slice 02.

Tests : quatre ajoutés, cinq mutations tentées, cinq tuées (retirer
l'invariant ; refuser le cas d'égalité ; retirer la garde d'identité ; laisser
`retain` non filtré ; revenir à `isLiveState`). Baseline 1 **145 passed**
(141 avant), baseline 2 **221 passed**.

## 2026-09-19 — Slice 04, implementation agent

Les deux moteurs sémantiques — gestes et intention de pincement — dans les deux
modules existants. **Aucun module de page ajouté, donc F3 ne s'applique pas** et
l'ordre `contracts → barehands → scene page` est intact. Moteur :
`handPosture`, `createGestureEngine`, `createPinchChannel`,
`createPinchIntentEngine`, `pinchRatioFor`, `createContactState` dans
`jarvis/runtime/control_center_barehands.js` ; le contrat gagne
`GESTURE_RULES` / `gestureScope` / `gestureAllowedDuringCapture` /
`isGestureSuppressed` et `PINCH_INTENT`, plus `intent` / `travelPx` /
`durationMs` sur `createPinchEvent`. Couverture :
`tests/unit/test_barehands_gestures_js.py` (12 tests) plus un test de cycle de
vie et un test du bloc navigateur. Contrat lisible :
`docs/barehands-contracts.md` § 4 et § 5.

Découvertes durables pour les Slices suivantes :

- **Le canal secondaire échappait à la garantie « un pincement ne réveille
  pas ».** La Slice 02 l'avait obtenue par construction côté index —
  `wakeGapMin` (0,46) au-dessus de `releaseRatio` (0,42), donc un pouce posé sur
  l'index sort de la bande du C. Le pouce-majeur de la décision 21 **pousse le
  pouce de côté, pas vers l'index** : mesuré, un clic droit franc laisse l'écart
  pouce-index à **0,72 paume**, en plein milieu de la bande effective
  [0,499 ; 0,811]. Conséquences réelles : **un clic droit tenu une seconde
  réveillait la veille**, et le moteur de gestes lisait « C » sur une main qui
  pince. Avec l'index écarté, la même main marque **1 en main ouverte** (quatre
  doigts tendus, pouce au large). La géométrie du C ne peut pas le dire seule :
  elle doit lire le second doigt. `cPoseScore` le fait maintenant lui-même — le
  guetteur de veille en profite donc aussi — et `handPosture` pose la règle
  générale : **une main qui pince (l'un ou l'autre canal sous `releaseRatio`)
  n'est aucune posture.** Absent du traqueur, le majeur ne change rien : il n'y
  a pas de pincement secondaire connu, donc rien à écarter.
- **Ce qui sépare les deux canaux n'est pas un seuil, c'est une marge.** Les
  deux se mesurent pareil (pouce → bout de doigt, rapporté à la paume) et
  partagent donc `pressRatio`/`releaseRatio` — un seuil propre au majeur aurait
  été un nombre de plus sans question de plus. Mais une main qui se **ferme
  entièrement** fait tomber les **deux** rapports sous le seuil : mesuré sur un
  poing, 0,18 côté index et 0,11 côté majeur. Un moteur qui regarderait chaque
  canal isolément lirait un clic droit dans un poing. La confiance d'un canal
  est donc `ramp(autre − sien, 0, pinchMarginRatio)`, nulle quand les deux se
  valent, et il faut `pinchConfidenceMin` pour descendre. C'est ce que demandait
  « rejeter la fermeture de main entière comme clic droit ».
- **Un contact ne commence pas sur une main douteuse, mais ne s'interrompt pas
  pour une note qui baisse.** `usableQuality` (décision 7) garde l'entrée en
  contact ; une main qui sort à moitié du cadre au milieu d'un glissement doit
  pouvoir le finir. Seuls un relâchement ou la perte de la main le terminent —
  et la perte donne un **`cancel`, jamais un `up`** : un `up` déclencherait
  l'action que l'arrêt vient d'interrompre. Même chose au retour en veille et à
  l'extinction (`cancelAll`).
- **L'événement ne porte pas le même point selon sa phase.** `approach` et
  `down` visent l'**ancre figée** (la cible ne glisse pas sous les doigts au
  moment de cliquer) ; `move` et `up` suivent la position **filtrée** (un
  glissement resté sur l'ancre ne déplacerait rien). Les deux voyagent donc
  séparément du jeton au moteur — `x/y` du jeton est l'ancre, `filteredX/Y` la
  main. **La Slice 06 doit lire la phase avant de croire la position.**
- **Le glissement se tranche en chemin, le clic seulement au relâchement.** Dès
  que le déplacement **maximal** depuis la descente franchit `dragSlopPx`,
  l'intention est prise et ne revient pas : une main qui repart d'où elle est
  venue a tout de même glissé (`travelPx` est un maximum, pas une distance
  courante). Le clic, lui, ne peut pas se savoir court avant d'être fini, et
  demande les **trois** témoins : durée, déplacement, et l'**immobilité publiée
  par la Slice 03**. Sans le troisième, un geste franc dont le pincement se
  ferme une image au passage se lit comme un clic — c'est la mutation
  `clickStillnessMin → 0`, et elle tombe.
- **L'arbitrage se décide à la publication, pas à la reconnaissance.** La
  posture garde sa progression pendant une capture ; sinon relâcher ferait
  réapparaître un geste à moitié construit. Ce qui est étouffé part dans
  `suppressed` avec sa raison plutôt que de disparaître : un geste qui s'évanouit
  sans trace est indiscernable d'un geste non reconnu. **`captured` est la
  couture de la Slice 06** — vide aujourd'hui, donc rien n'est étouffé.
- **La portée dit *à qui* le geste appartient, pas *qui* le fait.** `global` se
  tait dès que **n'importe quelle** main tient une capture ; `hand` seulement
  pour la sienne, la décision 12 voulant deux mains indépendantes. Sans cette
  distinction, le claquement — dont le `handTrackId` est `null` — ne serait
  **jamais** étouffé. La seule autorisation explicite est la **main ouverte** :
  une manipulation qu'on ne peut pas abandonner est un piège, et le geste
  universel pour lâcher doit marcher exactement quand quelque chose est tenu.
  Ouvrir la porte à un autre geste est une décision produit, prise dans
  `GESTURE_RULES`, pas un réglage.
- **`usableLandmarks` est paramétré, pas élargi.** La Slice 04 lit sept points
  (les trois bouts de doigt manquants) ; exiger les sept partout aurait refusé
  une main partielle que le réveil sait pourtant mesurer — une régression
  silencieuse sur le chemin de la Slice 02. Chaque moteur déclare donc ce qu'il
  lit (`USED_LANDMARKS`, `SECONDARY_LANDMARKS`, `POSTURE_LANDMARKS`) et le
  prédicat reste **unique et total** : un second argument qui n'est pas une
  liste de points (l'indice qu'un `.map` passe) retombe sur l'ensemble par
  défaut, parce qu'une exception levée là redeviendrait `tracking_failed`.
- **Le C n'est pas réimplanté.** `cPoseScore` est appelé tel quel : une seconde
  lecture aurait fait deux jeux de seuils, et la Slice 08 n'aurait pas su lequel
  calibrer. Même raison pour l'hystérésis, extraite en `createContactState` et
  partagée par le chemin de compatibilité du clic et par le nouveau flux — deux
  copies auraient donné deux hystérésis à régler et une seule documentée.
- **Trois exclusions par construction, pas trois seuils heureux** : poing contre
  main ouverte par l'extension ; C contre main ouverte par `wakeGapMax`, qui est
  *par sa propre définition* « l'écart où le score du C tombe à zéro côté main
  ouverte » ; et le pincement contre les deux par la règle ci-dessus. Aucune des
  trois ne dépend d'un réglage bien choisi.
- **L'instantané des postures se prend après la mise à jour.** Pris avant, il
  décrivait l'image précédente, et l'anneau de la **Slice 05** aurait eu une
  image de retard sur l'événement qui l'accompagne — deux chiffres différents
  pour le même instant.
- **Les moteurs ne tournent qu'en ACTIVE.** Le budget d'images de la veille
  (5 inférences contre 60) est un acquis mesuré de la Slice 02 ; la veille n'a
  qu'une question et `createWakeDetector` y répond déjà. Un test le vérifie
  maintenant sur la sortie sémantique elle-même, qui est **vide en veille** et
  vidée à chaque retour en veille — comme les traits de la Slice 03, elle ne
  doit jamais survivre à ce qu'elle décrit.
- **Le bloc pur publie à travers le contrat depuis la page.** Il ne peut pas
  lire le contrat (les tests node le chargent seul), donc il porte sa forme de
  travail et `window.JarvisBarehands.gestures()` / `.pinch()` la font passer par
  `createGestureEvent` / `createPinchEvent`. Un test fait transiter **tout** ce
  que les moteurs émettent, phase par phase, par les deux fabriques : sans lui
  les deux formes divergent en silence et la panne sort chez le consommateur.
  La **fente de pointeur** vient de l'allocateur de l'interaction
  (`interaction.slotOf`), jamais du moteur : une fente inventée volerait un
  `pointerId` à l'autre main.
- **Quatorze réglages nouveaux, tous épinglés** par
  `test_the_controller_states_and_timings_still_match_the_contract` et
  republiés dans `docs/barehands-contracts.md` § 5. Deux d'entre eux ne sont pas
  libres : `fingerCurledPalms < fingerExtendedPalms` est refusé à la
  construction (quatrième invariant de paire d'`options()`), et
  `clickSlopPx < dragSlopPx` — au-dessus, aucun contact ne pourrait rester
  indécis jusqu'au relâchement. **La Slice 08 les calibre** ;
  `gestures()`/`pinch()` sont ce qu'elle lira.
- **Ce que la Slice 04 n'a pas fait, à dessein** : elle ne dessine rien
  (décision 23 appartient à la Slice 05 — les couleurs sont dans
  `FEEDBACK_TOKENS` depuis la Slice 01, et `suppressed`/`postures`/`contacts`
  sont ce qu'il faut pour les choisir) et elle ne lie aucun geste à une action
  (Slice 06). Le défilement n'est pas décidé non plus : il dépend de la cible,
  donc le contrat fournit `travelPx`/`durationMs` et les traits de la Slice 03,
  pas la conclusion.
- **Pour la validation runtime de la Slice 11** : les fixtures sont
  synthétiques, à aspect 1 et doigts en éventail régulier. Deux nombres méritent
  d'être revus devant une caméra 640×480 — `pinchMarginRatio` (la séparation
  réelle entre index et majeur dépend de la main) et `postureScore` 0,7 sur un
  poing vu de face, où les bouts de doigt sont mal estimés parce qu'occultés.

Tests, chunks en avant-plan : nouveau fichier **12 passed** ; baseline 1
(barehands + scene logic) **159 passed** (145 avant : 12 nouveaux, un test de
cycle de vie et un test du bloc navigateur) ; baseline 2 (control centre +
settings) **221 passed**. Aucune régression. Dix-sept mutations tentées, dix-sept
reprises — cinq d'entre elles seulement après avoir renforcé les tests qu'elles
avaient traversés : la portée ignorée (le claquement anonyme n'était jamais
étouffé), le maintien créditant du temps non tenu, le C ignorant le canal
secondaire et la posture d'une main qui pince (la main synthétique tombait juste
en dehors des deux bandes — il a fallu la géométrie qui pince *dans* la bande du
C et celle qui pince avec l'index écarté), et la fenêtre du double (la purge de
la main cachait la fenêtre au lieu de l'exercer).

## 2026-09-19 — Slice 03 rework (reprise), implementation agent

Quatre retours de la QA de `8078f27`, repris sur l'arbre courant (Slice 04
comprise) et non sur les commits gelés. Les deux premiers partagent une racine :
la prime de latéralité était **soustraite au coût** d'appariement.

- **Une prime soustraite au coût est une clé déguisée.** Avec les deux
  étiquettes retournées sur la même image — ce que fait MediaPipe quand deux
  mains se recouvrent — l'appariement juste coûtait `0`, l'échange
  `(d − 0,35) × 2` : **l'échange gagnait sous 0,35 paume de séparation**
  (≈ 3 cm), et le pincement, la capture et le `pointerId` partaient à l'autre
  main — définitivement au-delà de ~330 ms, la vitesse des pistes se refermant
  sur l'erreur. La latéralité est maintenant une **clé secondaire** de
  `assign`, lue à distance totale égale ; la propriété garantie est donc :
  *la géométrie décide seule, sauf égalité des sommes à 1e-9 paume près*. Il
  n'y a plus de séparation minimale à espérer, et le test la balaie de 0,8 à
  0,02 paume au lieu de se poser à 0,8, confortablement 2,3× au-dessus du seuil
  qu'il croyait prouver.
- **`handednessBonusPalms` est retiré, pas laissé inerte** — `options()` le
  refuse en nommant ce qui le remplace, comme `smoothing` à la Slice 03. Un
  réglage exprimé en paumes était l'erreur de catégorie elle-même : une
  latéralité ne se mesure pas en distance. Le clamp d'`options()` le bornait à
  `matchRadiusPalms`, **4,5× au-dessus de la valeur dangereuse**, ce qui ne
  protégeait de rien.
- **Les coûts positifs rendent l'élagage légitime, et c'est lui le vrai
  gardien.** `if(total>=best.total)return` n'est un séparation-évaluation
  valide que si un total partiel minore le total final. Avec la prime, les
  coûts étaient dans [−0,35 ; 1,6] et la recherche jetait de vrais optimums
  (670 sur 300 000 matrices 2×2, mesuré par la QA), le même appariement
  pouvant dépendre de l'ordre des détections. L'élagage compare désormais à
  `best.total + MATCH_EPSILON`, pour que les branches **à somme égale** restent
  explorées : c'est là que la latéralité travaille. Constaté en mutant le
  comparateur pour mettre la latéralité en clé *primaire* : la plupart des
  tests passent quand même, parce que l'élagage coupe la branche avant que le
  comparateur ne la voie. La non-négativité est donc la garantie ; l'ordre des
  clés n'est que la façon de la dire.
- **Une troisième clé pour que l'ordre de la liste ne décide jamais** : à somme
  et à latéralité égales, les écarts triés du plus grand au plus petit — la
  pire paire la moins mauvaise. Sans elle, « la première attribution trouvée »
  gagnait, c'est-à-dire le rang dans le tableau. Le test d'ordre existant ne
  l'attrapait pas : son cas est symétrique. Le nouveau balaie 4 000 géométries
  quelconques, compare à une force brute indépendante, et rejoue chacune **à
  l'envers**.
- **Une étiquette absente ne vote ni pour ni contre**, même règle que le vote de
  latéralité. Compter l'inconnu comme un désaccord faisait gagner l'échange sur
  une preuve qui n'existe pas — mutation qui a d'abord **survécu**, puis tombée
  après l'ajout du cas « piste jamais étiquetée + détection sans étiquette ».
- **Le temps d'établissement de la vitesse est maintenant écrit, et chiffré.**
  `dCutoffHz` = 1 Hz donne τ ≈ 159 ms : après 900 px/s stoppés net,
  `stillness` franchit 0,5 à ~250 ms et vaut 1 à ~585 ms — c'est-à-dire que
  **`stillMs` ne commence à courir qu'à ~585 ms** ; sur une inversion franche la
  vitesse garde le **mauvais signe ~120 ms** et met ~490 ms à atteindre 90 % de
  la nouvelle. Structurel, pas un réglage raté : la même coupure basse est ce
  qui empêche le tremblement du repos de se lire comme un mouvement.
- **Ce que ça coûte au clic de la Slice 04, mesuré de bout en bout.**
  `stillness ≥ clickStillnessMin` (0,5) veut dire « vitesse publiée ≤ 224 px/s ».
  Donc un contact relâché **moins de ~250 ms après l'arrêt de la main** est
  conclu `drag` même avec 0 px de déplacement : mesuré, un tapotement de 128 ms
  juste après une approche à 900 px/s rend `drag`, `travelPx` = 1,
  `stillness` = 0,14. Un clic délibéré reste possible — la fenêtre
  `[~250 ms, clickMaxMs]` n'est pas vide, le même contact tenu 350 ms rend
  `click` à `stillness` 0,78 — mais **la fenêtre du clic commence plus tard
  qu'on ne le croyait**. Le sens de l'erreur est le bon (un faux `drag`, jamais
  un faux `click`), donc les seuils ne changent pas ici : ils sont documentés et
  testés, et `clickStillnessMin` est le seul nombre qui déplace la frontière —
  **à calibrer à la Slice 08 devant une caméra réelle**. La **position**
  filtrée, elle, ne traîne que de ~8 px refermés en deux ou trois images : qui a
  besoin de « la main a-t-elle bougé » doit lire un déplacement, pas une
  vitesse.
- **La décision 7 avait deux définitions, une de chaque côté du réveil.** Le
  minuteur d'ACTIVE se réarmait sur `usableQuality`, le guetteur de la veille ne
  lisait que la présence des points : un C tenu par une main de qualité 0,125
  réveillait, ACTIVE la refusait, et la session **cyclait sans fin** (30 s
  d'interaction, veille, réveil une seconde plus tard), détruisant toutes les
  identités et réallouant les fentes de pointeur à chaque tour. C'est le
  commentaire qu'on a rendu vrai, pas l'inverse — une définition plus large
  côté veille ne peut produire que ce cycle. `trustedHand` pose la même
  question que le minuteur ; la **continuité vaut 1** parce qu'en veille il n'y
  a pas d'identité à mettre en doute, et que la seconde de maintien du C est le
  témoin de continuité du guetteur. Le budget d'images ne bouge pas : une
  inférence par `wakeIntervalMs`, plus une boucle sur des points déjà rendus.
  La main refusée **reste dessinée**, l'anneau n'avance pas (RÈGLE ZÉRO) : la
  faire disparaître dirait « je ne te vois pas », ce qui est faux.
- **Observations laissées telles quelles, avec leur raison** : `quality` absente
  vaut 1 (règle d'absence, et le `HandFrame` neutre n'a pas de traqueur à
  interroger ; c'est la Slice 05 qui décidera d'en faire une porte) ; les deux
  limites « trop de mains » répondent à deux questions différentes (le contrat
  refuse une troisième main, le gestionnaire refuse ce que la recherche
  exhaustive ne tient pas) ; le témoin de complétude est quasi inerte face à
  MediaPipe, qui rend toujours 21 points — il garde sa valeur face à un autre
  adaptateur ; une horloge qui recule est traitée comme dt=0, ce que le filtre
  documente déjà à l'endroit où il le fait. Seule la coquille du contrat
  (`compris. sans elle,`) est corrigée.

Fichiers : `jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/control_center_barehands_contracts.js`,
`docs/barehands-contracts.md`, `tests/unit/test_barehands_tracking_js.py`,
`tests/unit/test_barehands_lifecycle_js.py`,
`tests/unit/test_barehands_gestures_js.py`.

Tests, chunks en avant-plan : baseline 1 (barehands + scene logic) **173 passed**
(159 avant : huit séparations balayées au lieu d'une, plus six tests neufs) ;
baseline 2 (control centre + settings) **221 passed**. Aucune régression.
Quatorze mutations tentées, douze reprises, **deux survivantes assumées** :
`MATCH_EPSILON` mis à 0 (tolérance purement numérique — une géométrie dont les
deux sommes diffèrent sous 1e-9 paume est une géométrie où les deux réponses
sont justes) et la porte d'appariement doublée (mutant équivalent : au-delà de
`matchRadiusPalms`, ne pas apparier coûte déjà moins cher que d'apparier, donc
la porte est une redondance volontaire — la **rétrécir**, elle, fait tomber
trois tests). Une troisième avait d'abord survécu et est tombée après
renforcement du test : l'inconnu compté comme désaccord — il a fallu ajouter le
cas « piste jamais étiquetée + détection sans étiquette », le seul où la règle
d'absence change le gagnant. Le contrôle ajouté au passage (aucun appariement
retenu au-delà de la porte) n'a pas suffi à faire tomber la porte doublée, et
c'est ce qui a montré que ce mutant était équivalent.

## 2026-09-19 — Slice 04, reprise (R1-R4, N1-N5)

La QA a piloté les **vrais** modules depuis une **vraie géométrie de points**,
ce que les tests de la Slice 04 ne faisaient jamais : chaque constat est une
mesure. Elle a aussi corrigé l'hypothèse qu'on lui avait donnée — ce n'est pas
`stillness` qui bloquait le clic, c'est `travelPx`.

**Découverte durable n° 1 — le repère d'une mesure vaut le seuil.** Le
déplacement d'un contact se lisait sur le bout de l'index, c'est-à-dire sur le
doigt qui *fait* le pincement primaire. Main strictement immobile, 1920×1080,
un pincement textbook : **39,4 px** contre `dragSlopPx` 26, et `dragSlopPx`
latche `drag` sans retour — `intent: click` était **inatteignable pour une
vraie main**. C'est le défaut que la Slice 03 avait déjà corrigé une couche plus
haut, avec les mêmes mots (« l'index parcourt plusieurs paumes pendant un
pincement »), pour l'association d'identité. Là il faisait sauter une main, ici
il la faisait glisser. Le déplacement se mesure désormais sur le **centre de la
paume** (`palmX`/`palmY`, pixels de la fenêtre, publiés par le jeton) ; le
pointeur continue de suivre l'index, parce que c'est ce que l'utilisateur vise.
Mesuré après : `click`, 0 à 8,7 px selon la taille de paume.
**La leçon générale : quand un seuil surprend, vérifier d'abord sur quoi la
grandeur est mesurée, pas la valeur du seuil.** Le même repère avait déjà
trompé deux Slices.

**Découverte durable n° 2 — un `start` et un `end` ne s'arbitrent pas pareil.**
L'arbitrage de capture s'appliquait à toutes les phases. Un `start` demande
d'agir : l'étouffer ne coûte que l'action. Un `end`/`cancel` **rend** quelque
chose sur quoi le consommateur a déjà agi : l'étouffer le laisse accroché pour
toujours. Pire, sur une perte de main le moteur étouffait le `cancel` **puis**
effaçait l'état, si bien que plus rien ne pouvait corriger. L'invariant qui
règle les deux moitiés (dont l'`end` orphelin de N3) : *tout `start` publié
reçoit exactement une phase terminale, et aucune phase terminale n'arrive sans
`start`*. Il demande deux faits distincts par posture — `started` (le maintien
est fini) et `announced` (le `start` est **parti**) — là où un seul drapeau les
confondait.

**Découverte durable n° 3 — « image malformée » se décide par lecteur, pas par
image.** Les deux canaux de pincement ne lisent pas le même bout de doigt.
L'image n'était sautée que si les **deux** étaient illisibles : perdre
exactement le doigt du canal qui tient laissait l'image passer, le canal aveugle
recevait `null`, l'hystérésis retombait à `open` et **un `up` partait**. Or
`MIDDLE_TIP` est le point le plus probablement occulté d'un pincement
pouce-majeur, le pouce étant devant. Le test d'origine coupait le doigt du canal
**au repos** : l'angle mort était le canal qui tient. Règle : *le prédicat de
sautabilité appartient au lecteur, et chaque lecteur déclare ce qu'il lit.*

**Découverte durable n° 4 — une constante à qui l'on demande deux choses
contraires n'a pas de bonne valeur.** `pinchMarginRatio` devait à la fois
écarter la fermeture de main entière et admettre un pincement primaire. Il
n'écartait le poing du dépôt que de **0,02 paume** (un poing un peu desserré
passait ; le pouce replié *en travers de la paume* — le poing le plus courant —
donnait un clic droit de confiance **1,0**) et bloquait le primaire dès que le
majeur suivait l'index à moins de 8°. Aucune valeur ne tenait les deux. La
fermeture a donc son **propre témoin** : `handClosure` = `1 − max(extension des
quatre doigts)`, la même mesure et les deux mêmes constantes que le score
`fist` — un poing *est* « tous les doigts repliés ». Garantie : quatre doigts à
`fingerCurledPalms` ou en deçà ⇒ confiance **exactement** nulle sur les deux
canaux, quelles que soient la marge et les distances. Mesuré 1,000 sur toute la
famille des poings, 0,000 sur tous les pincements francs : pleine échelle contre
0,02 paume. Libérée, la marge descend à **0,12** et admet le majeur qui suit
l'index partout sauf dans une fenêtre de deux degrés, où le bout du majeur est à
moins de 0,06 paume (~5 mm) du point de pincement — une **égalité géométrique**,
pas un artefact de seuil, et refuser y est juste : un contact sur le mauvais
canal est un clic droit involontaire.

**La fenêtre du clic, maintenant.** `travelPx` ne bloque plus rien. Il reste la
seule contrainte de la Slice 03, et elle ne s'applique qu'**après une approche
franche** : `stillness ≥ 0,5` veut dire vitesse publiée ≤ 224 px/s, ~250 ms
après une main à 900 px/s. Donc fenêtre `[~250 ms, clickMaxMs 400]` après un
geste rapide, et **aucune attente** pour une main déjà posée — mesuré
de bout en bout : clic à 144 ms, `stillness` 1. Le test de la Slice 03
(`test_a_tap_made_too_soon_after_a_fast_reach_is_read_as_a_drag`) est intact et
reste le lieu où relire cette frontière.

**Non bloquants.** N1 : la garde du C était la **seule** frontière non adoucie
d'un fichier qui adoucit toutes les autres — `return 0` sec au-dessus de
`releaseRatio`. Mesuré sur 1 152 poses en C géométriquement valides, elle en
annulait 167. C'est une rampe sur la bande que l'hystérésis possède déjà : zéro
sous `pressRatio` (le seuil où le contact **entre**, le plus proche de l'état de
contact qu'un score sans mémoire puisse lire), plein au-dessus de
`releaseRatio` ; un pincement secondaire franc reste à zéro. N2 :
`clickSlopPx > dragSlopPx` est silencieusement tronqué et se refuse désormais à
la construction — **troisième** apparition de cette classe sur cette tâche,
après `smoothing` et `wakeIntervalMs`/`wakeGraceMs` ; le contrat l'écrivait
déjà sans que le code l'applique, ce qui est la forme la plus trompeuse du
défaut. N4 : un test pilote enfin les moteurs depuis la géométrie, à travers le
traqueur et le filtre de la Slice 03, plus un second à travers le **contrôleur
entier** — c'est cette couture-là, et elle seule, qui décide *ce que* les
moteurs reçoivent, et aucun test de moteur ne peut la voir. N5 : la table
`GESTURE_RULES` se lisait à nu dans la boucle d'images ; un geste sans règle y
aurait levé en `tracking_failed`. Repli le plus silencieux possible (global,
jamais permis pendant une capture) ; le contrat, lui, refuse — c'est la bonne
réponse hors de la boucle.

**Ce qui n'a pas bougé, sur instruction et vérifié :** `createPinchDetector` et
`createContactState` ne sont pas touchés (le chemin de clic hérité, prouvé
identique sur 336 000 pas) ; l'identité reste une distance pure avec la
latéralité en clé secondaire, `handednessBonusPalms` toujours refusé ; les
dix-huit constantes de la Slice 03 gardent leur valeur. Une seule constante
change de valeur, `pinchMarginRatio` 0,18 → 0,12, reportée dans le test qui
l'épingle et dans `docs/barehands-contracts.md` ; aucune constante nouvelle —
la fermeture réutilise `fingerCurledPalms`/`fingerExtendedPalms`, la rampe du C
réutilise `pressRatio`/`releaseRatio`.

**Résidu connu, pour la Slice 08.** `clickSlopPx`/`dragSlopPx` sont en **pixels
de la fenêtre** : le même geste mesure ~3 fois plus de pixels en 1920 de large
qu'en 640. Tout le reste du fichier mesure en paumes précisément pour être
invariant. Ce n'est plus bloquant depuis que le repère est la paume (un clic sur
place vaut quelques pixels à toute résolution), mais la **tolérance** au
déplacement réel, elle, dépend de la résolution. À trancher à la calibration,
pas ici.

Fichiers : `jarvis/runtime/control_center_barehands.js`,
`docs/barehands-contracts.md`, `tests/unit/test_barehands_gestures_js.py`,
`tests/unit/test_barehands_lifecycle_js.py`.

Tests, chunks en avant-plan : baseline 1 (barehands + scene logic) **180 passed**
(173 avant, sept tests neufs) ; baseline 2 (control centre + settings)
**221 passed**. Aucune régression. Vingt-trois mutations tentées, vingt-deux
reprises, **une survivante assumée** : « fermeture inconnue traitée comme main
ouverte » (`closed===null ? 0 : closed`). Mutant **équivalent** — `handClosure`
ne rend `null` que si le poignet, la base du majeur ou tous les bouts de doigt
manquent, or un canal dont le rapport se lit exige déjà le poignet, la base du
majeur et son propre bout de doigt : la branche est inatteignable. Le repli
prudent (fermeture pleine, donc rien ne commence) est gardé pour qu'elle échoue
du bon côté le jour où elle cesserait de l'être, et `handClosure` renvoyant
`null` sans aucun bout de doigt est épinglé à part.

## 2026-09-19 — Slice 05, implementation agent

Le résolveur de cible sémantique et le retour visuel de visée. **Premier module
de page ajouté depuis la Slice 01**, donc le constat F3 s'applique :
`jarvis/runtime/control_center_barehands_target.js`
(`window.JarvisBarehandsTarget`), son couple
`BAREHANDS_TARGET_SCRIPT_FILE`/`_MARKER` dans `control_center.py`, son repère
dans `control_center.html`, et une assertion d'ordre. Le nouvel ordre est
`contracts → target → barehands → scene page` : le module lit les contrats et se
fait lire par le pointeur, donc il vit exactement entre les deux.

La géométrie et l'hystérésis sont **pures** (`targetBand`, `regionAt`,
`targetRegionsOf`, `createTargetResolver` dans
`jarvis/runtime/control_center_barehands.js`) ; le module de page ne fait que
lire l'arbre et dessiner. Le contrat gagne `feedbackRole` et trois noms de DOM.
Couverture : `tests/unit/test_barehands_target_js.py` (23 tests). Contrat
lisible : `docs/barehands-contracts.md` § 6.

Découvertes durables pour les Slices suivantes :

- **« En recouvrement » veut dire *au même point*, et c'est une contrainte de
  composition, pas une nuance de vocabulaire.** `pickRegion` classe
  actionnable → priorité → distance : appliquée à plat sur les candidates de
  **tous** les objets, elle fait gagner le coin d'un cadre situé à 11 px
  (priorité 3) sur le corps du bouton que le doigt touche réellement
  (priorité 1), la distance n'étant lue qu'en troisième. La résolution est donc
  en deux temps : *le plus proche décide quel objet, `pickRegion` décide quelle
  partie*. Mesuré et épinglé ; c'est la seule composition où les deux critères
  disent ce qu'ils veulent dire. **La Slice 06 hérite de la règle** : la
  priorité de région ne traverse jamais deux objets.
- **Le bloc pur ne réimplante pas la règle du contrat, il la reçoit.**
  `createTargetResolver` **exige** `pickRegion` et se refuse sans elle
  (`RangeError`). Le bloc pur est chargé seul par node et ne peut pas lire le
  contrat ; une seconde priorité écrite ici aurait divergé en silence de celle
  que la Slice 06 lira. C'est le troisième recours à cette forme après
  `STATE`/`LIFECYCLE` et `DEFAULTS`/constantes du contrat, mais le premier où
  l'injection remplace la recopie — préférable quand il s'agit d'un
  **algorithme** et non d'une valeur.
- **Une bande de zone a besoin de deux bornes, et la seconde ferme une
  décision.** `targetZonePx` (14 px) seul prend les deux moitiés d'une capsule
  de 24 px de haut : plus un seul pixel de **corps**, donc la décision 8
  (« BODY est de l'interaction de contenu ») inatteignable sur l'objet le plus
  courant de la scène, sans rien qui le dise. La bande est aussi plafonnée à
  `targetZoneMaxRatio` (0,3) du petit côté, et `≥ 0,5` se refuse à la
  construction. Effet de bord utile : sous 0,5, « les deux côtés d'un axe à la
  fois » devient **structurellement impossible**, donc un coin ne peut pas être
  inventé sur un objet étroit.
- **Quatrième apparition de la paire qui se règle séparément.**
  `targetZonePx` / `targetZoneHoldPx` sont l'hystérésis d'une zone, exactement
  comme `pressRatio`/`releaseRatio` l'est d'un contact. Inversées, la zone se
  perd **plus tôt** qu'elle ne se prend : l'aperçu clignote précisément là où
  l'hystérésis existe pour qu'il ne clignote pas, rien ne lève, rien ne tombe, et
  le symptôme se lit comme un tremblement de main. Refusé à la construction, à
  côté de `smoothing`, `wakeIntervalMs`/`wakeGraceMs` et
  `clickSlopPx`/`dragSlopPx`. L'égalité reste permise.
- **Un facteur 2 sur l'assistance, pour que brancher un réglage ne change
  rien.** `settings.assistance` vaut 0,5 par défaut (contrat § 9). Multiplier
  `targetAssistPx` par l'assistance nue aurait **divisé la portée par deux** le
  jour où la Slice 07 branche le champ — une régression invisible, causée par un
  câblage et non par un changement. La portée est donc
  `targetAssistPx × 2 × assistance` : 0,5 rend exactement le défaut du moteur, 0
  coupe, 1 double. **Règle générale : quand un réglage stocké multiplie une
  constante du moteur, c'est le défaut du réglage qui doit rendre le défaut du
  moteur.**
- **Décision 3 se tient par la structure de l'arbre, pas par une opacité.** Hors
  intention (aucun canal `pinching` ni `pressed`), il n'y a **aucun élément
  d'aperçu dans le DOM** — pas caché, pas transparent : absent. C'est la seule
  forme de la règle qu'un test puisse vérifier, et elle paie la performance au
  passage : `querySelectorAll` + un `getBoundingClientRect` par candidate ne
  s'exécutent que sous intention, jamais dans une session au repos. **La
  Slice 07 ne doit pas transformer ce retrait en `display:none`.**
- **`elementFromPoint` participe sans décider.** Deux objets qui se recouvrent
  rendent la **même** distance (zéro) : sans autre critère, c'est l'ordre du
  document — l'ordre de création — qui tranche, donc pas ce que l'utilisateur
  voit. La collecte cite en tête celui qu'`elementFromPoint` trouve au-dessus, et
  le résolveur lit « le premier cité » comme le contrat le fait. C'est
  exactement l'écart entre cette Slice et un survol de souris : le pixel est un
  indice, la géométrie sémantique est la réponse.
- **La représentation se déclare, elle ne se devine pas.** `sc-capsule` est la
  forme **dessinée**, qui retombe en capsule puis en point quand la place manque
  (`compactShape`, `control_center_scene_layout.js:936`). Lire les zones dessus
  ferait perdre les siennes à une fenêtre compacte, et en donnerait à une
  capsule dessinée en point. La page de scène pose donc `data-representation`
  dans `applyNodes` — **à chaque passe, et non dans `fill()`**, dont la mémoire
  de contenu ne regarde pas la représentation : un changement de représentation
  à forme dessinée constante ne rappellerait pas `fill()`. Représentation
  illisible ⇒ corps seul, l'erreur qui échoue du bon côté.
- **Un renvoi opaque plutôt qu'un réappariement sur des coordonnées.** Le nom et
  l'arrondi d'une cible ne sont pas de la géométrie et ne traversent pas le
  résolveur ; il faut donc les relire de la candidate collectée. Une cible
  **figée** n'a plus de candidate sous la main — l'objet n'est plus dans la
  portée — et le rang 0 de la collecte désigne alors un *autre* objet :
  l'étiquette annonçait ce qu'on ne tient pas, silencieusement. Le descripteur
  porte donc `ref`, et son apparence est gelée avec lui.
- **`suppressed` arrive enfin à l'écran** (RÈGLE ZÉRO). Le contrat range depuis
  la Slice 04 la raison d'un geste étouffé « plutôt que de la faire
  disparaître » ; elle n'allait nulle part. Elle s'écrit maintenant sous la
  pastille (`jh-note`), et une raison **inconnue** s'affiche telle quelle : ce
  nom est la seule information que cette ligne transporte, le remplacer par une
  phrase générique la viderait. Passé au second argument de `overlay.render`
  pour que les doubles de test existants l'ignorent sans se casser.
- **Ce que la Slice 06 consomme** : `window.JarvisBarehands.targets()`, une
  entrée par main **et par canal** (décision 21 : le clic droit est un canal),
  publiée à travers `createTargetCandidate` et augmentée de `handTrackId`,
  `channel`, `locked` et `feedback`. `createCapture({handTrackId, channel,
  state, objectId, region, zone, t})` se construit directement dessus. **`locked`
  est la couture** : la cible est dynamique tant que la main approche et **figée**
  dès la descente — objet, région, zone, cadre et nom — quoi que fasse la main.
  Sans ce gel, un glissement de 30 px changerait l'objet capturé au milieu du
  geste.
- **Ce que la Slice 05 n'a pas fait, à dessein** : elle ne touche pas au
  sélecteur `INTERACTIVE` ni au survol hérité (le contour `jarvis-hand-hover`
  reste ce qu'il était), et elle ne lie aucune cible à une action. **Résidu
  connu pour la Slice 06 ou 07** : ce contour-là, lui, n'est pas conditionné à
  l'intention — c'est le mécanisme d'hier que la décision 3 remplace, et le
  déconditionner touche le chemin de clic hérité, qu'on m'a demandé de ne pas
  déranger.
- **Résidu connu, plus faible que le reste** : il n'existe pas de harnais DOM
  pour `installJarvisScene`, donc l'écriture de `data-representation` est
  vérifiée par lecture de source (la garde, l'écriture et la **source** de la
  valeur — `node.representation` et non `node.shape`). À exercer pour de vrai à
  la validation runtime de la Slice 11.

Fichiers : `jarvis/runtime/control_center_barehands_target.js` (nouveau),
`jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/control_center_barehands_contracts.js`,
`jarvis/runtime/control_center_scene_page.js`, `jarvis/runtime/control_center.py`,
`jarvis/runtime/control_center.html`, `docs/barehands-contracts.md`,
`tests/unit/test_barehands_target_js.py` (nouveau),
`tests/unit/test_barehands_lifecycle_js.py`,
`tests/unit/test_barehands_tracking_js.py`.

Tests, chunks en avant-plan : nouveau fichier **23 passed** ; baseline 1
(barehands + scene logic) **180 passed** ; baseline 2 (control centre +
settings) **221 passed** ; suites de scène adjacentes **413 passed**. Aucune
régression. **Trente-deux mutations tentées, trente-deux reprises** — six
d'entre elles seulement après avoir renforcé les tests qu'elles avaient
traversées : les zones données à toutes les représentations et la représentation
devinée (l'étoile était sondée en son centre, où les deux réponses se
confondent — il a fallu la sonder sur son **coin**), l'indice
d'`elementFromPoint` retiré (aucun test ne passait par la collecte), l'ordre
actionnable-d'abord (la candidate non actionnable était hors de portée, donc
jamais en concurrence), l'étiquette d'une cible figée (aucun test ne faisait
partir la main hors de la collecte) et la barre de zone dessinée au mauvais
endroit (`zoneRect` n'était vérifié qu'indirectement). La trente-deuxième,
`data-representation` non posée, n'est reprise que par une lecture de source :
voir le résidu ci-dessus.

## 2026-09-19 — Slice 06, implementation agent

Le moteur de captures et la géométrie bimanuelle. **Aucun module de page ajouté**
— le constat F3 ne s'applique donc pas, l'ordre
`contracts → target → barehands → scene page` est intact — mais une **dépendance
de chargement** l'est : le bloc navigateur du pointeur lit désormais
`JarvisSceneInteract` (inséré bien plus haut), et un test d'ordre le dit.
Moteur pur : `createInteractionEngine` dans
`jarvis/runtime/control_center_barehands.js`. Géométrie : `resizeBySides`,
`manipulateBox`, `rebaseManipulation` **étendus dans**
`jarvis/runtime/control_center_scene_interact.js`. Couture de la scène :
`window.JarvisScene.frames`. Couverture :
`tests/unit/test_barehands_interaction_js.py` (26 tests). Contrat lisible :
`docs/barehands-contracts.md` § 7.

Découvertes durables pour les Slices suivantes :

- **Le seuil qui arme une manipulation n'est pas un nombre nouveau, c'est
  `dragSlopPx`.** La première version ajoutait un `manipulationSlopPx` — et donc
  une sixième paire dangereuse à refuser (`manipulationSlopPx >= clickSlopPx`,
  sans quoi un clic sur un bord déplace le cadre **et l'épingle**, puisque toute
  géométrie de l'utilisateur épingle). Or l'intention `drag` de la Slice 04
  répond déjà exactement à cette question, sur la **paume**, et la paire
  `clickSlopPx <= dragSlopPx` est déjà refusée à la construction. **La Slice 06
  n'ajoute aucune constante à `DEFAULTS`** : le seul réglage qu'elle aurait
  introduit était une question déjà tranchée ailleurs. Corollaire pour la
  Slice 08 : calibrer `dragSlopPx` déplace aussi le seuil de manipulation.
- **La paire dangereuse de cette Slice n'est pas un réglage, ce sont deux
  constantes de forme.** `clamp(v, lo, hi)` rend **`hi`** quand `lo > hi` : un
  `MAX_SIZE` passé sous `MIN_SIZE` ferait donc gagner le maximum et inverserait
  la décision 18 — une capsule réductible à rien, sans exception ni test rouge.
  Il n'y a pas de constructeur là où vivent ces constantes, donc **le refus se
  pose au chargement du module**. Cinquième occurrence de la classe sur cette
  tâche, et la première qui ne porte pas sur des options.
- **Un seul rebasage sert trois transitions.** La décision 19 nomme
  `RESIZE → MOVE`, mais le saut arrive partout où l'attribution change :
  à l'**armement** (les pixels déjà parcourus depuis la descente seraient
  réinterprétés d'un coup), quand une seconde main **entre** (`MOVE → RESIZE`),
  et quand une main **se retire**. Le moteur calcule donc une *signature* du
  plan — mode, axes, et **qui tient quels côtés** — et rebase dès qu'elle
  change. Ce n'est pas de la prudence : une main perdue puis **revenue sous une
  autre identité de piste** (au-delà de `lostGraceMs`, c'est une main neuve) qui
  reprend le même bord ne change ni le mode ni les axes. Sans le « qui » dans la
  signature, elle n'aurait jamais d'ancre et tirerait dans le vide pour
  toujours. Il y a un test pour ce cas ; la mutation qui enlève le « qui » ne
  tombe que sur lui.
- **Le corps entre dans le couple, il n'est pas filtré avant.** Premier jet : ne
  considérer que les captures de zone, puisque le corps n'est pas une poignée.
  Effet : `combineCaptures` ne voyait jamais un corps, donc les branches
  `body_is_not_a_resize_handle` (décisions 10/14) et `both_captures_are_body`
  (décision 8) étaient **inatteignables** et le moteur les réécrivait chez lui —
  exactement la duplication que le contrat existe pour empêcher. La règle d'une
  capture **seule** reste au moteur (le contrat ne parle que de couples) et elle
  dit la même chose : corps d'une capsule ou d'une fenêtre ⇒ contenu.
- **« Déplaçable seulement » ne peut pas vouloir dire « pas déplaçable ».** Une
  étoile `point` ou `signal` n'a pas de zones (décision D3), donc son **corps**
  est sa seule prise. Le prédicat demande trois choses — une étoile de la scène,
  identifiée, d'une représentation non redimensionnable — et les trois comptent :
  sans les deux premières, le corps de n'importe quel bouton du DOM passait pour
  une étoile, donc n'était **ni traîné ni cliqué**. Défaut trouvé par le test des
  interactions de contenu, pas par relecture.
- **Le déplacement d'un cadre se mesure sur la paume, le pointeur vise avec
  l'index.** Troisième occurrence de cette leçon (Slice 03 pour l'identité,
  Slice 04 pour `travelPx`). La mutation « suivre le bout du doigt » fait tomber
  le test de bout en bout : l'index parcourt un demi-palme en se refermant, donc
  le cadre partirait tout seul au moment de la prise.
- **Le clic hérité devait être retenu, pas supprimé.** `createPinchDetector` rend
  un clic à **chaque** relâchement, glissement compris : sans porte, tout
  déplacement à mains nues se terminait par un clic sur l'objet qu'on venait de
  poser, et sur une étoile déjà sélectionnée par l'ouverture de son menu. Ce qui
  est touché est la **livraison** (`interaction.click` rend `false` pour une main
  qui a conduit un cadre pendant l'image), jamais la mesure : le détecteur prouvé
  sur 336 000 pas n'est pas modifié. La porte lit une main qui **a conduit**,
  pas une main qui **tient** — le relâchement ferme la capture avant que la
  boucle des clics s'exécute, donc une porte sur les captures vivantes serait
  ouverte exactement à l'image qui compte.
- **Le corps d'une étoile n'émet aucune séquence de pointeur.** La page de scène
  lit un glissement de pointeur sur `.sc-node` comme un déplacement de cadre
  (`onPointerDown`, seuil grossier pour Barehands) : émettre la compatibilité DOM
  sur le corps d'une capsule ferait, par un autre chemin, exactement ce que la
  décision 8 interdit. Le corps d'une étoile se **sélectionne**.
- **La scène tient le cadre, elle ne le recalcule pas.**
  `window.JarvisScene.frames` réutilise `drawnBox`, `previewAt`, `holdNode` et
  `commitUserGeometry` : l'épinglage (décision 9), l'affichage optimiste, le
  bornage et les refus sont les mêmes pour la souris et pour la main. Une souris
  qui se pose sur un cadre tenu **gagne** (la tenue s'annule) ; une annulation
  rend le cadre à sa place et n'envoie rien, comme `pointercancel`.
- **Une annulation ne valide jamais une géométrie.** Main perdue, retour en
  veille, extinction : le cadre revient où il était. C'est la réponse de la
  souris à `pointercancel`, et la seule honnête quand on ne sait plus où la main
  était. **La Slice 11 doit le regarder devant une caméra** : c'est le seul
  endroit où « la caméra a cligné » coûte le geste en cours.
- **Le refus se voit.** `same_zone_rejected`, `axes_all_neutralized`,
  `frame_not_resizable` et `object_not_drawn` remontent sur la ligne qui portait
  déjà les gestes étouffés de la Slice 04, et un motif **inconnu** s'affiche tel
  quel — ce nom est la seule information que cette ligne transporte. Sans elle,
  deux mains sur la même zone sont indiscernables d'une panne.
- **Ce que la Slice 06 n'a pas fait, à dessein** : elle ne touche ni
  `createPinchDetector`, ni `createContactState`, ni l'appariement d'identité de
  la Slice 03, ni le budget d'images de la veille, ni aucune des constantes
  épinglées ; elle ne branche aucun réglage (Slice 07) ; la sélection de texte
  fine reste un **outil** (contrat § 8) et non une main nue. Résidu connu, hérité
  de la Slice 05 : le contour `jarvis-hand-hover` n'est toujours pas conditionné
  à l'intention.
- **Deux harnais de test existants ont dû apprendre un module de plus** :
  `test_barehands_target_js.py` et `test_barehands_tracking_js.py` chargent
  maintenant `control_center_scene_interact.js` dans leur double de DOM, parce
  que le bloc navigateur le lit directement. Toute Slice qui fait lire un
  nouveau module global au pointeur doit les mettre à jour en même temps.

Fichiers : `jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/control_center_scene_interact.js`,
`jarvis/runtime/control_center_scene_page.js`, `docs/barehands-contracts.md`,
`tests/unit/test_barehands_interaction_js.py` (nouveau),
`tests/unit/test_barehands_target_js.py`,
`tests/unit/test_barehands_tracking_js.py`.

Tests, chunks en avant-plan : nouveau fichier **26 passed** ; baseline 1
(barehands + scene logic) **203 passed** ; baseline 2 (control centre +
settings) **221 passed** ; suites de scène adjacentes **506 passed**. Aucune
régression. **Trente-deux mutations tentées, vingt-neuf reprises** — huit
seulement après avoir renforcé les tests qu'elles avaient traversées : le partage
du manque en deux parts égales au lieu du prorata, le canal secondaire admis dans
un couple, la signature sans « qui tient quoi », une zone refusée qui traîne du
contenu, les axes retirés de l'événement publié, un glissement annulé qui envoie
`pointerup`, une main qui vole un nœud tenu par la souris, et la scène qui valide
une boîte inchangée. **Trois survivantes assumées, toutes équivalentes** :
convertir les deux axes par `pxToUnits(...).dx` (l'échelle est unique, donc
`.dx === .dy`) ; retirer la réentrée en zone sûre de `resizeAxis` (`clampBox`
fait déjà exactement ce déplacement à taille constante — redondance volontaire,
gardée pour que l'intention soit lisible) ; et ne plus sauter `same_hand_twice`
dans la construction du couple (une main n'a qu'une capture **primaire**, donc la
branche est inatteignable — c'est un filet du contrat, et la mutation qui le rend
atteignable, « le canal secondaire manipule », tombe, elle).

## Slice 05 — reprise QA : trois défauts que la mutation ne pouvait pas voir

La leçon d'abord, parce qu'elle explique pourquoi les trois avaient traversé un
balayage 32/32 : **la mutation valide les tests qu'on a contre le code qu'on a
écrit.** Elle ne peut pas trouver une porte qu'on n'a jamais écrite, une ligne
dupliquée qu'aucun test n'exerce, ni une fixture qui ne ressemble pas au
produit. Les trois défauts étaient exactement ces trois formes-là.

- **L'hystérésis de zone valait numériquement zéro sur toute capsule et toute
  fenêtre compacte.** Le plafond proportionnel (`targetZoneMaxRatio`) bornait
  les **deux** bandes séparément, si bien que dès que `0,3 × petit côté ≤ 14`
  — tout objet sous 46,7 px — les deux `Math.min` rendaient le même nombre.
  Une capsule par défaut (240×42) : 12,60 et 12,60. Elle ne survivait que sur
  les grands objets, là où le clignotement gêne le moins. Désormais le plafond
  ne borne que la bande **tenue** (c'est elle qui décide du corps qui reste,
  donc la garantie des 40 % est intacte au pixel près) et la bande d'entrée
  s'en déduit par le rapport des deux réglages : 8,82 / 12,60 sur la même
  capsule. **La preuve était déjà dans le test de la Slice** — il affirmait
  `band == 7.2 and held == 7.2` avec un commentaire notant que la bande large
  était plafonnée pareil : constaté, écrit, conséquence non tirée. Toutes les
  fixtures zonées du fichier faisaient ≥ 110 px de petit côté. **Une fixture
  qui ne ressemble pas au produit ne peut être sauvée par aucune mutation.**
- **`createTargetCandidate` portait une seconde règle de couleur, aveugle au
  canal**, 45 lignes sous le `feedbackRole` ajouté pour être la source unique —
  et la documentation la désignait comme « le cas primaire » de `feedbackRole`,
  ce qui était impossible puisque la fabrique ne reçoit pas de canal. Seule la
  réécriture du champ par l'adaptateur rendait `targets()` juste : un
  consommateur passant par le point d'entrée **documenté** obtenait jaune
  pendant que l'écran affichait rouge. Le champ est retiré (une candidate ne
  connaît pas le canal), et l'aperçu **redemande** le rôle au contrat au lieu de
  retomber sur bleu quand il manque. Aucun test ne lisait ce champ : il était
  calculé dans un test des contrats et jamais affirmé.
- **Une cible non actionnable était résolue, publiée et dessinée.**
  `actionable` servait à *classer*, jamais à *fermer* : il n'y avait d'`if`
  nulle part. Un bouton désactivé seul sous un doigt qui pince se résolvait à
  d=0 et recevait un cadre bleu avec son nom — la promesse d'une action
  impossible, ce que le contrat interdit en toutes lettres depuis le début en la
  nommant « obligation du consommateur ». La porte est **dans le résolveur**,
  pour que `targets()` ne publie pas à la Slice 06 ce qu'elle devrait refiltrer,
  et **aussi dans l'aperçu**, parce que c'est lui que le contrat nomme et qu'il
  se laisse appeler directement.

Non bloquants tranchés :

- **N1 — une coordonnée est un nombre, pas « quelque chose qui se convertit ».**
  `Number.isFinite(Number(v))` refusait `NaN`/`undefined`/`'abc'` mais laissait
  passer `null`, `''`, `[]` et `false`, qui valent tous 0 : une main sans
  position visait le coin supérieur gauche, où il y a toujours quelque chose à
  saisir. Même classe que celle que le contrat dit corrigée pour les événements
  de pincement. Le contrôle vit **une seule fois**, dans `regionAt` ; le second,
  au-dessus de la boucle du résolveur, a été retiré — la mutation a montré
  qu'aucun test ne pouvait le distinguer du chemin normal (`if(!best)`), ce qui
  est la définition d'une ligne redondante.
- **N3 — `zoneRect` refuse au lieu de deviner.** Son dernier `return` était
  inconditionnel : un côté inconnu ressortait en « bord droit ». Latent (le seul
  appel vivant est gardé en amont), mais c'est une fonction exportée dont
  l'échec était une réponse assurée et fausse. Elle rend `null`, l'aperçu cache
  la barre et le dit une fois à la console.
- **N4 — sans objet : la Slice 06 l'a câblé depuis.** `resolver.release` a un
  appelant de production (`createInteractionEngine({onRelease})`), vérifié sur
  l'arbre courant. Le constat datait de `3eb2447`.
- **N2 — pas d'hystérésis sur le choix d'objet, et c'est un choix.** Une souris
  se comporte pareil, donc ce n'est pas une régression ; surtout, une mémoire
  d'objet collerait la visée à un objet que la main a quitté, alors que la
  mémoire de *région* ne survit qu'à l'intérieur d'un objet déjà choisi. Le gel
  au contact (`locked`) couvre déjà le seul moment où changer d'objet coûte le
  geste. À revoir si un usage réel montre le contraire.
- **N5 — l'assistance de 24 px reste battue par un conteneur, et c'est correct.**
  Un doigt **dans** un cadre est à distance 0 de ce cadre : c'est la réponse
  vraie, et la résolution en deux temps choisit ensuite la partie. Préférer la
  petite candidate contenue demanderait une règle de taille ou de spécificité,
  c'est-à-dire exactement le classement inter-objets que la résolution en deux
  temps existe pour refuser. Borne connue de `.choice`/`.acard`/`label`.

**Décision 3 est désormais tenue à l'écran.** Le contour hérité
(`jarvis-hand-hover`) s'ajoutait pour tout jeton **suivi** au-dessus d'un
élément interactif : une main qui traverse la page entourait chaque bouton au
passage. La preuve `previews().length == 0` ne parlait que du nouveau mécanisme.
Il suit maintenant l'**intention** — et seulement là où l'aperçu n'entoure pas
déjà l'élément, parce qu'un contour d'accent autour d'un cadre bleu, jaune ou
rouge ajouterait une quatrième couleur à une règle où la couleur *est* le sens
(décision 23). Quand l'aperçu est éteint (décision 24), le chemin de clic hérité
garde ainsi son seul repère, sous intention. **Le chemin du clic n'est pas
touché** : `hovered`, les fentes, `pointerover`/`mouseover` et
`createPinchDetector` sont ceux d'avant, au mot près — c'est de la présentation,
et elle a désormais un propriétaire unique (`paintHover`), au lieu d'être posée
dans la boucle de survol et retirée dans `release`.

Fichiers : `jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/control_center_barehands_target.js`,
`jarvis/runtime/control_center_barehands_contracts.js`,
`docs/barehands-contracts.md`, `tests/unit/test_barehands_target_js.py`,
`tests/unit/test_barehands_contracts_js.py`.

Tests, chunks en avant-plan : baseline 1 (barehands + scène) **229 → 235
passed** (six fixtures neuves) ; baseline 2 (centre de contrôle) **284 passed**,
inchangée ; les 26 tests de la Slice 06 passent sans modification ;
`-k "barehands or control_center or scene"` **1376 passed**. **Vingt-deux
mutations tentées, vingt-deux reprises, aucune survivante** — y compris les cinq
qui restaurent le défaut d'origine (plafond sur les deux bandes, couleur aveugle
au canal rendue à la fabrique, repli silencieux en bleu, porte
d'actionnabilité retirée, contour posé sans intention). Une survivante du
premier passage a été tuée en **supprimant** la ligne qu'elle épargnait plutôt
qu'en écrivant un test qui ne pouvait pas la distinguer.

## Slice 06 — reprise : une manipulation suspendue se rebase (R1, R2, N1-N4)

**Ce qu'une signature ne peut pas dire.** `plan.signature` est
`mode | axes | qui-tient-quels-côtés`. Elle attrape tout ce qui change
l'attribution — une main qui entre, une qui se retire, un axe neutralisé, une
main re-détectée sous un **autre** identifiant de piste (et ce « qui » est
porteur : sans lui, la main revenue n'aurait jamais d'ancre). Elle ne peut pas
dire **« ce plan n'a pas tourné à l'image précédente »**, et c'est exactement ce
que laissent derrière elles toutes les suspensions, pendant que la main continue
de voyager. Le plan porte donc maintenant le **numéro de l'image** où il a
conduit pour la dernière fois ; un trou vaut un changement de signature. Les
deux déclencheurs coexistent — le second ne remplace pas le premier.

Cinq suspensions mènent là, toutes mesurées : `same_zone_rejected` (décision
15), `axes_all_neutralized`, `frame_not_resizable`, `viewport_unavailable`
(nouveau), et **la main que le suivi perd le temps d'un clignement puis retrouve
sous le même identifiant** — 3 images perdues, 440 px plus loin, **68 unités en
une image**, sans refus et sans un mot. C'est la seule que l'utilisateur
rencontre vraiment ; les quatre autres demandent deux mains.

**Toutes les mains du couple, ou aucune.** Une main sans paume à cette image
gardait sa capture (`lostGraceMs`) et son côté servait encore d'**ancre** : le
cadre se redimensionnait de travers pendant le clignement, et `publish` sur une
paume `undefined` posait `barehands_interaction_invalid`, mot pour mot, sur la
ligne de la surimpression. La manipulation se suspend pour cette image, **en
silence** (un trou d'une image ne mérite pas une ligne qui clignote) et reprend
rebasée. C'est la même règle qui rend la publication sûre : plus aucun
conducteur sans paume, donc plus aucun garde à écrire en dessous.

**Deux mains sur une étoile déplaçable seulement.** La décision 8 argumentait
« chacune fait son interaction de contenu, plus bas » — vrai pour une capsule ou
une fenêtre, faux pour une étoile `point`/`signal`, dont le corps n'est pas du
contenu mais sa **seule** prise : la boucle de contenu la saute elle aussi
(`movesByBody`). Résultat : cadre figé, aucune interaction, `refusals == []` à
chaque image du maintien. La **première** main (la plus ancienne à la descente)
continue maintenant de déplacer l'étoile, et la seconde est un refus enregistré
(`star_moves_with_one_hand`). Une étoile `point` fait six unités : la seconde
main est presque toujours un accident sur un geste déjà en cours, et geler ce
geste punirait la main qui avait raison. Son relâchement reste un clic, comme
toute prise refusée (même règle que la décision 15).

**Un fixture irréaliste cachait le chemin de défilement en entier.** Le double
de nœud du harnais n'avait ni `nodeType`, ni `parentElement`, ni tailles de
défilement, et aucun `getComputedStyle` n'était défini : `scrollHost` sortait à
la **première** itération, `dom.scrollable()` rendait toujours faux, et les
tests affirmaient une sémantique de **glissement** pour des éléments que le
produit traite en **défilement**. Troisième fois sur cette tâche qu'un fixture
irréaliste cache un défaut. Le nœud ressemble maintenant à un élément (les
tailles suivent le rectangle, comme dans un document), et le chemin réel est
épinglé : ancêtre le plus proche, déplacement exact sur les deux axes
(500 → 470, 300 → 280), aucun double défilement, `overflow:hidden` qui déborde
**ne défile pas**, une boîte qui ne déborde que de largeur défile, et aucune
séquence de pointeur. **À emporter en Slice 11 : un double qui ne peut pas
échouer comme le vrai ne prouve rien.**

**Le reste.** Une fenêtre de scène absente ou nulle **refuse**
(`viewport_unavailable`) au lieu de retomber à 1:1 — 60 px devenaient 60 unités
au lieu de 10, six fois trop, en silence ; `frames.viewport()` a reçu la porte
`enabled` que `frames.begin` avait déjà. `actionable:false` est refusé à
`openCapture` : le résolveur de la Slice 05 est **la** porte de la décision 3,
celle-ci est une défense en profondeur, parce que ce moteur est injectable et ne
suppose pas son appelant. L'invariant des côtés doubles **se dit et se saute**
(`side_held_twice`) au lieu de lancer `tracking_failed` hors de la boucle
d'images. `step.manipulating` et `step.drove` sont supprimés : deux lectures du
même fait, de deux types, sans lecteur — `drivenHands()` est celle que le clic
hérité consulte. Le garde de source de `SIDE_AXIS` cherche désormais la
**forme** d'une table côté → axe, pas le nom. Deux mains ont enfin un test
d'identités de pointeur distinctes à travers le DOM (critère d'acceptation).

Non traités, et assumés : seul `refusals[0]` atteint l'écran (un second refus
différent dans la même image est perdu) ; le `wheel` dispatché n'a **aucun
auditeur** dans le dépôt, c'est le `scrollTop` qui fait tout le travail ;
`frames.begin` tourne avant le contrôle `frame_not_resizable`, donc le chemin du
refus ouvre puis annule un plan chaque image (inatteignable aujourd'hui).

Fichiers : `jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/control_center_scene_page.js`, `docs/barehands-contracts.md`,
`tests/unit/test_barehands_interaction_js.py`.

Tests, en avant-plan : baseline 1 (barehands + scène, dix fichiers) **235 → 244
passed** (neuf tests neufs) ; baseline 2 (centre de contrôle) **284 passed**,
inchangée ; `-k scene` **889 passed**, inchangée. **Trente-deux mutations
tentées, trente-deux reprises.** Les quatre survivantes du premier passage ont
été traitées sans remplissage : deux lignes devenues **réellement redondantes**
(`if(!drivers.length)` que l'égalité tranche déjà, `if(!anchor)continue` que
l'invariant rend inatteignable) ont été **supprimées** ; les deux autres
disaient la même absence — aucun cas d'une boîte qui **déborde sans défiler** —
et ont été tuées en ajoutant `overflow:hidden` au test, pas en assouplissant
l'assertion.

## 2026-09-19 — Slice 07, implementation agent

Outils et réglages (§8, §9, décisions 24 et 25). **Aucun module de page ajouté**
— le constat F3 ne s'applique pas, l'ordre `contracts → target → barehands →
scene page` est intact — et **aucune constante nouvelle dans `DEFAULTS`**. Le
contrat gagne `TOOL_CAPABILITY` / `SERVED_CAPABILITIES` / `describeTools` /
`SETTINGS_BOUNDS` / `SETTINGS_WIRE_KEYS` / `fromServerState` et monte à
`SETTINGS_SCHEMA_VERSION = 2` ; `barehands_test_mode.py` monte à
`SCHEMA_VERSION = 2` et accepte les neuf réglages ; le moteur gagne `setTool` et
la porte outil/cible, le contrôleur `configure`. Couverture :
`tests/unit/test_barehands_tools_settings_js.py` (15 tests). Contrat lisible :
`docs/barehands-contracts.md` § 8 et § 9 ; exploitation : `docs/OPERATIONS.md`.

Découvertes durables pour les Slices suivantes :

- **La capacité d'un outil *est* un mode de contenu du moteur, et c'est ce qui
  supprime la table de correspondance.** Premier jet : un drapeau `installed`
  écrit à la main à côté de chaque outil, plus une table
  capacité → `CONTENT_MODE` dans le moteur. Deux endroits à tenir d'accord, donc
  deux endroits pour dériver — exactement la forme que la Slice 05 a refusée en
  faisant **recevoir** `pickRegion` au bloc pur au lieu de le recopier. En
  nommant les capacités comme les modes (`scroll`, `select`), « installé »
  devient une **lecture** (`SERVED_CAPABILITIES.includes(capability)`) et non
  une affirmation, et la palette, le serveur et le moteur répondent à la même
  question par la même table. `contextual` reste à part parce que ce n'est pas
  une exigence, c'est l'absence d'exigence — c'est ce qui fait que « l'outil par
  défaut reste contextuel » n'est pas un cas particulier mais la porte d'entrée.
- **Un outil ne touche que le contenu.** Les zones (décisions 9-11) et le corps
  d'une étoile `point`/`signal` (décision D3) sont des **poignées de cadre**. La
  porte les saute explicitement : sans ça, choisir la Main faisait disparaître
  le redimensionnement et immobilisait les étoiles, en silence. La mutation
  « l'outil prend aussi les poignées » tombe sur les deux fichiers d'un coup.
- **Deux refus d'outil, deux phrases.** `tool_target_unsupported` (la cible ne
  peut pas honorer la capacité) et `tool_not_installed` (le moteur ne sert pas
  cette capacité) remontent sur la ligne `jh-note` qui porte déjà les gestes
  étouffés et les prises refusées. La mutation « une phrase générique pour les
  deux » a **survécu** au premier passage : aucun test ne lisait `noteFor`. Une
  ligne dont la seule information est *laquelle des règles a parlé* doit être
  lue par un test, sinon elle se vide sans rien faire tomber.
- **La deuxième porte est de la défense en profondeur, et elle est justifiée.**
  Un outil sans moteur est déjà refusé par le serveur et grisé par la palette ;
  il est refusé **une troisième fois** dans `openCapture`, parce que ce moteur
  est injectable et ne suppose pas son appelant — même raison que
  `target_not_actionable` à la Slice 06. Contrairement aux lignes redondantes
  supprimées aux Slices 05 et 06, celle-ci est **atteignable par un test** :
  `engine.setTool('highlighter')` suffit, et la mutation tombe.
- **Septième paire dangereuse : `sleepTimeoutMs <= wakeHoldMs`**, et la première
  que les **réglages** rendent atteignable. En dessous, la seconde de posture en
  C coûte plus cher que le temps qu'elle achète : on réveille, la veille reprend
  la main à l'image suivante, et la session cycle en détruisant à chaque tour
  les identités de piste et les fentes de pointeur — la panne que la reprise de
  la Slice 03 avait mesurée par un autre chemin. L'égalité se refuse aussi : un
  réveil qui dure exactement sa propre posture n'en est pas un. La borne basse
  du contrat (5 000 ms) est cinq fois au-dessus, donc **l'écran ne peut pas
  l'atteindre** — et c'est précisément pour ça que le refus est au moteur et non
  dans les bornes : une borne d'interface n'est pas un invariant.
- **Une paire dangereuse au seul constructeur est une paire sans garde dès qu'un
  réglage existe.** `controller.configure` repasse par `options()` en entier, à
  chaque écriture : tous les invariants de paire sont revérifiés là où le
  réglage arrive. Et `options()` lève **avant** qu'on garde le fusionné, donc un
  réglage refusé ne laisse pas le moteur à moitié changé. Les surcharges
  s'**accumulent** (`liveOptions`) : repartir de `deps.options` à chaque appel
  ferait qu'un réglage en défait un autre dès qu'ils ne voyagent pas ensemble.
- **Un réglage à chaud doit atteindre les mains déjà suivies.** Trois mutations
  ont survécu au premier balayage, toutes la même racine : mon test de
  sensibilité pilotait un `createPinchChannel` construit à la main. Il prouvait
  que les seuils font ce qu'ils disent, pas que le **réglage** les atteint — et
  trois lignes pouvaient disparaître sans rien faire tomber (le contrôleur ne
  transmettant plus au moteur de pincement, le moteur ne transmettant plus aux
  mains déjà là). Le test qui les tue part d'une vraie géométrie de main, passe
  par le traqueur, le filtre et les deux moteurs, **à travers le contrôleur
  entier**, et change le réglage quand la main est suivie depuis huit images.
  Mesuré : le même geste, 10,1 px de paume, rend `click` à sensibilité 1 et
  `drag` à 2. **Formulation générale, et c'est la même que la QA a posée à la
  Slice 06 : un réglage lu sur l'objet qu'on vient d'écrire ne prouve rien ; il
  faut le lire sur ce que la main fait.**
- **`sensitivity` divise les deux tolérances, jamais une.** N'en diviser qu'une
  produit la paire que la Slice 04 refuse (`clickSlopPx > dragSlopPx`) : à
  sensibilité 4 le réglage serait **refusé** au lieu d'être appliqué. Le test
  qui l'attrape est celui qui pousse le curseur à sa borne haute par l'écran —
  une valeur extrême légale est un cas de test, pas une curiosité.
- **Un affichage optimiste doit savoir revenir.** Un réglage est appliqué au
  moteur **avant** d'être enregistré, pour que la main suive sans attendre le
  réseau. Si l'écriture échoue, laisser le moteur sur la valeur refusée ferait
  mentir la case qu'on vient de décocher : `saveSettings` rend l'ancienne valeur
  au moteur *et* à l'écran, dit la phrase du serveur dans le bandeau, la
  journalise, et relâche tout dans un `finally`. Il rend `null` sur échec —
  rendre l'ancienne valeur ferait qu'un appelant ne peut pas distinguer un refus
  d'un succès.
- **Réinitialiser n'éteint pas la caméra.** `enabled` est reporté tel quel :
  remettre l'interrupteur à son défaut au passage couperait la webcam sans que
  rien ne l'annonce. La mutation a survécu jusqu'à ce qu'un test réinitialise
  **alors que Bare Hands est allumé** — une réinitialisation testée depuis
  l'état par défaut ne peut rien dire sur ce qu'elle préserve.
- **Deux réglages restent persistés et décoratifs, et l'écran le dit.**
  `tutorialSeen` et `calibrationEnabled` traversent la route, le fichier et la
  normalisation ; **aucun parcours ne les lit encore** (Slices 08 et 09). Un
  encadré de l'onglet l'énonce, plutôt qu'un bouton « Calibrer… » qui ne ferait
  rien : un contrôle inerte se lit comme une panne, une phrase se lit comme une
  attente. Les sept autres sont vivants, et `applyToEngine` est le **seul**
  endroit qui les porte au moteur — un réglage qui n'y trouve pas sa ligne n'a
  pas sa place dans la table.
- **« Réinitialiser le profil » (§9) n'a pas été implanté, et c'est délibéré :**
  il n'existe aucun profil de calibration persisté. Le construire ici donnerait
  deux propriétaires à la Slice 08. Le bouton porte donc le nom de ce qu'il fait
  vraiment — « Réinitialiser les réglages » — et l'écran dit qu'aucun profil
  n'existe encore à effacer. **La Slice 08 hérite du reste du § 9.**
- **La lecture de diagnostic est *absente* quand elle est éteinte, pas
  transparente.** Même règle que l'aperçu de cible à la Slice 05 : c'est la
  seule forme d'un réglage qu'un test puisse affirmer. Et elle paraît **tout de
  suite** quand on l'allume, en redessinant le dernier lot de jetons — attendre
  l'image suivante ferait d'un réglage appliqué et d'un réglage sans effet la
  même chose pendant une seconde.
- **Le serveur borne à la lecture et refuse à l'écriture.** `load` est tolérant
  (un fichier abîmé ne rend pas Bare Hands injoignable, comme
  `scene_settings.stored_gate`) ; `apply` refuse, avec un `code` stable. Une
  version de schéma **étrangère** au fichier n'est pas devinée : on n'en garde
  rien et Bare Hands reste éteint — agir sur des réglages qu'on ne sait pas lire
  est précisément ce que le refus codé existe pour empêcher. Une clé **absente**
  d'une écriture garde ce qui est enregistré, si bien que `{"enabled": false}`
  seul reste valide : c'est la raison d'être de cette route (F5), et la
  remplacer par « absence = défaut » ferait qu'un `curl` de l'interrupteur
  réinitialise huit réglages en silence.
- **Les deux moitiés du schéma sont tenues par des tests qui *exécutent* l'autre
  côté.** Un test node compare `TOOLS`, `INSTALLED_TOOLS`, les défauts et les
  bornes du contrat à leur miroir Python ; un autre construit la charge utile
  par `toServerPayload`, la passe au **vrai** `ControlCenter.save_barehands`,
  relit par `get_barehands` et la repasse par `fromServerState`. Une clé
  renommée d'un côté sort en `barehands_unknown_field`, pas trois Slices plus
  loin.
- **La couture de migration fait enfin quelque chose.** `schemaVersion: 1` est
  **converti** au lieu d'être refusé (`SETTINGS_MIGRATED_VERSIONS`) : côté page
  c'est une re-estampille, côté serveur un bloc v1 ne portait que `enabled` et
  les huit autres clés prennent leur défaut. Tout autre nombre lève toujours
  `barehands_schema_version_unsupported` — c'est là que la v3 s'accrochera.
- **Les bornes des réglages sont une table, et une table se refuse au
  chargement.** `clamp(v, lo, hi)` rend `lo` quand `lo > hi` : une borne
  inversée épinglerait tous les réglages sur une valeur unique, sans exception
  ni test rouge, et l'écran dessinerait des curseurs dont aucune position ne
  change quoi que ce soit. Sixième occurrence de la classe sur cette tâche, et
  la deuxième qui ne porte pas sur des options (après `MIN_SIZE`/`MAX_SIZE`).
- **F5 tenu en n'y touchant pas.** La Slice 07 n'enveloppe **pas** `renderTab`
  une troisième fois : elle écrit deux sections de plus dans le même
  `modalContent.innerHTML`. La chaîne reste `scene_settings → barehands`, donc
  la section de scène continue de se préfixer, et l'assertion d'ordre existante
  (`test_scene_settings_ui`) n'a pas bougé. **Toute Slice qui voudra une
  troisième surface dans cet onglet devrait faire pareil** : un enveloppement de
  plus, c'est une chaîne dont l'ordre dépend de l'insertion des modules.
- **Le double de DOM de l'onglet est construit à partir du balisage réel.** Il
  analyse la chaîne que la page écrit vraiment et n'enregistre les contrôles que
  pour `#modalContent` — les petits blocs que `refreshPanel` rafraîchit ne
  doivent pas effacer la liste, ce que le vrai DOM ne fait pas non plus. C'est
  ce double qui a trouvé le premier défaut de la Slice : `interactionView`
  n'exposait pas `setTool`, donc l'onglet aurait levé à la première ouverture.
  **Un double qui ne peut pas échouer comme le vrai ne prouve rien** — troisième
  application de la leçon sur cette tâche.
- **La palette est un groupe de boutons radio, avec le clavier qui va avec.**
  `role="radio"` sans navigation aux flèches annonce à un lecteur d'écran une
  promesse que la page ne tient pas. Un `tabindex` mouvant (un seul arrêt, sur
  l'outil actif) et les quatre flèches, qui **sautent** les outils sans moteur :
  s'y arrêter est un cul-de-sac au clavier, alors que la souris voit tout de
  suite qu'ils sont grisés. Deux mutations ont survécu au premier passage : la
  paire d'outils que mon test parcourait (`select` → droite) donnait la même
  réponse avec et sans le saut, et le `tabindex` du balisage était couvert par
  le rafraîchissement qui suit. Il a fallu la seule paire discriminante
  (`pan` → droite, qui enjambe `highlighter`) et une assertion sur le
  **premier** dessin — celui d'avant toute relecture de `/api/barehands`, qui
  peut échouer.
- **Le journal du chemin normal est testé, pas seulement celui de l'échec.**
  Chaque écriture réussie laisse une ligne `info`, chaque échec une ligne `warn`
  et un seul toast `bad` : « rien dans le journal » ne doit pas vouloir dire à la
  fois « tout va bien » et « mort ».
- **Ce que la Slice 07 n'a pas fait, à dessein** : elle ne touche ni
  `createPinchDetector`, ni `createContactState`, ni le budget d'images de la
  veille, ni la frontière unique pixels ↔ unités, ni aucune des constantes
  épinglées ; elle n'ajoute aucun module de page ; le contour hérité
  `jarvis-hand-hover` reste ce que la reprise de la Slice 05 en a fait ; et
  `highlighter`/`draw` ne sont pas inventés — la persistance, la portée et le
  comportement au défilement d'une couche d'annotation sont des décisions
  produit que personne n'a prises.

Fichiers : `jarvis/runtime/control_center_barehands_contracts.js`,
`jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/barehands_test_mode.py`, `docs/barehands-contracts.md`,
`docs/OPERATIONS.md`, `tests/unit/test_barehands_tools_settings_js.py`
(nouveau), `tests/unit/test_barehands_contracts_js.py`,
`tests/unit/test_barehands_test_mode.py`,
`tests/unit/test_barehands_lifecycle_js.py`.

Tests, chunks en avant-plan : nouveau fichier **15 passed** ; baseline 1
(barehands + scène, onze fichiers) **244 → 276 passed** ; baseline 2 (centre de
contrôle et réglages) **393 passed**, inchangée ; `-k scene` **889 passed**,
inchangée. Aucune régression. **Trente-cinq mutations tentées, trente-cinq
reprises** — huit seulement après renforcement : les trois de la chaîne du
réglage vivant (contrôleur → moteur de pincement → mains déjà suivies), la
phrase propre d'un refus d'outil, l'aperçu atteint par le réglage et non
seulement enregistré, la réinitialisation qui préserve l'interrupteur, et les
deux du clavier (la flèche qui saute un outil sans moteur, et l'arrêt de
tabulation du premier dessin). Aucune n'a été tuée en assouplissant une
assertion.

## 2026-09-19 — Slice 12, implementation agent

Slice ajoutée par l'audit de la Slice 00 (décision humaine D2). Le canal de
commandes du cerveau vers Bare Hands : `jarvis/domain/barehands_command.py`
(vocabulaire, bornes, codes), `jarvis/runtime/barehands_commands.py` (le
courtier), trois routes `/api/barehands/commands`,
`jarvis/runtime/barehands_mcp.py` (serveur stdio `jarvis-barehands`) et
`jarvis/runtime/control_center_barehands_commands.js` (le consommateur de page).

- **Le constat F1 tient toujours, vérifié sur l'arbre vivant** : aucun registre
  de commandes vocales, aucun routeur d'intention (`intent_router|voice_command|
  command_registry` : zéro occurrence dans `jarvis/`), `tools_for(continuous_brain
  =True)` rend toujours `[]`, et la surface Realtime reste interdite de
  revendiquer une action. La voix n'a donc **qu'un** chemin, et c'est celui-ci.
- **Le courtier vit dans le Control Center, pas dans Core.** Le précédent
  (`capture_request`) passe par Core parce que la scène **est** un objet de
  Core. Bare Hands n'existe nulle part dans Core : ni interrupteur, ni réglages,
  ni page. Y faire voyager la commande aurait demandé des routes `/v1/…`, un
  client protocolaire et un relais, pour trois sauts de plus et zéro
  propriétaire de plus. Le serveur MCP joint donc le Control Center, derrière le
  **même** garde d'origine que `POST /api/barehands` — la route qui bascule déjà
  le même interrupteur. Un appelant capable d'atteindre l'une atteint l'autre :
  le canal n'ajoute aucune autorité, il en emprunte une qui existe.
- **Échéance 3 s, et c'est un arbitrage, pas une valeur ronde.** Plus courte que
  les 5 s d'une capture parce qu'une capture doit dessiner un canevas et
  téléverser un PNG, quand une commande n'a qu'à traverser un long-poll déjà
  ouvert et appeler une fonction locale. En face, la commande naît d'une phrase
  prononcée et le cerveau **bloque** dessus pendant que la conversation attend :
  une commande qui part quatre secondes après que l'utilisateur est passé à
  autre chose est pire qu'un refus.
- **Aucune minuterie ajoutée à la page.** L'interrupteur voyage par
  `/api/status` — `refreshStatus` est le seul battement déjà permanent, et c'est
  exactement la couture de `JarvisScene.gate`. Le constat F1 notait que
  `/api/status` ne portait aucun champ Bare Hands : c'est ce trou-là qui est
  bouché. La boucle de commandes, elle, est un long-poll qui se rappelle
  lui-même et n'existe que pendant que l'interrupteur est vrai **et** que
  l'onglet est visible.
- **La campagne de mutations a trouvé un vrai défaut, pas seulement un trou de
  test.** Mon `evaluate` comptait les générations pour faire sortir la boucle à
  la fermeture. Fermer puis rouvrir la porte pendant que la boucle est garée sur
  un long-poll incrémentait deux fois le compteur : la boucle sortait alors que
  la porte était rouverte, et `running` valant encore vrai au moment de rouvrir,
  personne ne la relançait. **Bare Hands allumé, canal muet, rien à l'écran pour
  le dire** — et le cerveau n'aurait eu pour seul indice que
  `barehands_no_visible_page` devant une fenêtre parfaitement visible. Le
  compteur était en outre redondant : `while(active())` suffit à arrêter, et
  `running` seul suffit à empêcher deux boucles. Supprimé plutôt que testé.
  Formulation générale : **une garde qui double une condition déjà suffisante
  n'est pas de la défense en profondeur, c'est une seconde vérité** — et la
  seconde vérité finit par contredire la première.
- **Un appel qui ne lève pas n'est pas une preuve.** Pour `activate`/`deactivate`
  la preuve est l'état **relu** (`lifecycle()`) : `setAwake` avale ses erreurs
  dans `view.error` et ne rejette jamais, donc son retour ne dit rien. Cette
  règle a été durcie en cours de Slice après un signalement de la QA de la
  Slice 07 : `JarvisBarehands.tool('scissors')` normalise vers `pointer`,
  enregistre, n'affiche rien et **rend un succès**, ce qui rend le refus serveur
  `barehands_tool_unknown` inatteignable par la page. Conséquence pour ce canal,
  au-delà de ne pas router `tool` : un parcours (Slices 08/09) n'a **aucun** état
  observable, donc il doit **confirmer** explicitement (`true` ou `{ok:true}`)
  sous peine de `barehands_flow_unconfirmed`. Sans cette marche, le jour où la
  Slice 08 pose un `calibrate()` qui ne fait rien, la voix annoncerait un
  parcours ouvert.
- **Quatre portes de la surface restent délibérément hors de la table** —
  `enable`, `disable`, `settings`, `tool` — et un test lit l'absence sur la
  **vraie** surface plutôt que dans la table. L'interrupteur appartient à
  l'utilisateur : l'éteindre par la voix retirerait au cerveau l'outil qui vient
  de servir.
- **La preuve du point d'entrée unique est dynamique, pas une lecture de code.**
  Le double de DOM de la Slice 07 exécute le **vrai** bloc navigateur du
  pointeur, donc `window.JarvisBarehands` est le vrai. Deux runs node partent du
  même état (`off`) : l'un clique `#barehandsWake`, l'autre fait passer une
  commande par le canal. Les deux laissent la page dans un état **identique** —
  même cycle de vie, même `#barehandsLifecycle` redessiné, même bandeau
  `camera_unsupported`. `#barehandsLifecycle` n'est réécrit que par
  `refreshPanel()`, que seul `setAwake` appelle : une implantation parallèle du
  réveil laisserait ce bloc intact. Et sous node il n'y a pas de caméra, donc le
  refus est **réel** des deux côtés — c'est ce qui rend la comparaison probante
  au lieu d'être une mise en scène.
- **Quatre programmes de prompt pour deux interrupteurs indépendants**, composés
  par un constructeur plutôt que recopiés. Le test qui compte n'est pas celui du
  registre : c'est celui qui lance le **vrai** agent et lit l'argv. Tester le
  registre seul laissait passer la seule ligne qui relie « serveur MCP déclaré »
  à « consigne envoyée » — mutation M22, survivante au premier passage.
- **Deux `--mcp-config`, pas deux chemins accolés.** L'option du CLI est
  variadique : un chemin nu en deuxième position serait indissociable d'un
  argument positionnel, et un chemin Windows avec une espace s'y scinderait.
  Vérifié **sur le vrai CLI** : `claude --strict-mcp-config --mcp-config a.json
  --mcp-config "b with space.json" -p …` charge les deux serveurs et liste les
  dix outils (cinq par serveur) — ce qui prouve du même coup que
  `serve_stdio()` tourne pour de vrai au bout du protocole.
- **`consumed` n'est pas la même garde que « la réponse est posée ».** Entre le
  reçu de la page et la reprise de l'appel du cerveau, la commande est encore en
  place : un second onglet qui sonde dans cet intervalle la recevrait deux fois.
  Deux mutations (M6, M10) ont survécu au premier passage parce que mon test
  laissait la **fenêtre de redistribution** rendre `None` à la place de
  `consumed`. Il faut forcer la fenêtre à échéance pour que l'assertion parle de
  la bonne garde.
- **Ce que le cerveau voit aujourd'hui pour la calibration, le tutoriel et la
  sortie de panneau** : `barehands_flow_absent`, avec la phrase « ne prétends
  pas l'avoir lancé ». Le transport est complet et testé de bout en bout ; seule
  la dernière marche manque, et un test qui installe un faux point d'entrée
  prouve que le jour où les Slices 08 et 09 le posent, rien ne change ici.
- **Ce que la Slice 12 n'a pas touché, à dessein** : ni `createPinchDetector`,
  ni le budget d'images de la veille, ni les sept paires de construction, ni les
  deux refus de chargement existants (un troisième s'ajoute, de la même classe),
  ni aucune des constantes épinglées. Aucune constante nouvelle dans `DEFAULTS` :
  le canal ne règle rien, il transporte.

Fichiers : `jarvis/domain/barehands_command.py` (nouveau),
`jarvis/runtime/barehands_commands.py` (nouveau),
`jarvis/runtime/barehands_mcp.py` (nouveau),
`jarvis/runtime/control_center_barehands_commands.js` (nouveau),
`jarvis/runtime/control_center.py`, `jarvis/runtime/control_center.html`,
`jarvis/runtime/claude_local.py`, `jarvis/runtime/prompt_catalog.py`,
`jarvis/app.py`, `docs/barehands-contracts.md`, `docs/OPERATIONS.md`,
`tests/unit/test_barehands_command_channel.py` (nouveau),
`tests/unit/test_barehands_commands_js.py` (nouveau).

Tests, chunks en avant-plan : nouveaux fichiers **26 + 12 = 38 passed** ;
baseline 1 (Bare Hands + scène, onze fichiers) **276 passed**, inchangée ;
baseline 2 (`test_control_center_*`) **284 passed**, inchangée ; MCP + prompts +
`scene_settings` **148 passed**, inchangée ; `-k "claude or brain or agent or app
or mcp or barehands"` **1422 passed** ; `-k "settings or scene or prompt or
control"` **1643 passed**. Aucune régression.

**Quarante mutations tentées, quarante reprises** — six seulement après
renforcement : les deux de l'usage unique (`consumed` masqué par la fenêtre de
redistribution), celle du programme de prompt (le registre testé sans l'argv du
lancement), celle du refus de chargement du module, et les deux de la boucle —
dont une, M28, a été **supprimée plutôt que tuée** parce qu'elle visait du code
qui s'est révélé faux et redondant. Aucune n'a été tuée en assouplissant une
assertion.


## Slice 07 — reprise (QA de `1411421`) : ce qui **tient** les réglages en place

Trois constats MAJEURS, aucun bloquant. Le défaut commun n'était pas le
câblage (il était bon) mais ce qui l'empêche de disparaître.

- **Appeler la porte du moteur prouve la méthode, jamais le câblage.** Six
  fichiers de tests, 152 assertions, et cinq lignes de `applyToEngine`
  pouvaient paraître sans que rien ne tombe, parce que les tests écrivaient
  `overlay.showDiagnostics(true)`, `BAREHANDS.targetAssistance(0)`,
  `controller.configure({…})`. La règle qui remplace : **un réglage se vérifie
  en l'écrivant là où l'utilisateur l'écrit**, puis en regardant ce que la main
  fait. Onze mutations de câblage tentées, onze mortes.
- **Un moteur qu'on ne peut relire qu'en le reconfigurant ne se vérifie pas.**
  `configure` ne rendait ses valeurs qu'à celui qui écrit : « enregistré » et
  « appliqué » étaient indistinguables de l'extérieur. D'où
  `controller.options()` / `JarvisBarehands.engine()`, en lecture seule. C'est
  la même leçon que `targetsShown()` à la Slice 05, une couche plus bas.
- **Le coût exact d'un mutant se mesure à l'écran.** `sensitivity` ne divisant
  qu'une tolérance ne « casse » rien : il transforme le tiers inférieur du
  curseur — sa position minimale comprise — en « Réglage refusé » sur une
  position que l'écran propose. Le balayage des 76 positions **par l'écran**
  (et non par le contrat) est ce qui le rattrape.
- **Une tolérance de lecture n'est pas une tolérance d'écriture.**
  `normalizeTool` retombe sur `pointer` pour relire un schéma stocké ; sur le
  chemin d'écriture, la même ligne faisait de `tool('ciseaux')` un succès
  silencieux **et** rendait le refus serveur inatteignable, puisque la page
  postait la valeur déjà normalisée. Une porte de lecture et une porte
  d'écriture ne partagent pas leur indulgence.
- **`enabled` n'est pas un réglage comme les autres**, et son échec d'écriture
  ne peut pas suivre la règle générale : son état moteur ne passe pas par
  `applyToEngine` (la caméra est rendue **avant** l'écriture, exprès). Rendre
  « l'ancienne valeur à l'écran » recochait la case sur une caméra éteinte.
  **On ne rallume pas** : rouvrir une caméra parce qu'un enregistrement a
  échoué ferait faire à la machine ce que personne n'a demandé. L'écran suit le
  moteur, et la divergence qui reste se **nomme** (bandeau + toast, parce que
  ce chemin s'atteint panneau fermé par `JarvisBarehands.disable()`).
- **Un journal qui dit la même chose quoi qu'il arrive ne dit rien.** La route
  porte neuf réglages ; le message n'en nommait qu'un. Il nomme maintenant ce
  qui a **changé**, et une écriture sans changement le dit aussi — la taire
  ferait d'une route appelée et d'une route muette la même trace.
- **Deux leçons sur les doubles**, trouvées en écrivant ces tests :
  `global.navigator = …` **ne prend pas** (node 21+ l'expose en lecture seule,
  l'affectation échoue en silence) — le harnais héritait du navigateur de node
  depuis toujours ; et le `innerHTML` du double ne détruisait pas ses enfants,
  donc il ne pouvait pas échouer comme le vrai sur le constat F5. Les deux sont
  corrigées ; la seconde a donné l'assertion comportementale qui manquait
  (« un rafraîchissement ne réécrit jamais le corps de l'onglet »).
- **Le double de DOM géométrique de la Slice 05 est maintenant partagé**
  (`test_barehands_target_js.ELEMENTS`) au lieu d'être recopié une quatrième
  fois : sans arbre à rectangles, aucun réglage qui agit sur ce que la main
  **atteint** n'a de comportement observable.
- **Laissé en Issue** : un bloc de réglages en version étrangère est écrasé en
  silence par la première écriture ordinaire
  (`Issues/barehands-foreign-stored-version-overwritten.md`). Le contrat JS
  refuse bruyamment, le serveur se tait : l'asymétrie est le cœur du constat,
  et la refermer demande une décision de produit (archiver ou écraser).

Fichiers : `jarvis/runtime/control_center_barehands.js`,
`jarvis/runtime/control_center.py`, `docs/barehands-contracts.md`,
`tests/unit/test_barehands_tools_settings_js.py`,
`tests/unit/test_barehands_target_js.py`,
`tests/unit/test_barehands_test_mode.py`,
`tasks/jarvis-bare-hands-v1/Issues/barehands-foreign-stored-version-overwritten.md`
(nouveau).

Tests, avant-plan : Bare Hands + scène **300 passed** (baseline 288 après
Slice 12 + 12 nouveaux) ; `test_control_center_*` **284 passed**, inchangée ;
les deux fichiers de la Slice 12 **38 passed**, inchangés ; `-k "doc or
contract"` **693 passed**. **Quatorze mutations tentées, quatorze mortes** — les
cinq de la QA, la suppression complète de `controller.configure` (qu'aucune des
cinq ne couvrait), les deux voisines déjà tuées, et cinq visées sur les
correctifs eux-mêmes, dont `Object.assign(o,next)` retiré de `configure` pour
vérifier que la lecture du moteur n'est pas une tautologie.
