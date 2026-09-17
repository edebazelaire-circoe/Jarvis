# Slice execution order

Start with `00-project-manager`; it is the readiness gate and is not delegated. Then execute according to dependencies.

- [x] `00-project-manager` — Project Manager readiness and orchestration gate
- [x] `01-testlab-domain-contracts` — Test Lab domain contracts and schemas
- [x] `02-run-persistence-artifacts` — Persistent TestRun and artifact store
- [x] `03-diagnostic-bundle` — DiagnosticBundle normalization and session capture
- [x] `04-catalog-scenarios` — Diagnostic catalog, manifests, and safe ad-hoc scenarios
- [x] `05-supervisor-worker` — Run supervisor and isolated worker lifecycle
- [x] `06-virtual-profile-harness` — Virtual profile from async conversation harness
- [ ] `07-metrics-scoring-sweeps` — Metrics, scoring, comparisons, and parameter sweeps
- [ ] `08-audio-live-profiles` — Controlled audio and live-provider profiles
- [ ] `09-hardware-guided` — Hardware auto/guided profiles and resource gates
- [ ] `10-control-center-api-cli` — Native API, CLI, and Control Center HTTP surface
- [ ] `11-control-center-ui` — Control Center Test Lab UI
- [ ] `12-seed-diagnostics-rollout` — Seed diagnostics, end-to-end rollout, docs, and retention

Do not dispatch any implementation Slice until Slice 00 declares `READY`.
