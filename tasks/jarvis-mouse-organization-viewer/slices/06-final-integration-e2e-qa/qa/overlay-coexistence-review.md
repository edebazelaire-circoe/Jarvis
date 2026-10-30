# Real overlay coexistence — blocking native modality conflict

Actual isolated Core/SQLite + Control Center + Chromium, product identical to
frozen `97d56f11` (`git diff --quiet 97d56f11 -- jarvis`: exit0). Root released
the browser slot after its complete20-shard pass. Reused S05 LiveAcceptance,
production fullscreen command polling/controller and canonical actual
`POST /api/fullscreen/commands`; no fetch double or model call.

Before execution, inspected running python*.exe processes for **both** the
unique `-p owned_read_delay_plugin` identity and exact owned_read case. No
positively matching residual was found; no process was stopped. Evidence:
`owned-delay-process-cleanup.json`. No delay diagnostic was repeated.

## Result

Three prepared cases: **2 passed,1 failed in38.89s**. JUnit:
`overlay-coexistence-junit.xml`. No product edits or harness corrections.
All three actual scene revisions stayed20→20 and all Runtime exception
collections were empty. Owned Core/browser fixtures closed normally.

### F2 — BLOCKER: painted fullscreen prompt cannot receive input while viewer is modal

Actual canonical fullscreen request arriving while `#jvObjectViewer` is open:

- HTTP200 receipt says `state:needs_gesture`, deliveries1, armed60seconds;
- manual popover is open and parent is html; screenshot visibly shows it over
  the native viewer, with ordinary go/cancel buttons and countdown;
- elementFromPoint at **both actual button centers** does not reach those
  buttons (`hit:false`, `cancelHit:false`); native focus stays inside viewer;
- a real CDP mouse click on Cancel does nothing: viewer stays open and
  fullscreen state remains needs_gesture/armed;
- real Escape closes the viewer and restores `qa-note-a` focus; the same
  pending prompt then becomes hit-testable and actionable;
- browser fullscreen never enters automatically, and Board geometry/revision
  do not change. Canonical cleanup cancels the remaining owned arm.

Evidence: `fullscreen-request-during-viewer.json` and
`fullscreen-prompt-during-viewer.png` (visually inspected). The failed assertion
is the prompt button reachability check, not startup, selector or receipt
availability. Explicit `prompt.inert` property is false, but native modal
inertness applies outside the dialog's subtree independently of that attribute.
The combined actual hit test/click/focus observations establish the conflict.

The other arrival order also records a non-hit-testable armed popover while
viewer is open (`fullscreen-armed-before-viewer.json`: during.hitfalse).
That case's narrower post-close assertions pass: viewer Close restores an
actionable prompt, a real Go click enters actual browser fullscreen on the
scene host, scene dblclick correctly refuses viewer layering while fullscreen,
and canonical exit leaves fullscreen. The passing case must **not** be read
as proof that the pending prompt remained usable during the viewer.

This is an introduced coexistence regression relative to the old custom
body-inert modal system. html/manual-popover solved old custom inertness but
does not escape native dialog modality. Raising z-index or repeating
showPopover would not establish the required ownership/focus coordination.

### Ordinary panels/Settings/Studio — passed

`ordinary-panels-settings-studio-viewer.json` proves ordinary panel closure
on actual viewer opening, normal Settings Escape then supported scene opening,
viewer Escape/focus return, and a nonmodal Studio inspector retained behind
the modal without stealing focus. The inspector remains open after viewer
close, which is accepted preservation, not a missing closure requirement.
The probe never synthesized a supported scene click through inert Settings.

## Recommendation

Return F2 for bounded coordination rework using existing owners. The earlier
conditional note identifies viewer prepare/close/onClose and canonical
fullscreen state/cancel/controller composition seams; it was a proposal, not
an implemented fix or selected policy. PM must choose the exact visible,
actionable single-intent or coordinated-subtree behavior. No new fullscreen
engine, event bus or prompt copy is warranted.

Reverify the affected two arrival orders/cancel/Escape/focus/actual fullscreen
and unchanged scene state after rework, plus narrow controller hook tests if
added. Do not repeat the full suite for this diagnosis alone. PM owns final
disposition; no release-ready recommendation while F2 is unresolved.
