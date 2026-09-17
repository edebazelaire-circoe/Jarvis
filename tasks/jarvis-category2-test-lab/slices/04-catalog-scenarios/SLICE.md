# Slice 04 — Diagnostic catalog, manifests, and safe ad-hoc scenarios

## Goal
Implement introspectable official diagnostic manifests plus safe ad-hoc scenario composition from registered primitives.

## Context
This task was planned against `main@c33207281a5b6a10a6630b8914f19855ea096473`. Slice 00 and the pre-dispatch freshness check are authoritative for live file locations and parallel changes.

## Canonical Concepts
- Category 2 Test Lab
- DiagnosticSpec / ProfileSpec / Scenario / TestRun
- DiagnosticBundle
- Existing RuntimeJournal, speech delivery telemetry, async conversation harness, and Control Center contracts where relevant

## Scope
### In Scope
Create registry/manifest loader and schema validation. Support per-profile implementation declarations. Define a bounded scenario DSL/primitives such as user speech, wait, interrupt, inject audio, parameter override, expected event/metric/assertion. Explicitly reject arbitrary Python/shell/code execution. Add explicit promotion path from ad-hoc scenario to versioned official diagnostic.

### Out of Scope
- Autonomous LLM reasoning inside Test Lab.
- Unrelated product behavior changes.
- MCP as a required dependency.

## Dependencies
`01-testlab-domain-contracts`

## Implementation Steps
Create registry/manifest loader and schema validation. Support per-profile implementation declarations. Define a bounded scenario DSL/primitives such as user speech, wait, interrupt, inject audio, parameter override, expected event/metric/assertion. Explicitly reject arbitrary Python/shell/code execution. Add explicit promotion path from ad-hoc scenario to versioned official diagnostic.

## Files Likely Touched
Resolve against the live repository during the freshness check. Likely areas include `jarvis/testlab/` (new), `jarvis/runtime/`, `jarvis/audio/`, `tests/integration/`, `tests/unit/`, and Control Center assets/routes as appropriate.

## Architecture Constraints
- Test Lab remains deterministic and contains no embedded debugging intelligence.
- Do not persist hidden chain-of-thought.
- Do not make Category 2 live/hardware diagnostics part of every normal CI run.
- Use run-local overrides only; never mutate permanent Jarvis settings automatically.

## Automated Validation
- Add narrow unit/contract/integration coverage for this Slice.
- Run repository baseline/release verification selected by Slice 00 where reasonable.
- Prove failure paths, cancellation/cleanup, and serialization compatibility relevant to this Slice.

## Acceptance Criteria
- Slice behavior is covered by automated tests.
- Public contracts are documented/versioned where introduced.
- No regression in existing deterministic conversation/voice tests.
- Runtime/user-visible behavior has concrete evidence when applicable.

## Documentation Updates
Update canonical repository documentation for every new public Test Lab concept or contract introduced by this Slice.

## Handoff Notes

Mandatory QA doctrine:
- Every implemented Slice gets `qa-verification`.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts/tools/routing/modules/runtime add `agent-trace-analysis` with real trace evidence.
- Regressions caused by the Slice are blocking.
- Human validation never substitutes for maximum reasonable machine QA.

Coding-agent requirements: invoke `/caveman` and `/coding-guideline` before implementation.
