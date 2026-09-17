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
- `jarvis.testlab.runs`: `TestRun` record and its state machine.
"""
