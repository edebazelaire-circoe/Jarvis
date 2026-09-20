# Target architecture

## 1. Main Bare Hands HUD control

Add a dedicated UI adapter around the authoritative Bare Hands lifecycle. It renders the hand button and the visual state chooser but delegates transitions to the existing Bare Hands controller/API.

Recommended state mapping:

- selecting OFF: persist/drive the existing master-enabled state false and fully release camera/resources;
- selecting SLEEP: ensure Bare Hands is enabled, then enter SLEEP;
- selecting ACTIVE: ensure Bare Hands is enabled, then activate;
- ERROR remains a runtime/error state, not a fourth selectable mode.

Do not create a second lifecycle store in the UI. Subscribe/refresh from existing controller status/API.

## 2. Context menu router

Right click on the HUD control routes to existing or refined surfaces:

- Settings → Bare Hands configuration section;
- Calibration → unified calibration flow;
- Help/Gestures → new visual help card;
- Diagnostics → existing recorder/diagnostic surface.

Use the existing Control Center context-menu pattern when practical instead of adding a bespoke menu framework.

## 3. Tool palette

Move the UI for `pointer`, `pan`, `select` out of Settings into a dedicated fixed-left palette. Continue using the canonical `describeTools()` / tool-setting path and interaction-engine capability gating. The palette is another view of the current tool state, not a parallel setting.

## 4. Settings cleanup

Keep existing persistence/validation contracts unless migration requires a schema change. Remove lifecycle/tool/tutorial controls from the primary Bare Hands settings presentation. The backend `enabled`/`tool` values may remain because runtime/compatibility depend on them; UI ownership changes, not necessarily storage ownership.

## 5. Help / Gestures card

Build a small visual card from canonical contract data and known bound interactions. It may contain small SVG/CSS hand diagrams. Keep semantics data-driven enough that help cannot drift from actual supported gestures/actions.

Do not advertise unbound recognizers as commands.

## 6. Calibration shell

Replace the current `.jf-step` centered modal composition with a full-viewport presentation layer:

- background veil + backdrop blur;
- separate header/instruction region near top;
- central exercise stage using most of viewport;
- lightweight global progress;
- secondary escape/skip controls;
- live feedback zone that does not occlude the exercise.

The shell still needs one stable accessibility root and predictable keyboard/escape behavior.

## 7. Calibration phase state machine

Each exercise needs explicit phases rather than “step opened = test running”:

`INTRO -> ARMED -> RUNNING -> RESULT -> NEXT`

- `INTRO`: minimum reading/demo delay; no stage measurement timeout.
- `ARMED`: user can engage; gesture/posture steps can remain here indefinitely while idle.
- `RUNNING`: measurement/validation watchdog and current calibration logic run.
- `RESULT`: short positive/failure feedback; partial calibration fallback semantics remain.
- `NEXT`: advance.

Target/window exercises may materialize their interactive target at the end of INTRO, then transition to RUNNING on meaningful engagement.

## 8. Demonstration visuals

Use lightweight DOM/SVG/CSS line-art hand demonstrations, not video and not realistic imagery. Demonstration is instructional UI only; it must not become an input source or be persisted.

## 9. Unified calibration/tutorial sequence

The separate tutorial module must no longer own a competing flow. Fold teaching into the six exercises plus completion report.

The existing tutorial command compatibility path should be resolved by Slice 00. Preferred migration: keep the command name temporarily as a deprecated alias that launches calibration, while removing distinct tutorial UI/state. If current public contracts make a clean removal safer, version them explicitly; never keep two flows.

## 10. Window practice adapter

Step 6 should mount an ephemeral practice frame that uses the same target region/capture/geometry semantics as real scene windows.

Preferred approach:

- create a sandbox/practice object compatible with the current scene/Bare Hands adapters;
- exercise one-hand move via a real edge/corner capture;
- exercise two-hand resize via two distinct compatible zones;
- do not persist the practice object into the real scene model;
- do not duplicate `manipulateBox`, `rebaseManipulation`, zone ownership, min-size, or no-inversion rules.

The stage may still collect drag-distance samples for the existing calibration profile when appropriate.
