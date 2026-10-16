# 05 - Documentation levels and prerequisite gaps

The PM must re-evaluate these levels against current HEAD before dispatch. The levels below are planning estimates based on the inspected code/docs.

| Concept | Current estimate | Required by this task | Gap / action |
| --- | --- | --- | --- |
| Capture ownership and API | L3 (+ S04: `GET /v1/captures/targets` / `/api/captures/targets`, `CaptureTargetLister` port, `docs/capture.md` › HTTP API, `tests/unit/test_capture_targets.py`) | L3 | Preserved; S04 added the read-only targets route (no schema change) |
| Capture controls UI (wheel wedges, target sub-arcs, persistent indicators) | **L3 (S04)**: `docs/capture.md` › Interface (rewritten from the left rail), controller `control_center_capture_rail.js` (`JarvisCaptureRail.subscribe/start/screenshot/stop/targets`), views `control_center_capture_wheel.js` (pure `wedgeStatusOf`/`chipsOf`/`targetItemsOf`), `test_capture_rail_js.py` + `test_capture_wheel_browser.py` (real CC + real Core, fake sources) | L3 | Done in S04; indicators in a provisional slot until S06 places them in the status centre |
| Artifact registry | L3 | L3 | Preserve |
| Interaction mode | L3 | L3 | Preserve; update UI screenshots/entry docs if needed |
| Bare Hands lifecycle | L3 | L3 | Preserve |
| Bare Hands tool presentation | **L3 (S03)**: `docs/barehands-contracts.md` § 8 (palette invariants carried to the Selection › Bare Hands second level), wheel second level + `setStatus` in `docs/control-center-shell.md` › Tool wheel | L3 for new wheel contract | Done in S03; since S04 the wheel is live by default, the strip comes back only as rollback (wheel hidden / not installed) |
| Orbital tool wheel (reveal, wedges, activation, radial sub-arc) | **L3 (S02)**: `docs/control-center-shell.md` › Tool wheel, `control_center_tool_wheel.js` (`JarvisToolWheel`: pure geometry + reducer, injected actions), `tests/unit/test_tool_wheel_js.py` + `test_tool_wheel_browser.py` | L3 | Done in S02; S03 wired Selection; S04 wired the captures (`menu` as a function, `checked`/`unknown` status) and removed the flag: live by default |
| Mouse/Bare Hands arbitration (selection method, mouse takeover) | **L3 (S03)**: `docs/control-center-shell.md` › Selection method, `control_center_input_arbitration.js` (`JarvisInputArbitration`: pure `decide` + projection `methodOf`, browser seam), `tests/unit/test_input_arbitration_js.py` (10k-seed properties) + `test_selection_method_browser.py` (real engine, fake camera) | L3 | Done in S03 (projection of the BH lifecycle, no new owner); user-facing by default since S04 (wheel live) |
| Control Center shell/layout | **L3 (S01)**: `docs/control-center-shell.md` (zones, tokens, a11y rules), `control_center_shell.js` (`JarvisShell`), conformance `tests/unit/test_control_center_shell_layers.py` | L3 for new shell | Done in S01; later slices update the doc, the sheet and the mirror in the same commit |
| Z-index/layer registry | **L3 (S01)**: single table in `docs/control-center-shell.md`, compared to every real sheet (page, Cosmos, modules); same ranks in both themes | L3 | Done in S01; rank 37 taken by S02 (open wheel); rank 40 `#recIndicators` taken by S04 (row `#captureRail` 30 removed); reserved 38/40 (`#hiddenEye`)/60 for S05/S06 |
| Background notifications UI | L1/L2 | L3 | Separate category model from rendering; document semantics |
| Hidden-object visibility | L2/L3 in scene interaction | L3 | Preserve canonical owner; add eye control contract |
| Presentation rail | L2/L3 implementation | L3 | Document new right-rail behavior and retained actions |
| General active workspace rail | L0 | L2 minimum, preferably L3 | Define view model, source adapters, refresh semantics |
| Rich preview sourcing | L0/L1 | L2 | Define truthful fallback/caching/size bounds |
| `changed/unreviewed` status | unknown / likely absent in presentation rail | L2 before UI | Define owner if implemented; otherwise defer indicator |
| Bottom-left mode+Board context composition | L1 UI concept | L2 | Document composition without merging state owners |

## Level interpretation used here

- **L0:** idea only, no durable contract.
- **L1:** implementation/comments imply behavior but it is not a stable reusable contract.
- **L2:** explicit durable behavior/ownership/edge-case documentation exists.
- **L3:** behavior is documented, implemented behind clear boundaries, and protected by conformance tests/runtime evidence.

## Blocking rule

If Slice 00 finds that a concept relied upon by a later slice is below the required level, the PM creates or expands the prerequisite contract/test slice before implementation. Do not compensate for missing contracts with assumptions inside UI code.
