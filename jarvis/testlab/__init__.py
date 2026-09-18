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

Slice 06 adds the `virtual` execution profile (`jarvis.testlab.virtual`): the
production voice path mounted in memory with controlled doubles, and the five
registered `virtual` runners.

Slice 07 adds synthesis and experiments: the pure `jarvis.testlab.scoring`
(the declared `weighted_mean`, computed by the supervisor),
`jarvis.testlab.outcomes` (how a terminal run READS: passed / failed /
inconclusive / refused / crashed / cancelled, derived from status and failure
code), `jarvis.testlab.compare` (per-metric deltas, assertion changes,
incomparability, aggregates) and `jarvis.testlab.sweeps` (the sweep declaration,
its expansion and its record), plus the I/O modules
`jarvis.testlab.sweep_runner` (`SweepRunner`: bounded fan-out over a supervisor,
partial failure, cancellation, the summary artifact) and
`jarvis.testlab.filesystem_sweep_store` (`FilesystemSweepStore`).

Slice 08 adds two more execution profiles and the device gate:
`jarvis.testlab.audio` (the real local audio chain over an injected fixture; no
device, no provider), `jarvis.testlab.live` (a real provider session, behind four
mechanical gates) and `jarvis.testlab.devices` (READINESS B9: is the live Jarvis
using the workstation's microphone, and the shared Test Lab device lease).

Slice 09 adds the two profiles that open real devices,
`jarvis.testlab.hardware`: device selection and the honest failure mapping
(`devices`), the guided interaction contract with the human as a scenario actor
(`prompts`), the file channel a worker addresses a human through (`channel`), and
the four registered runners (`runners`, `registry`).

Slice 10 composes and exposes the whole subsystem: `jarvis.testlab.composition`
(`TestLabConfig` / `TestLab`: roots under `<runtime>/testlab/`, policies, the one
shared store, and the capability grant read from the process environment),
`jarvis.testlab.api` (`TestLabApi`: every operation once, as documented
JSON-ready shapes, with every synchronous store call in `asyncio.to_thread`),
`jarvis.testlab.cli` + `__main__` (`python -m jarvis.testlab`, human-readable or
`--json`, with exit codes that tell the outcomes apart),
`jarvis.testlab.presenter` (the guided presenter: prompt, deadline, live
countdown) and `jarvis.testlab.http` (`/api/testlab/...` on the Control Center's
aiohttp application). Nothing in that layer decides anything: it exposes what
Slices 01-09 derive.
"""
