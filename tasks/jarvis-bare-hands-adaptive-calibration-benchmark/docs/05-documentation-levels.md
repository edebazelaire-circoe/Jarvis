# Documentation levels

| Concept | Current | Required | Gap |
|---|---:|---:|---|
| Bare Hands lifecycle OFF/SLEEP/ACTIVE | 3 | 3 | preserve |
| Pinch press/release thresholds | 3 | 3 | extend with episode/timing contract |
| Calibration stage state machine | 3 | 3 | preserve, change result semantics |
| Calibration telemetry session | 1 | 3 | define schema + validator + privacy gate |
| User feedback taxonomy | 0 | 2 | define canonical semantic categories, keep free text |
| Diagnostic hypothesis | 0 | 2 | define evidence/confidence/trial outcome contract |
| Trial profile | 0 | 3 | define schema, invariants, apply/rollback/accept API |
| Pointing intent | 0/1 | 3 | canonical signal + renderer/controller conformance tests |
| Target preselection for all actionable targets | 1 | 3 | extend resolver/preview contract and tests |
| Target assistance calibration | 1 | 3 | define bounded parameters + ambiguity constraints |
| Benchmark exercise plan | 0 | 3 | schema, seeded generator, runner |
| Interaction quality score | 0 | 2/3 | define dimensions, formula, raw metrics and conformance tests |
| Calibration agent control plane | 0 | 3 | scoped tool/API schema + receipts + trace tests |
| Voice feedback during calibration | 1 | 3 | session routing and verified state/action receipts |

Slice 01 must close the foundational Level 0/1 contracts before behavior-heavy implementation is dispatched.
