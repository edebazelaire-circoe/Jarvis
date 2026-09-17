# 02 - Architecture

## Target package

Prefer a distinct `jarvis/testlab/` subsystem unless Slice 00 finds an established canonical namespace that should own it. Keep it separate from generic logging diagnostics.

## Core domain

- `DiagnosticSpec`: stable id, title, domain, supported profiles, parameters, permissions, metrics, score contract.
- `ProfileSpec`: `virtual`, `audio`, `live`, `hardware:auto`, `hardware:guided` plus declared resources/cost.
- `Scenario`: safe declarative sequence of Test Lab primitives; no arbitrary code execution.
- `TestRun`: persistent execution identity, code/config snapshot, profile, parameters, status, assertions, metrics, score, artifact references.
- `DiagnosticBundle`: normalized evidence from a real Jarvis session.
- `RunSupervisor`: lifecycle, resource reservation, timeout/cancel/crash handling.
- `ArtifactStore`: structured run outputs and retention policy.
- `Registry/Catalog`: introspectable official diagnostics and profiles.

## Adapters

- Direct Python/native API for Jarvis and internal agents.
- CLI for coding/debug agents and operators.
- HTTP endpoints for Control Center.
- Optional MCP facade later; not required for the first implementation.

## Execution profiles

A single diagnostic can provide specialized implementations for multiple profiles. Common identity/metrics remain stable while realism and resource use increase progressively.

## Storage

Test Lab run storage is separate from the global `RuntimeJournal`, but references/join keys should connect TestRuns to conversation/session traces. Raw audio retention must be bounded and opt-in/profile-driven.

## Security and permissions

Profiles declare provider/device/human needs and estimated cost. The runner enforces configured limits mechanically. Ad-hoc scenarios are constrained to registered primitives.
