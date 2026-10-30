# Final contract/evidence mapping — read-only S06 review

Reviewed integration `4cb4724f` against the canonical planning/main baseline
`c0858a8000e2ca23b57231edb8f46c643080ad07`, merged into this QA worktree at
`3a7bed50`. Scope: task README/product contract, S06 contract/testing matrix,
final S01–S05 implementation/independent reports, changed product paths and
neighboring fullscreen/keyboard/Bare Hands tests. No product/canonical-doc edits,
Chrome, pytest or model invocation during this review. S2's pending S06 source
regex/known-failure/layout schematic convergence and root's broad gate are not
claimed verified here.

## Acceptance map

| User contract | Existing evidence and ownership | Remaining limit |
|---|---|---|
| Eight edges/corners, bounds, Shift start/toggle/release, Escape | S02 independent17-test report: actual CDP16 edge/corner resizes, initial/toggled ratio and keyboard resize; shared hold/resizeBySides tests | Mouse hardware/Cmd on macOS not physically tested |
| Ctrl-click/group context/rectangle, menu keyboard, editable shortcuts | S02 actual native right-click/Menu/Shift+F10, Ctrl+A/editable exclusions and open intents; existing gesture-shield/interaction tests cover band/cancel/Delete/minus | Legacy suites must still pass the integrated broad gate |
| Atomic organization/resize/undo | S01 critical persistence/authority/compare QA; S05 pure every-action tests and real-Core fixed/orbit organization20→21/undo22; resize/pin seam in focused convergence test | No claim that opening viewer is a geometry operation |
| Atomic actual group mouse drag | Independent real baseline3 set_geometry/revisions20→23 versus final1 layout_selection/revision20→21, all targets/offsets/dimensions/selection retained | S05 author also exercised applied/refused orbit groups; independent real-Core fixed group plus orbit organization are distinct proofs |
| Auto/custom grids, align/distribute/equal sizes | S05 deterministic planner/reducer tests and actual page menu-action fixtures, graphical picker/refusal and3×8 numeric; nonresizable sizes refuse | S06 selected-layout visual aid is pending S2 convergence, not accepted by this review |
| Open via double-click/Enter/context, compatible selection and notice | S02 real opening intents; S05 integrated desktop/narrow menu/Enter/double-click fixture plus actual Core text/image/agent opening | No unsupported provider type is relabeled as a working preview |
| Viewer layouts/images/scroll/geometry/focus | S03 independent PM15-test UI review and critical bridge mutations;1/2/4/5/24 entries/both themes, zoom/pan, native scroll/history/pagination, focus/inert/restore,200%-equivalent viewport; S05 real registered image/text and actual wheel280→280 with identical DOM/revision/no scene POST | Real-world PDF preview is conditional provider_missing + canonical Open link; opaque prefab internals may reset under Host pause |
| Agent truth, public steps/findings/artifacts/unknown | S04 independently executed23 cases and privacy whitelist; S05 real public mission/activity/children/completion→restart unknown, canonical explains Artifact→Back | No published future plan is fabricated; optional token/tool counters aren't required UI hierarchy |
| Stop/Ask | S05 actual JobService cancellation and in-modal outcome; fresh canonical chat prefill rework independently3passed, retained A/B drafts, delayed cancellation, no send/Voice switch | Individual CLI Stop deliberately disabled; no new direct-agent control plane |
| Error/privacy/resource boundaries | Canonical typed request failures and visible in-dialog feedback; bounded loads/history/entries/undo/wire; S01/03 independent critical reviews/mutations | Successful real-model request unavailable: one actual CLI attempt hit weekly quota; public running→failed honestly recorded, no retry/mock |
| Accessibility/reduced motion/keyboard | Native dialog semantics/labels/inertness, actual Tab/ShiftTab/Escape/focus, reduced-motion/200%-equivalent tests; menu/open/undo/text-undo boundaries use existing canonical keyboard owners | No screen-reader hardware audit; one uninterrupted keyboard-only complete organization journey is composed from existing seams rather than separately recorded |

## Legacy regression coverage: evidence versus pending gate

- **Prefab pointer shield:** S02 independently reran prefab page redraw/iframe
  sibling safety, and reported29 shared shield/hold tests. Existing
  `test_scene_gesture_shield_js.py` covers shield press/release/cancel/blur,
  held-hand coexistence, selection band and iframe selection. New grips remain
  sibling hit targets and canonical Host remains iframe owner.
- **Bare Hands/keyboard:** optional mouse-side/aspect arguments leave omitted
  Bare Hands defaults unchanged. Existing `test_barehands_interaction_js.py`,
  shared hold desk/hold contract and keyboard-resize tests directly exercise
  those canonical seams. S02 reported selected practice/min/body/frame cases;
  the stale practice expectation is a proven baseline issue, being handled in
  S06. Real camera tracking was not invoked. Root's integrated suite is still
  required; source reuse alone is not a pass result.
- **Browser fullscreen:** `test_fullscreen_browser.py` already covers true
  host enter/exit/restore, actual activation, command→prompt→click, timeout,
  unsupported display and prompt above the old custom confirm/inert system.
  These tests do not combine the new native viewer modal with an armed manual
  popover. Product `prepare()` rejects already-active browser fullscreen.
  No Fullscreen owner was modified by this feature.
- **Chat/ordinary shell overlays:** canonical chat scope rework was independently
  verified; S03/S05 actual modal focus boundaries and normal panel closure are
  recorded. Shell registry and source-test convergence plus broad neighbors
  remain root/S2's gate. Nonmodal Studio inspector state retained behind an
  inert native viewer can be acceptable preservation, not a new closure rule.

## Meaningful pending coexistence check

No new proven product blocker is established by this static review. The one
specific runtime gap is native-dialog/manual-popover coexistence. A dedicated
QA-only `test_overlay_coexistence.py` now reuses S05's real LiveAcceptance
fixture, production command poll/controller and actual CDP input. **Prepared,
not executed**; PM releases the browser slot after the broad gate.

Planned cases: fullscreen prompt armed before viewer, viewer Close then actual
prompt click/true fullscreen and active-fullscreen viewer refusal; request
arriving while viewer is open with prompt paint/hit/focus and actual Cancel;
Escape/focus/geometry; ordinary panel close, normal Settings Escape boundary
and nonmodal Studio focus inertness/state. The test does not synthesize a scene
user event through an inert Settings modal. It records screenshots, browser
exceptions, canonical request/receipt traffic, public fullscreen state and
real scene revisions before interpreting any failure.

Source facts, correcting an initial hypothesis: `fullscreen.arm()` appends to
`html` and calls `showPopover('manual')`, so one cannot assume its prompt is
painted behind the viewer. Native modal inertness/hit testing still requires
the browser. `handle(command)` only arms/returns needs_gesture; it never calls
requestFullscreen. Countdown runs independently; expiry removes the prompt,
logs arm_expired and reports canonical expired. Thus no infinite pending wait
or automatic command-driven entry is inferred. Actual focus/hit/cancel and
post-close actionability must still be measured; no new fullscreen engine is
proposed.

## Release boundaries

Root's complete canonical release gate and failure dispositions remain pending.
Human review remains required on a concrete isolated preview before main
merge/Drive done. Preview helper is already committed and smoke-stopped; no
persistent preview was launched. Physical screen reader, camera/Cmd hardware,
multi-monitor permissions and successful quota-blocked model execution remain
truthful limits, not substituted claims. Historical S02 baseline wording about
group drag is superseded by the explicit S05 atomic correction/amendment and
real before/after evidence; canonical shipped semantics now describe the fixed
shared seam.

## S06 convergence source addendum

Subsequently merged root's exact full-gate revision `97d56f11` into the QA
worktree at `bbf09459`, read-only. No root HEAD change or execution was performed.
Inspected the small source diff: the selected-layout schematic is a bounded,
aria-hidden decorative grid beside the existing labeled select, with current
layout/dimensions in its title. It reuses the current layout plan and does not
mount content, change geometry, rank a new layer or add a parallel layout owner.
The raw404 refinement changes only user-visible copy; it retains the same
degraded public model/provenance. No new blocker found in those product edits.
S2's own focused source-guard/browser proof and root's running sequential broad
gate remain separate evidence. The prepared coexistence probe still has not
been launched and awaits PM's explicit browser-slot release after that gate.
