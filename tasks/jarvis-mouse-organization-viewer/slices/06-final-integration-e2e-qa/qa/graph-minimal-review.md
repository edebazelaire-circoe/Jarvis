# One minimal exact graph capture — passed, original miss not observed

PM allocated exactly one current original3-scenario test with raw output
retention after the exact current retry re-failed and the first passive prefix
did not reproduce. This allocation is complete; no repeat loop was run.

## Method and actual result

QA copy of the existing Node driver changes only the existing center
Runtime.evaluate body to retain rect/EFP/rail/ancestor data and install small
passive native event-target observers. The existing final server evaluate
returns those fields. Native mouse method sequence, coordinates calculated
from the same rectangle, clickCount/default modifiers, test plan/seed/waits,
three scenarios and original assertions remain unchanged. **Zero additional
CDP roundtrips**, no animation freeze, DOM mutation, geometry write or retried
click. A Python subprocess-output wrapper saves complete raw JSON before
pytest assertions, without changing the running browser. Observation can
still add small in-page computation; no exact timing equivalence is claimed.

Exact original current case **passed in19.89seconds**, once. Evidence:
`graph-minimal.log`, `graph-minimal.xml`, `graph-minimal-run.json`,
`graph-minimal-raw.json`, metadata/captures, `graph_minimal_capture_plugin.py`
and `run_graph_minimal.py`. Copied driver path and original source SHA256 are
retained in metadata. No model/hardware/live runtime; canonical owned-profile
cleanup and original fixtures used.

Dense scenario actual center(384.0539,249.6753), visible rail x448..720. EFP
at sample and native pointer/mouse/click targets all resolve to `rel_comm`.
The marker moves≈0.76px between center sample and click but remains under the
point. All38nodes are points, zero grips, viewer absent. Communication board
opens normally; forced-colour and Cosmos assertions also pass. No Runtime or
error-console entry. This is successful normal handling, **not a captured
version of the original miss**.

## Causal assessment and limits

Relevant relation/layout/roles/board code and ranks are unchanged. Relation
buttons are in sc-relmarks, not sc-node; the new node resize/hold path returns
before acting on such a target. Viewer opening requires node Enter/double-click,
not this one ordinary relation click. Point-only fixture produces no new
window/capsule grips; no viewer CSS/modal or fullscreen request is created.
The driver retains its original one-center/three-native-events sequence.
These source facts and measured target-path evidence exclude added grip or
viewer interception **in the observed successful path**.

Original current broad-gate and exact-retry boardNone failures remain red.
Baseline's pass and later current captures' passes do not prove baseline
flakiness, exact scheduling cause or the original event target. Existing
rail occlusion and point hover/focus ranks are plausible conditions, but no
failed target/occlusion was captured. The original shallow board wait alone
cannot distinguish them. Do not waive the graph from a passing probe.

No further runtime is initiated here. If PM requires a new bounded discriminator,
a separately allocated **baseline natural-condition witness** could wait once
for rel_comm's center to be intercepted by the existing rail/point (bounded
predicate, no frozen clock/DOM positioning), perform one native click and
retain both actual target and board result. It would demonstrate an unchanged
reachable miss mechanism, not reproduce the original current event or justify
repeat-until-fail. If the condition never occurs within the allotted window,
report inconclusive. Alternatively PM may elect a local test readiness
correction requiring an actually hit-testable intended button before one
native click, preserving all original graph/board assertions; that is a policy
decision, not a fix silently made by QA. Original attribution remains open
pending PM's source/evidence disposition.
