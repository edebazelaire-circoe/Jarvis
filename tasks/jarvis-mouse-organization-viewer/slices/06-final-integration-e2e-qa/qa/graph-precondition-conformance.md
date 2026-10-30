# Dense 200% graph: canonical panel precondition, with an unchanged real click

PM approved this local test-only correction after an actual old-baseline
occlusion witness. No product source, pointer engine or shared harness changed.

## Observed evidence and limits

S1's retained baseline witness is commit `daef90ef`, review
`graph-baseline-occlusion-review.md`, raw
`graph-baseline-occlusion-witness.json` and run manifest in this QA directory.
At exact `c0858a80`, default natural orbit reached the specified old
presentation-rail occlusion after **85.352 seconds**. The unique native
pointer/mouse/click sequence targeted `#presentationRail`, and Board stayed
null after **8025 ms**. The page had 38 points, zero grips, no viewer, Runtime
exception or scene command. The existing orbit uses wall-clock modulo a
240000 ms period; launch phase therefore changes its target positions.

Fractional center EFP at x=447.1156 identified the rail, while an EFP using
integer MouseEvent.clientX=447 could identify the mark. Actual native event
targets, not that rounded-point re-query, establish where the click went.
This proves an existing occlusion mechanism. It **does not measure or prove
the cause of the original broad-gate or later exact-current failures**; those
raw red reports remain unchanged. The source-path/grip exclusions and 17
identity comparisons remain separate supporting evidence, not hit coverage.

## Exact bounded correction

Only the first (720×450 CSS viewport, scale 2) plan in
`test_a_dense_graph_at_200_percent_and_in_forced_colours_stays_usable` changes.
It first activates the existing **Replier le rail des présentations** button
if that panel is visible. Its unchanged owner handles the button through
`toggle(false,{restoreFocus:true})`, rendering/persisting the ordinary user
choice. It never writes `hidden`, style, storage or fake owner state directly.
The new assertion requires the real host present/hidden and owner.visible
false. This isolates graph layout/relation navigation from an unrelated
presentations panel; panel coexistence remains its own shell/rail test scope.

After the existing READ/layout measurements and optional screenshot, one
pre-click observation records complete-document readiness, exact mark
presence/visibility, unrounded rectangle and center, viewport dimensions,
center reachability and the actual element at that fractional center. A
second added assertion requires those readiness/hit conditions; failure
includes the captured target and geometry. Only the click center must be
within the viewport; the original overall mark-visibility criterion remains
unchanged. No wait for a favorable orbit, retry, direct mark.click(), alternate
target coordinate or frozen DOM/clock/animation is introduced.

The existing native CDP relation click remains byte-for-byte unchanged. Its
normal current-center calculation is still authoritative for its dispatch.
The new observation does not claim to record the later event's target; moving
targets can still cause a later real-click/Board assertion failure. Its local
1 ms action delay avoids adding the shared harness's default 300 ms pause.

Every original assertion predicate, all three original scenarios and the
existing eight-second WAIT_BOARD remain. The forced-colors and Cosmos plans
are unchanged. No fixture response, shared driver, timeout or product policy
was changed, and no failure was added to an ignore list.

## Verification performed here

Python compile and Node syntax checks of both new expressions pass (parsing
only). AST comparison verifies only the target function changed, exactly two
precondition assertions were added, every old assertion predicate is retained,
WAIT_BOARD is identical, and the other two plans are identical.
`git diff --check` passes. See [static log](graph-precondition-static.log).

No browser/runtime was launched by this correction's implementer. PM review
of the actual diff precedes S1's one independent modified original
three-scenario run. Runtime approval is pending; no test-pass, original-cause
or release-ready claim follows from static checks alone.
