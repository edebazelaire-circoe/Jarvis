# Bare Hands "leftward reveal" gesture for the tool wheel

- **Found in:** Slice 02 (orbital tool wheel), 2026-10-16.
- **Not a regression.** Deferred by decision O02 / `docs/06-resolved-architecture.md` §4 (last bullet).

## Context

The grill session described the wheel opening when the user moves "two fingers toward the left" in
Bare Hands. No such gesture exists in the canonical Bare Hands vocabulary
(`docs/barehands-contracts.md`: pointer, primary pinch = `click`, thumb + middle pinch =
`contextmenu`, no long press - decision 22).

## What Slice 02 ships instead

No new gesture. In ACTIVE the hand drives the synthetic pointer (`pointerId` 9001-9002); the hand
pointer reaching the left-edge anchor dispatches the same `pointerover` as the mouse and opens the
wheel; a primary pinch on a wedge is a `click` and fires once
(`tests/unit/test_tool_wheel_browser.py::test_bh_synthetic_pointer_9001_opens_and_pinch_fires_once`).

## Open question for a later task

Whether a dedicated directional gesture (swipe left, two-finger leftward motion) is worth adding to
the Bare Hands recognizer. It would need: a gesture definition and thresholds in the Bare Hands
contracts, false-positive measurements against the existing calibration corpus, and a mapping to
`JarvisToolWheel.open()` (the API already exists). Human product decision required before any work.
