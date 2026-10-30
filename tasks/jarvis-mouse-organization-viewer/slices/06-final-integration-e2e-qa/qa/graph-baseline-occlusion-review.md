# One baseline natural-occlusion witness

**Observed:** the existing presentation rail intercepts an ordinary relation
click on exact baseline `c0858a8000e2ca23b57231edb8f46c643080ad07`.
The relation Board remains `null` after the original 8-second wait. This is
a deliberately conditioned baseline witness, **not a reproduction of the
original uninstrumented baseline test failure**. That original baseline test
passed; the original current full-gate and exact-retry failures remain retained.

## Method and provenance

PM allocated one observation, without retry. The baseline worktree was clean
before/after. Every imported Jarvis/test Python module was asserted to resolve
under `movb`; paths and SHA256 values are retained in the run manifest. The
served page is composed by baseline `test_boards_card_browser._served_page`
using baseline ControlCenter markers and runtime sources. Its composed bytes
and the original/copied Node harness hashes are retained. No current product
module was imported into the witness.

The existing fixture seed `_seed(dense=30)`, viewport720x450/deviceScale2,
default theme and default orbit are used. The page uses its existing fetch
double; this is a real headless Chrome UI observation, not real Core/model
evidence. No daily data, provider, model, microphone or user's runtime is used.

One read-only async predicate polls `rel_comm`'s current center every100ms,
bounded245000ms, and returns only when `elementFromPoint(center)` has
`#presentationRail` as an ancestor. The original Node driver has no internal
CDP-evaluate timeout. A local QA-only300000ms Node ceiling preserves canonical
owned-profile disposal on exit; shared driver, product and Core deadlines are
unchanged. Tool waits stayed below60seconds. Actual run finished normally in
109.09seconds including startup, original Board wait and owned cleanup.

The screenshot precedes the predicate. Upon reaching it, the existing native
mouse helper samples one center and sends its unchanged move/down/up sequence
once. No synthetic click, new click engine, target repositioning, animation
freeze, DOM mutation, clock substitution, second click or repeat-until-red is
used. The earlier minimal-capture observer is factored into a reusable QA helper;
its observations run inside the existing center/final evaluate calls.

Baseline layout defines `ORBIT_PERIOD_MS=240000`; `orbitTurnAt(nowMs,field)`
uses modulo wall-clock time, and `orbitFrameWall` reconciles that with the
displayed document frame. Different launches therefore have different natural
phases; no assertion that additional current JS parse time caused the original
miss is justified.

## Actual evidence

The condition was reached naturally after **85351.7ms** at wall time
1793374767842. The sampled native-click center22ms later was
(447.1156311,190.6010590). The mark rectangle was
x435.1156311..459.1156311/y181.6010590..199.6010590. Rail rectangle was
x448..720/y0..450, visible, existing z-index30. The center hit was the rail;
its complete ancestor chain was rail→body→html. All38objects were points,
with zero grips and no viewer.

Every recorded native event **target**, including pointerdown, mousedown,
pointerup, mouseup and click, was `#presentationRail`. Consequently no relation
Board opened: `waitBoard=8025`, `board=null`. The event observations preserve a
subtle boundary distinction: PointerEvent coordinates retain447.1156 while
MouseEvent.clientX reports447. A fresh EFP query at that integer MouseEvent
coordinate sometimes resolves to `rel_comm`, even though the actual native
event target is still the rail. The raw evidence keeps both fields; the causal
observation uses the actual target rather than conflating integer EFP with it.

There are no error/exception console entries. The only recorded write body is
the existing presentation-rail display-state publication; there is no scene
command. Screenshot inspection confirms the existing right presentation panel
and the closed relation Board. Initial/after screenshots are separate from all
previous current/baseline test captures.

Evidence:

- `graph-baseline-occlusion-witness.json`: complete parsed Node JSON plus record.
- `graph-baseline-occlusion-witness-run.json`: imports, hashes, roots, wall times,
  budget, condition and outcome; `original_test_baseline_failure_claim=false`.
- `graph-baseline-occlusion-before.png`, `graph-baseline-occlusion-after.png`.
- `graph_baseline_occlusion_witness.py`: no-repeat guard and exact method.
- `graph_minimal_capture_plugin.py`: shared QA-only passive observation builder.

## Recommendation and limits

The witness establishes a reachable **pre-existing rail-interception mechanism**
that yields the same closed/null Board outcome with the original click helper
and original Board wait. It does not measure the original current failure's
event target, nor prove that every original red had this cause. Earlier current
successful captures prove relation handling when the mark is actually hit;
source review finds its relation handler/Board route unchanged and new node
viewer/grip handlers inapplicable to this point/relation path.

Together these are sufficient evidence to propose a local graph-fixture
precondition correction: close the unrelated presentation rail through its
existing owner before testing the graph's native click, retain all graph/Board
assertions, and retain historical reds. PM owns that policy and any subsequent
test-only work. No such correction or product change was made here. No further
baseline/current repetition is initiated by this report.
