# 04 - Testing and Quality

## Layers

- Unit/contract tests for domain schemas, manifests, scoring, permissions, stores.
- Deterministic integration tests for supervisor/worker lifecycle and virtual profile.
- Audio-chain tests where physical acoustics are not required.
- Opt-in provider live tests.
- Workstation `hardware:auto` and `hardware:guided` acceptance for real acoustics.

## Required regression behavior

Normal CI must remain deterministic and cheap. Category 2 live/hardware diagnostics are opt-in/selective and must not silently enter every release run.

## QA doctrine

- Every implemented Slice gets `qa-verification`.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent/tool/routing/module/runtime changes add `agent-trace-analysis` with real trace evidence.
- Regressions introduced by the current Slice are blocking.
- Human validation is only after maximum reasonable machine validation.

## Evidence expectations

Every TestRun should make it possible to understand what executed, against which code/config, with which parameters, and why it passed/failed. Metrics and assertions are primary; a score is a synthesis.

## Seed regression scenarios

- No false self-barge-in while Jarvis speaks.
- Real interruption stops output and admits the new turn.
- Brain speech payload is delivered faithfully without replaying previous text or surface improvisation.
- Stale/superseded speech is not delivered after revision.
- Queue latency and speech-ready-to-play delay are measurable.
