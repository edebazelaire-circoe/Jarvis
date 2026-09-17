"""Category 2 Test Lab: native, deterministic diagnostic subsystem.

Binding contract: `docs/testlab.md`. Slice 01 provides the pure domain
contracts only (no I/O, no implicit clock, no provider/transport import):

- `jarvis.testlab.validation`: errors, JSON/text/time guards, redaction and
  forbidden-code guards, canonical fingerprint;
- `jarvis.testlab.identity`: schema version, diagnostic id/version, run, sweep
  and bundle ids;
- `jarvis.testlab.profiles`: profile names, capabilities, cost bounds and the
  mechanical permission check;
- `jarvis.testlab.diagnostics`: parameters, metrics, assertions, score
  declaration and `DiagnosticSpec`;
- `jarvis.testlab.scenarios`: safe declarative `Scenario`;
- `jarvis.testlab.runs`: `TestRun` record and its state machine;
- `jarvis.testlab.store`: run store port, query/usage types, update rule (pure);
- `jarvis.testlab.retention`: retention policy, planner and apply step (pure).

Slice 02 adds the I/O modules `jarvis.testlab.filesystem_store` (durable
filesystem adapter) and `jarvis.testlab.capture` (git identity, environment,
redacted configuration snapshot).

Slice 03 adds the DiagnosticBundle: pure `jarvis.testlab.bundle` (schema, codec),
`jarvis.testlab.bundle_rules` (anomaly rules), `jarvis.testlab.bundle_builder`
(builder), `jarvis.testlab.redaction`, and the I/O modules
`jarvis.testlab.bundle_capture` (capture service) and
`jarvis.testlab.filesystem_bundle_store` (bundle store).

Slice 04 adds the catalog: `jarvis.testlab.primitives` (registered scenario
primitive vocabulary, a superset of the `jarvis.voice_replay` action DSL),
`jarvis.testlab.implementations` (in-code registry of implementation names),
`jarvis.testlab.manifests` (manifest and catalog-lock codec),
`jarvis.testlab.promotion` (ad-hoc scenario -> official manifest content), plus the
I/O modules `jarvis.testlab.catalog` (loads `jarvis/testlab/official/`) and
`jarvis.testlab.replay` (replay fixture codec and scenario adapter, which
`tests/replay/voice_replay.py` re-exports).

Slice 05 adds execution: the pure worker protocol `jarvis.testlab.jobs`
(`WorkerJob`, `WorkerResult`, failure codes), the runner seam
`jarvis.testlab.runners`, and the I/O modules `jarvis.testlab.supervisor`
(`RunSupervisor`: queueing, resource reservation, bounds, adoption, upkeep),
`jarvis.testlab.worker_launcher` (process start and tree kill),
`jarvis.testlab.worker` (the child process, `python -m jarvis.testlab.worker`),
`jarvis.testlab.maintenance` (scheduled store upkeep) and
`jarvis.testlab.selftest` (the `selftest.worker` TEST FIXTURE diagnostic, never a
seed diagnostic).
"""
