# 00 - Overview

## Goal

Implement a native Jarvis Category 2 Test Lab for targeted diagnosis after observed failures. It must expose deterministic diagnostic capabilities to humans, Jarvis, coding/debug agents, Control Center, CLI, and later an optional MCP facade.

## Mental model

`incident -> DiagnosticBundle -> targeted diagnostic -> isolated TestRun -> metrics/assertions/artifacts -> compare/sweep -> cause isolated -> optionally promote scenario`.

## Scope

- Test Lab domain contracts, catalog, manifests, safe ad-hoc scenarios.
- Persistent TestRuns and artifacts.
- DiagnosticBundle ingestion from real sessions.
- Supervised isolated workers.
- Virtual/audio/live/hardware profiles.
- Per-diagnostic metrics/assertions/scoring and run-local sweeps.
- Mechanical cost/resource permissions.
- Native API, CLI, Control Center API/UI.
- Seed diagnostics for self-echo/barge-in, speech payload integrity, stale speech/supersession, and latency/queueing.

## Non-goals

- No embedded LLM/debugging intelligence.
- Not part of every normal CI run.
- MCP is not the core contract.
- No arbitrary Python in ad-hoc scenario definitions.
- No automatic permanent configuration writes.
- No hidden chain-of-thought persistence.
- No unlimited audio retention.
