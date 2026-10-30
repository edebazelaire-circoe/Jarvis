# Dense graph: causal click-path audit after a passing baseline

Independent QA reports the exact baseline case passing in 38.25 seconds.
The original current broad-gate failure (`board is None`, line 438) therefore
remains a possible regression, not proven pre-existing. Current exact runtime
comparison is assigned to S1; no browser or test execution was performed for
this source audit.

## Exact unchanged segments, including the surrounding input paths

[Retained source identity measurements](dense-graph-click-source-identity.json)
compare baseline `c0858a80` to the F2 candidate `1340ca56`. All **17** selected
comparisons match exactly: mark construction/placement, drawn-point conversion,
mark obstacle/layout calculation, tick setup/stop, click/keyboard handlers,
node target lookup, ordinary inner click, point focus/hover handling, band
candidate filtering, mark/point hover CSS, entire layout/roles/relation-board
modules, and the browser test itself. The new modal fix does not alter these
segments. The comparison is source identity, not runtime coverage.

Marks are actual buttons appended to `.sc-relmarks` under the scene, outside
the `.sc-node` objects. `applyMarks` retains each mounted button and updates
its transform; it does not wrap, detach or reorder an existing mark. The
relation board's `open()` calls `ensurePanel()` synchronously before starting
its read. A failed/slow HTTP relation read would still leave panel DOM and
loading/error state. Board absence is earlier than that ordinary async state.

## Changed paths considered, rather than assuming identical graph modules suffice

- `onPointerDown` adds the `geometryBusy` early return. This case performs no
  organization action, so the initial false flag is never armed. The next
  `nodeElement` lookup only accepts closest `.sc-node`; a correctly targeted
  relation button/SVG returns before hold/grip/selection gesture setup.
- All dense fixture objects are point agents; S02's new resize grips are
  built for capsule/window branches. Point content/hit areas are not wrapped
  by them. The new organization status surface is only built during an actual
  geometry action, absent here.
- `bandCandidate` excludes button targets, including mark descendants through
  `closest`. `onDocumentPointerDown` has new viewer/organization exemptions,
  but no preventDefault/stopPropagation; with the initial empty selection it
  returns immediately. Correctly targeted mark input cannot start the band.
- The changed normal mouse-click menu behavior lives in a scene-node gesture
  pointerup path, not mark delegation. `onInnerClick` only handles `.sc-origin`.
  New viewer dispatch is double-click/Enter/custom `jarvis:scene-open`; the
  test sends a single mark click. The new double-click handler also excludes
  buttons, and its node lookup does not find a relation mark.
- `JarvisSceneViewer.prepare()` is only entered by viewer opening. Neither
  mark click nor `JarvisRelationBoard.open()` calls it. Viewer styles/native
  dialog are created lazily; this graph plan never opens a viewer.
- F2 `beforePrompt` is called only when the canonical fullscreen controller
  arms a request. A mark click does not enter that controller or request
  fullscreen. No new admission listener or overlay bus intercepts it.

Thus no introduced handler interception or new modal/grip overlay is found
for a **correctly hit** relation mark. That does not establish that the
physical click in the failed run hit it, nor exclude timing/stack changes
elsewhere on the complete served page.

## Concrete existing moving-target mechanism; not yet an observed cause

The exact `_status_centre_browser.mjs` click path reads the current rectangle
center, awaits a CDP mouse move, then press, then release at those same
coordinates. It does not re-hit-test, remeasure between events, or record
their actual target. Its changed `clickCount` argument defaults to 1; the
ordinary `click` action still calls `mouse(arg,'left')`. The added double-click
and modifier support does not change this action's count or coordinates.

`MARK_TICK_MS=1000`, one-second transform transitions and an advancing orbit
move mark targets. Mark placement predicts the next second's endpoint.
Point hover/focus can raise its rank to `WINDOW_FLOOR-1` (219), above marks
at `WINDOW_FLOOR-2` (218); those declarations and focus/hover handlers are
unchanged. A pointer move can therefore change what covers its coordinates,
and CDP round-trip delay leaves time for a target to move. The test permits
20% of all marks outside the viewport and does not specifically prove
`rel_comm` is among the inside marks. These are concrete source conditions,
**not captured hit evidence or an attribution of the original failure**.

The task also adds JS to the complete served page; source identity cannot
measure its parse/render cost. The original failure has no retained per-event
hit targets, rectangle/phase at click, or failure-time console payload. It
does not support a conclusion about task-induced performance versus an
incidental existing moving-target miss.

If the exact current case passes, preserve that limited result. A separately
allocated bounded diagnostic can record the target's rectangle/viewport,
`elementFromPoint`, orbit timestamp and capture-phase pointerdown/up/click
targets, with timestamps before/after the actual CDP events, using transparent
page observers and the existing harness. Do not change product hit behavior,
freeze animations or replace the click merely to make it green. If failure
recurs, those observations distinguish missed mark/interception from a mark
click whose board handler failed. No such diagnostic was executed here and no
automatic waiver or registry ignore is proposed.

## F2 unit-count clarification

The retained actual F2 JUnit contains **39 fullscreen JS cases**, 3 object
viewer pure cases and 22 agent-reader cases: 64 total. The fullscreen file
therefore gained three cases; its absence/callback/error/local-ID behavior is
covered by that focused run. Browser arrival-order and active-fullscreen
proofs are recorded separately under S05 QA and independent S1 review. No
additional runtime was launched for this count inspection.
