# 05 - Documentation levels and prerequisite gaps

The PM must re-evaluate these levels against current HEAD before dispatch. The levels below are planning estimates based on the inspected code/docs.

| Concept | Current estimate | Required by this task | Gap / action |
| --- | --- | --- | --- |
| Capture ownership and API | L3 | L3 | Preserve; update UI references only if routes/behavior change |
| Artifact registry | L3 | L3 | Preserve |
| Interaction mode | L3 | L3 | Preserve; update UI screenshots/entry docs if needed |
| Bare Hands lifecycle | L3 | L3 | Preserve |
| Bare Hands tool presentation | L2/L3 implementation-specific | L3 for new wheel contract | Establish wheel contract before migration |
| Orbital tool wheel (reveal, wedges, activation, radial sub-arc) | **L3 (S02)**: `docs/control-center-shell.md` › Tool wheel, `control_center_tool_wheel.js` (`JarvisToolWheel`: pure geometry + reducer, injected actions), `tests/unit/test_tool_wheel_js.py` + `test_tool_wheel_browser.py` | L3 | Done in S02 behind `JarvisToolWheel.enabled=false`; S03 wires Selection, S04 captures and removes the flag |
| Mouse/Bare Hands arbitration | L0/L1 for this exact policy | L3 | New contract + pure tests + runtime validation |
| Control Center shell/layout | **L3 (S01)**: `docs/control-center-shell.md` (zones, tokens, a11y rules), `control_center_shell.js` (`JarvisShell`), conformance `tests/unit/test_control_center_shell_layers.py` | L3 for new shell | Done in S01; later slices update the doc, the sheet and the mirror in the same commit |
| Z-index/layer registry | **L3 (S01)**: single table in `docs/control-center-shell.md`, compared to every real sheet (page, Cosmos, modules); same ranks in both themes | L3 | Done in S01; rank 37 taken by S02 (open wheel); reserved 38/40/60 for S05/S06 |
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
