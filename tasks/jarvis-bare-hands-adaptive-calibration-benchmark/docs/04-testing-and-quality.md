# Testing and quality

## Automated gates

- Deterministic unit tests for episode segmentation using synthetic traces at multiple frame rates and pinch speeds.
- Replay tests proving latency/false-positive metrics change when relevant parameters change and remain stable otherwise.
- Invariant tests for all trial-tunable parameter pairs and bounds.
- Tests proving trial apply/rollback/accept cannot silently persist the wrong state.
- Pointer-intent tests: tracked non-pointing hand => no cursor; credible intent => wake/active preview; loss of intent cleans up.
- Target tests for stars/buttons/window zones, nearest reasonable candidate, ambiguity, preview stability, and no physical pointer teleport.
- Agent trace tests using real calibration-session receipts: measurement facts cannot be invented or mutated by the agent.
- Benchmark tests with seeded exercise plans, stable scoring and no state mutation.
- Before/after comparison tests that distinguish measurement improvement from user learning by varying equivalent layouts.
- Migration tests from current profile/settings schema and current command vocabulary.
- Full existing Bare Hands suites remain green, including calibration, profile, pointer, gestures, target, recorder and commands tests.

## QA composition

Every implemented Slice: `qa-verification`.

Code: add `code-review`.

Runtime/user-visible behavior: add `runtime-validation`.

Agent prompt/tool/routing/control plane: add `agent-trace-analysis` with real trace evidence.

Current-Slice regressions block completion.

## Human validation

A real webcam is necessary for final subjective checks, but only after machine validation is clear. Human checks compare old/saved and trial profiles where possible and capture both measured metrics and the user's reported feel.
