# 00 - Product overview

## Problem statement

Jarvis currently exposes several independently evolved UI surfaces around the Board: Bare Hands lifecycle/tool controls on the left, a separate capture rail, a presentation rail also on the left, a bottom-left interaction-mode chooser, a right-side vertical diagnostic/tool dock, right-side notification pills, a Board control in the top bar, and a bottom-center voice hint. Each piece has useful behavior, but their combined composition is visually dense and conceptually fragmented.

The task is not to rewrite those domain owners. It is to **recompose their UI into a coherent workspace shell**.

## Vocabulary

### Orbital tool wheel
A retractable, semi-circular menu anchored to the left edge. It is a navigation/control surface, not a state owner.

### Wheel anchor / core
A small permanently visible visual fragment at the left edge. It provides discoverability and is the mouse activation hotspot.

### Selection method
The active way the user manipulates the surface: `Mouse` or `Bare Hands`. This is narrower than the broader Jarvis interaction mode (`SIMPLE`, `PRESENTATION`, `REUNION`). Never conflate them.

### Interaction mode
The product behavior mode defined in `docs/interaction-mode.md`. It remains controlled by the bottom-left context control and canonical Core status.

### Active workspace rail
The right-side list of work objects relevant to the current Board/session/work context. It is not a file browser and not a replacement for the full artifact manager.

### Notification/status center
The compact bottom-center row of categorized counters/actions. It is the visual successor of the right-side background pills, not an independent event source.

### Persistent recording indicator
A compact `REC + duration` / audio-recording state visible while recording even when the wheel is closed. Its state is projected from the canonical capture status.

### Intentional mouse takeover
A policy that moves selection control from Bare Hands to Mouse only when deliberate mouse use is detected. A click is always deliberate; movement needs hysteresis/debounce.

## User journey - expected primary flow

1. User works in the central Board with almost no permanent chrome.
2. They see a subtle left-edge anchor, bottom-left context control, bottom status center, and the right active-workspace rail.
3. They move the mouse to the left anchor or gesture left with Bare Hands.
4. The tool wheel expands around the left edge.
5. Hover/point highlights one item and shows its text label.
6. Activation executes the action. For Selection it opens Mouse/Bare Hands. For captures it starts/takes the capture.
7. The wheel retracts when the interaction leaves it. Ongoing recording remains represented by a persistent indicator elsewhere.
8. New tasks/questions/alerts appear as counts in the bottom status center without stealing central workspace area.
9. Work artifacts stay visible on the right as preview cards and can be reopened quickly.

## Current-to-target mapping

| Current surface | Target treatment | Preserve |
| --- | --- | --- |
| Bare Hands top-left lifecycle/tool UI | Lifecycle access remains available; direct work tools become retractable wheel | canonical lifecycle seam, settings/calibration/help/diagnostic routes where still required |
| Separate left capture rail | capture actions move into wheel | Core capture status, start/stop semantics, failure/recovery behavior |
| Left presentation rail | move/rebuild as right active workspace rail | open/present/edit/context actions, canonical presentation data |
| Bottom-left interaction mode | keep as permanent context anchor | `/api/status`, `/api/interaction-mode`, no optimistic mode state |
| Board topbar control | simplify/recompose; Board access must remain | canonical Board identity/switch operations |
| `F9` bottom-center hint | remove from this visual slot | keyboard F9 behavior itself may remain if still supported; only the capsule is removed |
| Right-side `bgpills` | horizontal bottom-center status center | category truth, unread counts, popovers/actions |
| hidden-object count capsule | compact eye toggle | canonical hidden-object visibility behavior |
| tall right diagnostic dock | simplify/top chrome or other discoverable route | functionality; no silent deletion of still-required tools |

## Success criteria

The implementation is successful when:

- Board remains visually dominant at normal desktop size;
- wheel is discoverable but absent from the main visual field at rest;
- wheel works with both Mouse and Bare Hands;
- selection arbitration is stable and does not flap;
- capture state stays truthful through reload/multi-tab/runtime changes;
- bottom center communicates work that needs attention in one glance;
- right rail visually communicates what each work item is and its state;
- no existing critical tool becomes inaccessible;
- overlays/Studio/Variantes/menus still stack correctly;
- keyboard and screen-reader paths exist for every action represented by gestures.
