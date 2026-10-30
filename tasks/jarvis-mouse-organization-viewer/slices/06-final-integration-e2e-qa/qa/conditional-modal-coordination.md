# Conditional reuse path — not a confirmed defect

Read-only preparation at full-gate product revision `97d56f11`. No probe,
browser, pytest, model or product edit. This note applies **only if** the
prepared real-browser coexistence scenario demonstrates a broken prompt,
Escape/focus interaction or invisible entry. Native modal inertness differs
from the old custom body-inert system, but source alone does not establish the
actual browser outcome.

## Existing owners and useful seams

- `JarvisSceneViewer.create(...).prepare()` already performs modal/fullscreen
  admission and calls injected `beforeOpen`. The scene page composes this hook
  to cancel gestures/key edits/bands and close ordinary menus/panels.
- `JarvisObjectViewer` owns the native dialog, provider disposal/abort,
  history, clocks and focus return. Its public `close()` and existing
  `onClose` callback are the correct cleanup seams. Closing it must not be
  replaced by removing the DOM or manually toggling open/inert attributes.
- `JarvisFullscreenCore.createFullscreenController(deps)` owns arming,
  prompt DOM/top-layer membership, requestFullscreen, timer, transition,
  receipts and focus restoration. Installed page API already exposes
  `JarvisFullscreen.state()`, `.cancel()` and `.exit()`.
- `cancel()` calls canonical cancelArm: clears ticker/deadline, removes the
  prompt, restores focus, transitions to exited, logs arm_cancelled and reports
  `fullscreen_cancelled`. This is an explicit canonical cancellation, not a
  dropped or expired request.
- `handle(command)` only arms; it never auto-enters fullscreen. `expireArm`
  continues its normal deadline independently and reports expired. Only an
  actual prompt click or the existing local enter seam calls requestFullscreen.

There is no existing general native-modal coordinator in input arbitration;
that module owns mouse/Bare Hands method arbitration. Reusing it as a modal
bus would conflate unrelated concepts. The appropriate composition point is
the current scene viewer admission hook plus the existing fullscreen owner.

## Smallest conditional response, after evidence/PM policy choice

Prefer one active modal intent at a time over a new suspension mechanism. If
the actual bug is an inert fullscreen prompt outside the native dialog, a
bounded coordination change can keep all lifecycle/transport logic in the
current owners:

1. Before viewer admission, use the existing fullscreen state/cancel seam for
   an already armed prompt, or refuse viewer admission with an explicit
   explanation if PM elects to preserve that pending request. Do not merely
   hide its DOM while leaving the broker armed.
2. For a fullscreen request arriving during the viewer, add at most a local
   optional controller dependency such as `beforePrompt` at the installed
   composition point, calling the viewer owner's existing close seam before
   the canonical controller builds/focuses its ordinary prompt. The scene
   viewer instance is private today; expose only that narrow local close
   callback through the existing scene facade or inject the callback when
   wiring the two owners. No event bus, new backend route, new fullscreen
   controller or provider changes are needed.
3. Use the canonical cleanup order: viewer close/dispose/focus completes,
   then fullscreen arm chooses/restores focus and starts its existing timer.
   No automatic requestFullscreen is added. Geometry, Board selection and
   pin state remain unaffected.

The policy of dismissing transient viewer state when an explicit fullscreen
request takes precedence must be confirmed by PM from the probe; it is not
silently approved by this QA note. A typed refusal/defer policy is also valid
if it remains visible/actionable and uses existing canonical receipts. Its
exact status/code must follow the existing domain vocabulary rather than
labeling a modal conflict as an unrelated browser denial.

If preserving both surfaces is required instead, the canonical fullscreen
owner would have to mount its prompt within the active native dialog's
non-inert subtree, using the viewer's existing onClose/abort seam to cancel or
relocate it safely when that dialog closes. That is a larger lifecycle change
than single-intent coordination and must not be achieved by copying prompt
buttons/countdown into the viewer. Arbitrary z-index changes cannot fix native
modal inertness. Direct `dialog.close()` from another owner is also inferior
to the viewer close API because cleanup/focus timing belongs to that owner.

## Required re-verification if rework is needed

Use the already prepared real-harness cases for both arrival orders, actual
prompt hit/cancel/click, explicit browser fullscreen enter/exit, Escape/focus,
request timeout and unchanged real scene revision. Add only focused unit
coverage for the chosen optional callback/no-callback/failure behavior. Keep
ordinary hosts and nonmodal Studio state unchanged. Run affected checks after
the broad gate; no competing browser process is launched during it.
