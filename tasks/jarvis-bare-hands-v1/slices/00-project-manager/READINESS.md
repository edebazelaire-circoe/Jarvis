# Slice 00 — Readiness report

- Date: 2026-09-19
- Branch: `task/jarvis-bare-hands-v1`, created from `origin/main@6af6df91` (no `dev` branch exists in this repository)
- Planning snapshot: `main@6af6df91c900efa33317ffa836a7eac9abbeb181` (2026-09-19) — **identical to current `origin/main`, zero drift**
- Handoff origin: remote (Drive `to-do/jarvis-bare-hands-v1`, folder `14ODU9_2L-3B1_zvAINHq59xntzkqlf26`). The Drive connector exposes create/update/delete only and cannot move folders, so the Human must move it to `current`.
- Mirrored into the repository as `S0` (`2550271`): 48 files, Google Docs export escaping removed, every JSON parses.

## Declared state

**`HUMAN_DECISION_REQUIRED`** (2026-09-19)

Three decisions are needed before any implementation Slice is dispatched. Everything else is resolved; the plan is sound and the repository matches it.

- **D1 — Workspace Task Type.** No such vocabulary exists anywhere in the repository. Precedent across three prior tasks (settings, observability, category2 test lab) is to waive the gate and leave `task_type: null`. Recommend the same waiver.
- **D2 — Voice entry points (F1 below).** Decision 6 and Slice 09 require voice activation of Bare Hands, calibration and tutorial. No substrate exists for this, and building it is a mechanism no Slice currently scopes. Choose: build it (enlarge 07/09 or insert a Slice), or defer voice entry to V1.1 and ship the UI button only.
- **D3 — Scope of frame manipulation (F4 below).** Decisions 9–11 (edges/corners as manipulation zones) apply cleanly to scene objects in `capsule`/`window` representation. `point` and `signal` objects are not resizable today and have no min-size. Confirm that edge/corner manipulation targets `capsule`/`window` only.

## Blind audit — live facts that change or confirm the plan

The handoff's characterization of the current implementation is **accurate**. `jarvis/runtime/control_center_barehands.js` is a click-only experiment landed 2026-09-14 (`419d3c2`, `b08cc08`) and untouched since: index-tip token, thumb-index pinch, synthesized pointer/mouse click on `document.elementFromPoint`. None of the locked V1 model exists yet (no OFF/SLEEP/ACTIVE, no C-pose wake, no secondary pinch, no semantic target resolver, no move/resize, no calibration/tutorial/diagnostics).

### F1. Voice entry points have no substrate (drives D2)

There is **no voice command registry and no intent router** in this repository. What exists:

- `jarvis/runtime/shortcuts.py` — keyboard shortcuts only (`wake_toggle` + 7 UI keys). Not voice.
- In the default `continuous_brain` architecture the Realtime surface is given **zero tools** (`jarvis/runtime/realtime_tools.py:30` `tools_for(continuous_brain=True)` returns `[]`, Décision 34), and `jarvis/adapters/openai_realtime.py:74-97` forbids the surface from claiming any action. The whole turn is forwarded to the brain.
- So a voice command must travel: utterance → brain (Claude CLI) → **MCP tool** → server → **browser delivery channel** → page.

The last hop does not exist for Bare Hands. `/api/status` carries no barehands field; the page learns Bare Hands state only by polling `GET /api/barehands` at load and after each toggle. The only precedent for "brain asks the visible page to do something" is the scene's `capture_request` long-poll (`jarvis/runtime/scene_view.py:314-322` → `POST /api/scene/captures/{id}`).

Slice 09 defers this correctly ("current Jarvis voice command/router integration discovered by Slice 00"), but no Slice scopes building the channel. Slice 07 (Tools and Settings) does not cover it either.

### F2. `pointerId 9001` is a cross-module contract, not a Bare Hands internal

`docs/02-architecture.md` §7 requires replacing the single hard-coded `pointerId 9001` with stable per-hand identity. Four coupling points live **outside** `control_center_barehands.js`:

| Location | Coupling |
|---|---|
| `jarvis/runtime/control_center_scene_page.js:1874` | drag threshold branches on `event.pointerId===9001\|\|barehandsActive()` |
| `jarvis/runtime/control_center_scene_page.js:1726` | `barehandsActive()` sniffs the DOM for `#jarvisHands .jh-token` |
| `jarvis/runtime/control_center_scene_page.js:819` | CSS shifts `.sc-status` when `#jarvisHands .jh-badge` exists |
| `jarvis/runtime/control_center.html:2075` | the confirm dialog's `inert` sweep exempts `#jarvisHands` by id |

Changing pointer identity breaks the scene's Bare Hands detection unless `control_center_scene_page.js` changes in the same Slice. **Planning repair:** add `control_center_scene_page.js` and `control_center.html` to Files Likely Touched for Slices 01 and 06.

### F3. New JS modules need explicit registration (missing from all twelve Slices)

The Control Center page loads no external scripts. Each JS module is a marker comment in `control_center.html`, substituted server-side by `ControlCenter.index()` (`jarvis/runtime/control_center.py:713-760`) from constants at `control_center.py:184-237`. Load order is load-bearing and asserted by tests (e.g. `tests/unit/test_scene_interaction_logic.py:474`).

Any new Bare Hands module therefore needs: a `*_SCRIPT_FILE`/`*_SCRIPT_MARKER` constant pair in `control_center.py`, a marker in `control_center.html` at the right position, and a load-order assertion. **Planning repair:** add this to the Implementation Steps of every Slice that extracts a module (01, 02, 03, 04, 05, 06, 08, 09, 10).

### F4. "Frames" already exist as scene objects (drives D3)

There is no generic movable/resizable window widget in the Control Center — `.panel`, `.modal`, `.tl`, `.tlab` are all fixed. The handoff's "frames" are **scene objects** in `capsule`/`window` representation, and their geometry is already implemented as pure, node-tested functions in `jarvis/runtime/control_center_scene_interact.js`:

- `clampBox(box, representation)` (`:67`), `dragBox` (`:89`), `resizeBox` (`:96`), `pxToUnits(vp,dx,dy)` (`:84`)
- `MIN_SIZE` (`:37`) — `capsule {w:16,h:5}`, `window {w:40,h:24}`; `MAX_SIZE.capsule {w:160,h:10}`
- `resizable = r => r==='capsule'||r==='window'` (`:104`) — **`point`/`signal` are not resizable**
- commit path `commitGeometry(...)` (`:464`) → `POST /api/scene/commands`, where any user geometry also pins the object (`geometrySteps`, `:452`)

Two consequences for Slice 06:

1. **Coordinate space is scene units, not pixels.** `FRAME` is ±160 × ±90 with `SAFE_AREA` `{-152,138,-72,68}` (parity-asserted against `jarvis/domain/scene.py:116`); `viewport()` gives `scale` ≈ 6 px/unit at 1080p. The handoff's open question "exact edge/corner pixel clamps" must be answered in scene units and converted through `vp.scale`.
2. **Extend, do not reinvent.** Today resize is a single bottom-right `.sc-grip` with the top-left pinned. Eight edge/corner zones with per-zone axis constraints is genuinely new, but it belongs in `control_center_scene_interact.js` beside the existing pure functions, reusing `clampBox`/`MIN_SIZE`, not in a parallel Bare Hands geometry layer.

Scene node identity for the target resolver is `data-object-id` (`control_center_scene_page.js:1496`), hit-tested by `target.closest('.sc-node')` (`:1609`). Note `.sc-node` is **absent** from the current Bare Hands `INTERACTIVE` selector (`control_center_barehands.js:266`), so stars are reachable by raw click today but never hover-highlighted.

### F5. Bare Hands owns the "Expérimental" tab that Scene settings depends on

`control_center_barehands.js:507` **creates** the tab (`TABS.push({id:'experimental',...})`) and monkey-patches `renderTab`. `control_center_scene_settings.js` then prepends its section to it, and says so in its header comment (`:317`); the required injection order is documented at `control_center.py:224-226`.

Restructuring Bare Hands settings in Slice 07 can silently break the Scene settings section. **Planning repair:** Slice 07 must treat the tab as a shared surface, keep the injection order, and cover it with the existing order assertions.

Also note the deliberate design that Slice 07 must not undo casually: `barehands_test_mode` is **not** in `_settings_payload` / `GET /api/settings`. It has its own immediate-write route pair (`GET`/`POST /api/barehands`) precisely so the toggle applies hot and does not depend on the rest of the settings being valid (rationale quoted at `control_center.py:1661-1666`).

### F6. Diagnostics substrate — no LogBroker; use `RuntimeJournal`

There is no LogBroker in this repository (the repo's own docs record its absence, e.g. `docs/settings/INDEX.md:107-109`). Slice 10 must emit through `jarvis/runtime/journal.py::RuntimeJournal.emit(kind, message, level=, data=)` → `runtime/trace.jsonl`, with `errors.jsonl` populated automatically at `level="error"`, and inspect via `read_jsonl_tail`. Repo convention: a stable `code` string in `data` for every rejection, mirrored into the `X-Jarvis-Error-Code` header.

For benchmarks, `jarvis/testlab/` (Category 2 Test Lab, contract `docs/testlab.md`) already provides `ParameterSpec`/`MetricSpec`/`AssertionSpec`/`DiagnosticSpec` registration and a runner. Slice 10 should register Bare Hands metrics there rather than build a new harness. `jarvis/runtime/voice_metrics.py` is the precedent for deriving metrics from `trace.jsonl`.

### F7. Clean-room boundary is structurally enforced (no action needed)

The native pointer never contacts the AGPL upstream. `third_party/barehands/` is git-ignored in its entirety; only `README.md` and `LOCK.json` are versioned. The page receives MediaPipe (Apache-2.0) through a **closed whitelist** of six names in `barehands_test_mode.ASSETS` — anything not in the table 404s regardless of what is on disk. Both `control_center_barehands.js:1-13` and `barehands_test_mode.py:1-17` state the clean-room boundary explicitly, and `third_party/README.md` repeats it.

Bare Hands V1 touches none of the hashed upstream files (`server.py`, `stage.html`), so `scripts/bootstrap_third_party.py --verify` will not be invalidated by this task.

## Environment verified on this host

- MediaPipe assets installed and complete: `vision_bundle.mjs` (134K), `wasm/vision_wasm_internal.js` (205K), `wasm/vision_wasm_internal.wasm` (9.0M), `models/hand_landmarker.task` (7.5M) under `third_party/barehands/vendor/`.
- `node v24.18.0` present — the Python-drives-node JS test harness runs (it `pytest.skip`s without node).
- Host RAM ~2.9 GB free of 15.6 GB. Per repository precedent, run pytest in **foreground chunks**; background jobs and single-process full runs get killed.

## Baseline (origin/main@6af6df91, before any change)

`origin/main` imports cleanly (`jarvis.runtime.control_center`, `jarvis.runtime.barehands_test_mode`).

| Set | Result |
|---|---|
| `test_barehands_pointer_js`, `test_barehands_test_mode`, `test_scene_interaction_logic`, `test_scene_renderer_logic` | **94 passed** |
| `test_control_center_appearance`, `test_control_center_quality`, `test_settings_endpoints`, `test_scene_settings_ui`, `test_scene_settings`, `test_control_center_testlab_js` | **221 passed** |

315 passed, 0 failed across the surface this task touches. No pre-existing breakage to work around.

## Test harness for implementation Slices

Pure JS is tested by Python driving node: pytest writes a `.cjs` shim into `tmp_path` that `require()`s the exact file the page serves, runs it, and parses JSON from stdout; `pytest.skip("node absent")` without node. Canonical example `tests/unit/test_barehands_pointer_js.py:16-40`. The browser half of each module is never executed — it is guarded by `if(typeof window==='undefined')return`. For fixtures too large for a command line, a JSON data file is read in the shim (`tests/unit/test_scene_interaction_logic.py:65-84`).

Every JS module additionally gets server-side assertions: the marker is consumed by `ControlCenter.index()`, load order holds, JS constants match their `jarvis.domain` counterparts, and static prohibitions (no `confirm()`/`alert()`, no `innerHTML` in scene code) are regex-checked over the served HTML.

## Dependency graph

Unchanged from `slices/TODO.md`; all Slice IDs and dependencies resolve. No Slice is dispatchable before this report reaches `READY`.

## Required before dispatch

1. Human answers D1, D2, D3.
2. Human moves the Drive folder `to-do/jarvis-bare-hands-v1` → `current`.
3. Planning repairs F2, F3, F5 applied to the affected SLICE.md files.
4. Targeted freshness check immediately before each Slice dispatch, per the handoff's standing rule.
