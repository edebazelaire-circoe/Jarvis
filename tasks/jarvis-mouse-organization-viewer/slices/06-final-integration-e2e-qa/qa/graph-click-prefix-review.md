# Initial graph click prefix capture — no failed click observed

One valid current720×450/scale2 dense prefix, using a QA copy of the existing
Node driver, production page modules and original seed/center/CDP mouse event
sequence. Passive page capture records actual event targets/EFP/rectangles,
viewport/panel bounds, ancestor chains and node/grip counts. One extra sample
evaluate precedes mouseMove; event snapshots themselves are in-page callbacks,
not additional CDP roundtrips. Added observation can perturb timing, and launch
wall-clock orbit phase differs. No freeze/DOM mutation, geometry edit, model,
browser parallelism or click retry.

The first builder check failed before launching Chrome because its replacement
matched both mouse and drag functions; scope was narrowed to mouse. An initial
launched copy then had an IIFE statement-separator error: fake server initialized
but observer did not, and the guarded click stopped before input. Those setup
artifacts remain `graph-click-*-setup-error.*`; they are not product failures
or click evidence. The separator was fixed in the QA copy, producing the one
valid capture `graph-click-diagnostic.json`, with screenshots and builder.

## Actual valid capture

- Board opened normally as communication relation `rel_comm`; no Runtime/error
  console entry. This prefix did **not** reproduce the original failure.
-15 records from sample, pointer/mouse move/down/up/click and post-handler
  microtasks. Actual click capture target and EFP are the rel_comm button;
  ancestor chain is button→sc-relmarks→sceneLayer→app→body→html.
-38 scene nodes, all38points, **zero resize grips**, viewer never created/opened.
  The new window/capsule grip branch and viewer modal path are absent here.
- Sample center(441.6198,190.70), rel_comm rectangle left429.6198/right453.6198.
  Existing visible presentation rail occupies x448..720 across450px height.
  The actual center is just left of the rail, although part of the marker is
  behind it. Click coordinates round to(441,190) and still hit the marker.
- Marker x moves only≈0.12px between sample/click in this capture. No point
  hover/focus interception was observed. The panel/rank/motion condition remains
  relevant to a possible miss, but was **not observed as its cause** here.

Source review: nodeElement accepts only .sc-node, while relation buttons are
in the separate sc-relmarks layer; onPointerDown returns before new grip/hold
logic for a relation target. Viewer open is limited to node Enter/double-click,
not this ordinary button click. Existing onMarkClick/RelationBoard.open,
relation layout/roles/ranks and original point-hover219 versus marks218 remain
unchanged. The driver still samples the center once before three awaited CDP
events. These are bounded path facts, not proof of the original failed target.

The baseline exact case passed and the original current case failed twice
(full gate and allocated retry). A successful later diagnostic must not waive
those reds. PM's next bounded discriminator is one full original3-scenario
case with center/EFP/rail/rect observation in the **same existing** evaluate,
small native event-target capture and raw stdout retention through the same
final server read. No extra CDP calls/freeze/DOM changes/repeat loop. If that
does not capture a miss, report the limitation rather than manufacturing one.
