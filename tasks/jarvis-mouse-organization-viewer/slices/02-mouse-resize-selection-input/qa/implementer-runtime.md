# Implementer runtime evidence

This is implementation feedback, not independent QA disposition.

Real headless Chromium, fully composed `ControlCenter.index` page, isolated `file://` harness and fetch fixture. Native CDP pointer/key events exercise production page/interaction modules. Tests never target the user's Jarvis ports/data.

Observed: all eight window and capsule handles change intended size/anchor; Ctrl-click + right-click preserves both IDs; keyboard context menu preserves both; Enter/double-click emit expected open seam; Ctrl+A preserves normal input selection; Shift toggle leaves frame identical at toggle, subsequent resize preserves segment ratio; Escape restores original geometry and clears held state without geometry command; Shift held at start preserves initial ratio and Ctrl+Arrow still resizes.

Browser plans count writes only after initial unrelated existing content auto-fit. No unexpected browser errors in eight-handle scenario. Window, capsule and menu visually inspected in `evidence/mouse-selection.png` at 1920×1080, circuit-board theme. Other themes/responsive viewer checks belong to S06 convergence.

Commands/results and baseline failures are recorded in ../IMPLEMENTATION.md. No camera or physical Bare Hands accepted here; canonical engine regression tests were exercised.
