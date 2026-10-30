# Shard 14: capture-source baseline and pending Variants browser comparison

Root `97d56f1144cb721e7c5303f43ff71d291ed1d9bc` reports **1066 passed,
6 failed, 12 skipped**, no session problems, in its shard JSON (486.1 seconds
gate duration; pytest reports 482.37 seconds). Five failures are newly
observed; the missing `ui_intent_publish` brain-prompt assertion was already
known. Original evidence is root's `qa/evidence/shard-14.json` and
`qa/evidence/shard-14.log` under this Slice.

## Two source assertions: actual baseline proof

Only the following two exact cases were executed in detached
`C:/Projects/jarvis/movb` at baseline
`c0858a8000e2ca23b57231edb8f46c643080ad07`, using the main venv Python,
`PYTHONDONTWRITEBYTECODE=1`, and these arguments:

```powershell
python -m pytest --assert=plain --tb=short -p no:cacheprovider -q `
  tests/unit/test_capture_rail_js.py::test_la_scene_mesure_les_indicateurs_et_la_roue_comme_des_commandes `
  tests/unit/test_capture_rail_js.py::test_les_indicateurs_sont_au_haut_gauche_au_rang_du_centre_d_etat `
  --junitxml=C:/Projects/jarvis/mov5/tasks/jarvis-mouse-organization-viewer/slices/06-final-integration-e2e-qa/qa/baseline-shard-14-capture.xml
```

Actual baseline: **2 failed in 6.87 seconds**, exit 1. Retained
[console](baseline-shard-14-capture.log) and [JUnit](baseline-shard-14-capture.xml).

Both traces match root exactly:

| Test | Root and baseline failing assertion |
| --- | --- |
| `test_la_scene_mesure_les_indicateurs_et_la_roue_comme_des_commandes` | line 401 requires `selector:'#recIndicators',zone:'top-left'` |
| `test_les_indicateurs_sont_au_haut_gauche_au_rang_du_centre_d_etat` | line 409 requires the exact absolute/z40/left-gutter/top-gutter HTML CSS sequence |

The test module and shell module are unchanged. Actual shell line 49 declares
`#recIndicators` in `top-right`; actual HTML line 670 positions it with
`right:calc(var(--shell-gutter) + max(var(--shell-rails-open-w),var(--shell-panel-open-w)))`.
The only HTML changes between baseline and root are four module injection
markers, away from this CSS. The declarations already differ from these
left-side expectations at baseline.

Recommendation: these two observed source failures are proven pre-existing
and unrelated, subject to PM disposition. This does not classify the three
browser failures below. No product change, ignore or test rewrite was made.

## Three Variants browser failures: still blocking and unclassified

The affected function is
`test_variants_run_browser.py::test_during_a_run_recording_chips_stay_visible_reachable_and_stop_without_touching_the_run`,
parameters `[1280x720]`, `[1920x1032]`, `[600x800]`.
All three actual root traces fail at line 338:

```text
AssertionError: ('une puce couvre une commande du Studio', ['Plein écran', 'Fermer Variantes'])
```

This is an actual geometry assertion, not a browser-startup timeout. Prior
assertions establish run mode, indicator z-index `9150`, `data-keep-live=run`,
the two expected channels and visible/reachable/non-inert chips. `REC_GEOMETRY`
records chip rectangles, temporarily hides their host, then samples
`document.elementsFromPoint` on an 8-pixel grid inside those rectangles and
collects interactive Studio descendants. The two named controls were found
under the chip rectangles. Exact rectangles and sample coordinates are not
printed in the failure trace, so their values are not invented here.

The harness completes its planned screen-chip click before Python evaluates
this assertion, but later assertions of run continuity and Core capture
state, and `_no_noise`, are not reached. Thus the failed test does not prove
those later outcomes or a clean console.

## Source and click-path pretriage

The test, `_fullscreen_browser.mjs`, fullscreen Python helper, capture test
fixture, capture rail/wheel and Studio explorer/core CSS are unchanged
between `c0858a80` and root. Source facts:

- HTML positions the indicators at the top right (line 670); shell also
  describes the top-right zone. Comments and these source assertions still
  refer to top left. That mismatch alone does not prove the browser cause.
- Explorer core CSS sets the Studio host to z9000 and raises recording
  indicators to z9150 during `html.jvx-run` (line 463). Explorer
  `setRunInert` toggles that class, and `data-keep-live=run` excludes these
  indicators from page inerting while a run exists.
- Explorer header construction appends its fullscreen and close buttons to
  `.jvx-top-actions` (explorer lines 337–343), matching the reported names.
- `_fullscreen_browser.mjs` lines 112–117 read the chip's rectangle center
  and dispatch real CDP mouse move/press/release there. The recording wheel
  click listener calls `activateChip`, then `C.stop(captureId)`; the rail
  posts the existing `/api/captures/{capture_id}/stop` route. This path does
  not call the scene object-viewer open hook.

The complete served page does include new scene/viewer modules and other
integration changes. Source similarity does **not** disprove a stacking or
layout regression. Keep all three cases blocking/unclassified until the
exact real baseline browser scenario is executed after the broad gate.

## Queued bounded runtime scope

Future baseline comparison, only after PM allocates a browser slot: the one
affected function with its three parameters at `movb`, retaining actual
trace/JUnit and any existing per-case screenshots. Do not run the full file.
Its fixtures use real isolated Core/SQLite/loopback HTTP and the real page,
but `tests.fakes.capture_stack` injects `FakeCaptureSources`/`FakeCaptureSource`
and a fake transcription provider. No physical screen/audio capture or live
model is needed by this scenario. Owned fixture handles close through the
existing async context managers. No browser/model/hardware execution,
process scan or cleanup command was performed for this pretriage.

The original red gate evidence remains unchanged.
