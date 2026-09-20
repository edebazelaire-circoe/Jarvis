# Documentation levels

| Concept | Current level | Required level | Gap / action |
|---|---:|---:|---|
| Native Bare Hands test mode | 2 | 3 | Existing code/tests exist; evolve into reusable modular contracts and validators. |
| MediaPipe asset/vendor contract | 3 | 3 | Preserve. |
| Bare Hands lifecycle OFF/SLEEP/ACTIVE | 0 | 3 | New explicit state machine + tests. |
| Stable hand identity | 0/1 | 3 | Current handedness-derived key is insufficient. |
| Gesture vocabulary | 0/1 | 2-3 | Define semantic events and deterministic recognizers. |
| Primary/secondary pinch | 1 | 3 | Primary exists; secondary/right-click and contact-like events need contracts/tests. |
| Target resolver | 0/1 | 3 | Current elementFromPoint is not a semantic resolver. |
| Frame manipulation zones | 0 | 3 | Define reusable zone schema and geometry helpers. |
| Bimanual resize constraints | 0 | 3 | Define axis ownership/conflict rules and tested solver. |
| Bare Hands Tools | 0 | 2-3 | Define tool contract + initial palette. |
| Bare Hands Settings | 1 | 3 | Current setting is only enabled boolean; introduce versioned schema and UI. |
| Calibration profile | 0 | 3 | Define schema, derivation and reset/fallback rules. |
| Tutorial flow | 0 | 2 | Define UX contract and content sequence. |
| Diagnostics/replay | 0 | 2-3 | Define trace schema + replay runner/benchmarks. |
| Clean-room/AGPL boundary | 2 | 2-3 | Existing comments/third-party lock document it; keep explicit in contributor docs/tests where appropriate. |
