# Testing and quality

## Required automated gates

### Main HUD lifecycle control

- state visual mapping OFF/SLEEP/ACTIVE;
- direct selection of all three modes;
- selecting OFF really releases/tears down camera resources;
- state button updates after C-wake, voice/MCP activation/deactivation, inactivity sleep, and error/recovery;
- no duplicate local lifecycle source of truth.

### Tool palette

- palette lists exactly installed tools from canonical contract (`pointer`, `pan`, `select` at reviewed snapshot);
- one-click selection updates the canonical tool state;
- external tool changes update palette selection;
- unavailable/future tools cannot appear as working controls without engine support;
- Tools section is absent from Settings after migration.

### Context menu/help/diagnostics

- right-click opens Settings / Calibration / Help / Diagnostics;
- no Tutorial or activation item;
- Help does not claim unbound gestures are actions;
- Diagnostics opens/reuses current recorder surface;
- keyboard/focus behavior is accessible.

### Calibration shell and timing

- shell covers viewport and does not render the old centered-card composition;
- intro delay does not consume active stage timeout;
- idle/no-hand user can remain in ARMED without timeout on gesture/posture steps;
- target appears only after reading delay;
- window practice appears after reading delay;
- Escape/close/skip cleanup remains deterministic;
- result/fallback states remain truthful.

### Calibration sequence

- exact public sequence has six exercises + completion;
- primary and secondary pinch use distinct illustrated fingers;
- target test is driven by primary pinch, not pointing-only visual semantics;
- target positions cover meaningful viewport areas;
- window 6A validates one-hand zone capture + move;
- window 6B validates two-hand compatible-zone resize;
- practice window does not persist into real scene state;
- stage uses canonical target/capture/geometry implementation.

### Tutorial migration

- no separate tutorial entry in right-click menu or Settings;
- no distinct tutorial overlay can be launched accidentally;
- legacy command behavior is explicit and tested (preferred alias to calibration if retained);
- stale `tutorial_seen`/related persistence is migrated or harmlessly tolerated according to chosen schema strategy.

## QA doctrine

Every implemented Slice receives `qa-verification`. Code changes add `code-review`. User-visible/runtime changes add `runtime-validation`. Agent/MCP/tool/routing changes add `agent-trace-analysis` with real trace evidence. QA agents return evidence; Project Manager owns the decision.

A regression caused by the current Slice is blocking. Human validation happens only after machine validation is exhausted.

## Human validation focus

Human checks should evaluate the things automated tests cannot fully establish:

- discoverability and readability of the main button;
- visual distinction among OFF/SLEEP/ACTIVE;
- speed of tool switching;
- Help card clarity;
- calibration pacing and visual calm;
- whether the schematic hand is simple enough;
- whether window move/resize practice feels like the real Jarvis interaction.
