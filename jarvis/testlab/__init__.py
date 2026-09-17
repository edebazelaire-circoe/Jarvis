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
"""
