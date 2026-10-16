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
| Presentation rail | **L3 (S07)**: `docs/presentation-studio.md` › Rail › *Active workspace rail*, `docs/control-center-shell.md` › *Workspace rail* (zone `right`, densities, mirrored Studio docking), `control_center_presentation_rail.js` (pure `displayState` / `cardOf` / `densityOf`), `test_control_center_presentation_rail_{js,browser}.py`, `test_presentation_rail_e2e_browser.py` | L3 | Done in S07 Stage A; every action, `Alt+Maj+P`, brain `show_rail`/`hide_rail` and the display-state report kept |
| General active workspace rail | **L3 (S07 Stage B)**: `WorkspaceRailItem` built by the pure adapter `control_center_workspace_rail_model.js` from `/api/workspace/artifacts?board_id=` (type by kind / MIME / link host, payload-route image previews, state without yellow, last-Board-wins refresh), contract in `docs/presentation-studio.md` › *Active workspace rail*, `tests/unit/test_workspace_rail_model_js.py` + browser + e2e | L2 minimum, preferably L3 | Done in S07 (separate commit, cuttable) |
| Rich preview sourcing | **L3 (S07)** for presentations: Core row `preview` = newest complete `presentation_still` (lineage cached, one bounded query per read, `PREVIEW_*`), served by `/api/artifacts/{id}/payload`, typed placeholder otherwise; `test_presentation_studio_rail.py::test_row_preview_is_latest_complete_still_without_path`, `::test_preview_cache_bounded` | L2 | Done in S07 |
| `changed/unreviewed` status | **L3 (S07)** for presentations: owner Core rail service, additive `unreviewed` key of `rail.json` v1 (no SQLite), set on brain work `success`, cleared by user action `review`; precedence working > problem > unreviewed > done; 5 Core + 3 JS acceptance tests | L2 before UI | Done in S07; none for Stage B items (no canonical review owner) |
| Bottom-left mode+Board context composition | L1 UI concept | L2 | Document composition without merging state owners |

## Level interpretation used here

- **L0:** idea only, no durable contract.
- **L1:** implementation/comments imply behavior but it is not a stable reusable contract.
- **L2:** explicit durable behavior/ownership/edge-case documentation exists.
- **L3:** behavior is documented, implemented behind clear boundaries, and protected by conformance tests/runtime evidence.

## Blocking rule

If Slice 00 finds that a concept relied upon by a later slice is below the required level, the PM creates or expands the prerequisite contract/test slice before implementation. Do not compensate for missing contracts with assumptions inside UI code.
