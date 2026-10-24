# 04 — Testing and quality

## Per-Slice machine QA

Every implementation Slice requires:

- `qa-verification`;
- `code-review` for code changes;
- `runtime-validation` for user-visible behavior;
- focused automated checks relevant to the touched view;
- screenshot capture at the reference viewport;
- one narrower responsive viewport;
- keyboard/focus validation for interactive controls.

Use existing test/build/lint commands discovered during Slice 00. Do not invent a parallel test stack when one already exists.

## Visual regression

Each page Slice must produce deterministic screenshots using fixtureable state. Compare against the corresponding reference for:

- major regions and hierarchy;
- card grouping and spacing;
- border radius and panel treatment;
- cyan/blue/purple accent hierarchy;
- typography scale and label density;
- alignment of controls;
- overflow/scroll ownership;
- popup/dropdown layering;
- responsive collapse behavior.

Pixel-perfect equality is not required where live data differs, but unexplained structural divergence is a failure.

## Final QA

Slice 07 runs the final repository-appropriate unit/integration/E2E suite and the cross-page visual regression set. If suites can be isolated, run them concurrently; otherwise run them in the same final validation phase.

## Regression doctrine

A regression caused by this task is blocking and cannot be moved to `Issues/` as accepted debt.

## Human validation

Human checks occur only after machine QA is clean. The reviewer is shown the implementation next to the matching reference image and validates visual hierarchy, polish and interaction feel.
