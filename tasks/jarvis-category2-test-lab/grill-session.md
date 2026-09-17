# Grill session - reconstructed

This file is a faithful reconstruction of the architecture grill conducted in the current ChatGPT session on 2026-09-12. The exact host transcript is not available as a durable export, so this is explicitly reconstructed rather than claimed verbatim.

## Starting point

The user wanted Category 2 diagnostics to be invoked selectively after a problem is observed, not on every test run. The desired loop is: observe a real symptom, let an agent inspect the transcript/trace, run only relevant diagnostics, replay phrases or simulated human interactions, inspect the output, score results, and iterate until the failure is isolated. The same facilities must also be usable manually from Jarvis through a visual interface.

Before grilling, the repository was rechecked. Important findings included:

- Existing `tests/unit`, `tests/integration`, `tests/e2e`, and fixtures.
- `tests/integration/async_conversation_harness.py` already runs most production layers in memory with only Realtime, audio, and brain doubles.
- Existing integration scenarios already simulate a human interruption after a known number of audio chunks and verify `played_ms`, cancel/truncate, new intent handling, and stale result suppression.
- Current `main` had already evolved beyond the incident transcript: `realtime_audio.py` contains guard-aware provider VAD handling and Solo Owner logic, so the Test Lab must diagnose current behavior rather than encode stale hypotheses.
- Control Center already has HTTP endpoints and an audio-device test path.

## Decision 01 - Native subsystem vs pytest family

Question: Should Category 2 be an advanced extension of `tests/`, or a native Jarvis Test Lab used by pytest, agents, and UI?

Recommendation: native subsystem.

User decision: **B - native Jarvis Test Lab**.

## Decision 02 - Diagnostic identity and realism profiles

Question: Separate tests such as `self_echo_virtual` / `self_echo_live`, or one logical diagnostic with specialized execution profiles?

Clarification: Under option B, a diagnostic has one behavioral identity and common metrics, but each profile can have its own implementation. This avoids forcing a universal DSL across incompatible environments.

User decision: **B - one diagnostic identity with specialized profiles**.

## Decision 03 - Intelligence ownership

Question: Should Test Lab itself choose tests and loop intelligently, or remain deterministic while an external agent/human reasons over it?

User clarified that Test Lab should act like a tool/MCP surface: rich debug capabilities, no intelligence embedded.

User decision: **B - deterministic and agent-agnostic**.

## Decision 04 - Canonical access contract

Question: Make MCP the foundation, or use a native core API with thin adapters for internal callers, HTTP/Control Center, CLI, and optional future MCP?

User decision: **B - native Core plus adapters; MCP optional**.

## Decision 05 - Run lifetime

Question: Ephemeral results, or a persistent `TestRun` object containing snapshot, parameters, metrics, transcript/timeline, score, and artifacts?

User decision: **B - persistent, comparable, replayable TestRun**.

## Decision 06 - Isolation

Question: Run experiments against the active Jarvis runtime, or isolate them from the production conversation/configuration?

User decision: **B - isolated by default; real resources only when required by profile**.

## Decision 07 - Scoring contract

Question: One universal score formula, or per-diagnostic metrics/assertions/score with optional dashboard aggregation?

User decision: **B - diagnostic-specific score contracts**.

## Decision 08 - Permanent vs ad-hoc experiments

Question: Catalog-only diagnostics, or catalog plus temporary scenarios composed from safe primitives?

User decision: **B - official catalog plus safe ad-hoc scenarios; useful experiments may be promoted**.

## Decision 09 - Parameter experiments

Question: Read-only Test Lab, or isolated parameter overrides and automated sweeps with no permanent configuration writeback?

User decision: **B - run-local overrides and sweeps**.

## Decision 10 - Real session ingestion

Question: Let every agent reread raw `trace.jsonl`, or normalize a real session into a first-class `DiagnosticBundle`?

User decision: **B - DiagnosticBundle is first-class**.

## Decision 11 - Physical human participation

Question: Automate hardware tests only, or support `hardware:guided` scenarios that explicitly ask the user to remain silent, interrupt, or say a phrase?

User decision: **B - support guided human hardware diagnostics**.

## Decision 12 - Official diagnostic format

Question: Python-only diagnostic modules, or declarative manifest plus specialized code per profile when needed?

User decision: **B - hybrid manifest plus implementation**.

## Decision 13 - Execution process boundary

Question: Run diagnostics inside Control Center, or supervise isolated worker processes per `TestRun`?

User decision: **B - supervisor plus isolated worker**.

## Decision 14 - Cost and resource permissions

Question: Let agents run anything immediately, or classify runs by provider/device/human requirements and enforce mechanical permission/budget gates?

User decision: **B - explicit cost/capability gates**.

## Shared understanding reached

The user confirmed the grill was complete and architecture was sufficiently defined for implementation planning. The Test Lab should be a selective diagnostic platform, not a blanket test suite: a tool-rich deterministic backend usable equally by humans and agents, with progressive realism from cheap virtual experiments to real provider/hardware tests only when evidence requires them.
