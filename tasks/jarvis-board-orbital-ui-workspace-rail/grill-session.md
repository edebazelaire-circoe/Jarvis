# Reconstructed Grill Session - Orbital UI refinement

This file reconstructs the user decisions that produced the handoff. It is not a verbatim transcript export. Where wording was not explicitly locked, this file says so.

## Starting visual complaint

The user rejected the current left side of the interface and much of the surrounding chrome. The Board itself was not the problem; the goal was to make the Board the hero and turn the surrounding controls into compact, meaningful, well-designed affordances.

The user explicitly asked for:

- keep the bottom-left mode/Board context control;
- remove the bottom-left hidden-object count capsule;
- replace it with a single eye / eye-off toggle;
- remove the bottom-center F9 start capsule;
- place notification/status icons in that bottom-center area;
- show alert count, completed task count, pending-question count, and possibly another meaningful category;
- make the left tool area a more stylish semi-circle / selection wheel instead of a rectangular bar;
- move presentations/documents from the left to a long right-side rail;
- show documents/media as recognizable visual cards with previews and type identity, not just color + title;
- blue status for work in progress, green for ready/done, yellow for new changes that need review;
- simplify upper controls and preserve the premium dark futuristic Jarvis direction.

A generated UI concept implementing those ideas was shown to the user. The user responded that it was exactly what they wanted. That image is preserved as `assets/target-ui-reference.png`.

## Decision Q1 - how the tool wheel appears

**Locked decision:** retractable wheel.

The user clarified that Jarvis supports Bare Hands and the wheel must be reachable from either input channel:

- Bare Hands: extend two fingers toward the left, or extend the hand toward the left, to summon the menu;
- then point/select without needing an initial click;
- use the existing finger-click/pinch gesture to activate the chosen item;
- Mouse: move the pointer toward the left edge/anchor and the menu appears.

The wheel is not permanently visible. Only a small visual core/anchor remains at the edge so the user can discover that something is there.

## Decision Q2 - persistent vs one-shot tools

User chose option C, hybrid behavior.

- interaction/control modes can stay active;
- one-shot actions execute, then leave the user in the prior interaction mode;
- ongoing recording is an exception in the sense that its capture channel remains active until explicitly stopped, but it does not need the wheel to stay expanded.

## Decision Q3 - scope of the wheel

User chose option C, contextual.

- wheel contains actions useful to the current surface/context;
- global settings/status do not belong in the wheel just because they exist;
- the wheel should remain quick to navigate with Bare Hands.

## User redefinition of the actual tools

The user then explicitly reset the proposed tool list and asked not to invent extra functionality.

### Selection

The `Selection` item opens selection-method choices. Only two are required:

1. Bare Hands
2. Mouse

Other selection modes/tools currently exposed can be removed from this selector.

The current Bare Hands icon is disliked and must be redesigned.

**Intelligent transition:**

- while Bare Hands controls the UI, an intentional mouse click immediately changes active control to Mouse;
- meaningful mouse movement can also trigger Mouse mode;
- the implementation must distinguish genuine intent from tiny/noisy mouse movement;
- once Mouse becomes active, Jarvis does not automatically jump back to Bare Hands;
- return to Bare Hands is manual through the selector or can be requested verbally from Jarvis.

This is an arbitration policy, not a new Bare Hands lifecycle owner.

### Capture

Exactly three direct capture buttons are required for now:

- Video
- Screenshot
- Audio

The user explicitly said more functionality can come later. Therefore the architecture should be extensible but the initial wheel should remain sparse.

## Decision Q5 - target selection for Video/Screenshot

User chose option C, hybrid target selection.

- simple activation uses a default target immediately;
- long press / secondary activation opens target choices;
- those choices must be backed by real supported capture capabilities.

The exact default target and exact list of available target choices were not locked in the discussion and must be reconciled with `docs/capture.md` and current adapters.

## Decision Q6 - Audio

User chose option C.

- simple activation starts recording;
- recording state becomes visibly active with duration;
- second activation stops;
- a long/secondary activation exposes available audio sources;
- active state remains visible when the wheel retracts.

## Decision Q7 - Video

User chose option C.

- simple activation starts recording immediately;
- wheel may retract;
- persistent `REC + duration` stays visible;
- second activation stops;
- long/secondary activation exposes target choices.

## Decision Q8 - Screenshot aftermath

User chose option C.

- screenshot is captured and saved immediately;
- a temporary, non-blocking thumbnail preview appears;
- quick actions: open, annotate, send to Jarvis, delete;
- if ignored, the preview goes away and never blocks the main workflow.

## Decision Q9 - right workspace/document rail

User chose option C.

The rail is an **active workspace**, not a general library. It represents documents/media/artifacts tied to the current context of work.

Each item should show an informative preview, type, status and lightweight metadata. Clicking opens or foregrounds the relevant item/surface.

The initial examples discussed include PowerPoint-like slide previews, Google Slides, video thumbnails with play affordance, and images.

## Final user instruction

The user asked to stop grilling and create the implementation task with high detail:

- document user expectations precisely;
- explain the UI transformation from the current state to the expected state;
- define implementation stages;
- define art direction;
- define terms clearly.

This handoff is the result.
