# Decision log

1. Webcam-only V1; specialized hardware is deferred, but a future Pro tracker must fit the architecture.
2. Jarvis-only V1; exploit DOM/component semantics instead of solving arbitrary desktop apps.
3. No permanent pointer; target feedback appears only when interaction intent is detected.
4. Lifecycle is OFF/SLEEP/ACTIVE. OFF releases camera; SLEEP keeps a lightweight watcher; ACTIVE runs full interaction.
5. Wake gesture is a C-like pre-pinch posture held about one second with circular progress feedback.
6. UI button and voice commands also activate/deactivate Bare Hands.
7. 30 s with no usable hand returns ACTIVE to SLEEP.
8. BODY is content interaction, not a frame move handle.
9. Frame edges/corners are manipulation zones.
10. One zone capture moves the entire frame.
11. Two compatible zone captures on the same frame produce constrained resize.
12. Two hands on different objects stay independent.
13. Zone capture latches until release.
14. ZONE + BODY never forms resize.
15. Same-zone double capture is rejected.
16. Edge + overlapping corner: edge owns the shared axis; corner only its remaining axis.
17. Two corners sharing an axis neutralize that shared axis.
18. Crossing hands never invert geometry; clamp at minimum size.
19. Resize -> move transition is rebased to avoid jumps.
20. Primary pinch is thumb + index.
21. Secondary/right click is thumb + middle finger.
22. Right click is not encoded as long press. Primary pinch duration/movement still contributes to click/drag/scroll intent.
23. Feedback colors: body/normal blue, manipulation zone yellow, right click red.
24. Target preview is configurable in Bare Hands Settings.
25. Tools and Settings are separate concepts.
26. Calibration and tutorial are separate flows in one overlay shell.
27. Calibration is optional and explicit.
28. One simple visible profile in V1, with internal per-hand parameters allowed.
29. V1 calibration is statistical/threshold-based, not personalized ML.
30. No continuous auto-learning in V1.
31. Partial calibration is valid; failed functions fall back to standard defaults.
32. No images/video retained by default; only derived parameters and quality metrics.
33. Native implementation remains clean-room/non-AGPL relative to pinned upstream Barehands.
