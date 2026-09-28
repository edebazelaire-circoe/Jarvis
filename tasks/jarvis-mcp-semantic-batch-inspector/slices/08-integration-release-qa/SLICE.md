# Slice 08 — Integration, migration and release QA


## Goal
Run full seam validation: actual tools/list versus inspector, representative multi-object scene mutations proving one MCP call -> one Core command -> one revision, visual coherence, context/tool-count budget, alias cleanup, runtime traces, docs and release QA.


## Context
This Slice closes the MCP semantic-batch/inspector handoff. Validate seams between domain, Core, MCP runtime and Control Center rather than trusting isolated unit tests.


## Canonical Concepts
SceneSelection, canonical constellation, atomic scene batch, canonical MCP catalog, human inspector.


## Scope
### In Scope
Run full seam validation: actual tools/list versus inspector, representative multi-object scene mutations proving one MCP call -> one Core command -> one revision, visual coherence, context/tool-count budget, alias cleanup, runtime traces, docs and release QA.


### Out of Scope
New Bare Hands gesture bindings; unrelated scene UX redesign.


## Dependencies
02, 03, 04, 05, 06, 07


## Implementation Steps
1. Run targeted and broad regression suites.
2. Start representative Jarvis configurations with scene/Bare Hands enabled and disabled.
3. Capture actual MCP advertised tools and compare catalog/inspector schema and status.
4. Execute semantic constellation update/translate/archive/pin calls and prove one MCP mutation call -> one Core command -> one revision.
5. Verify coherent scene rendering.
6. Measure final tool count/context surface and remove accidental aliases/meta-tools.
7. Run code review, runtime validation, agent trace analysis and frontend visual QA.
8. Finalize canonical docs and durable execution notes.


## Files Likely Touched
Tests, docs, catalog/prompts and small migration cleanup files.


## Architecture Constraints
Require `/caveman` and `/coding-guideline`; frontend fixes also require `/impeccable` and Claude Work Agent routing when supported.
Do not weaken atomicity or catalog parity to make tests pass.


## Automated Validation
`qa-verification`, `code-review`, `runtime-validation`, and `agent-trace-analysis` with real evidence. Regressions introduced by this task block completion.


## Acceptance Criteria
Run full seam validation: actual tools/list versus inspector, representative multi-object scene mutations proving one MCP call -> one Core command -> one revision, visual coherence, context/tool-count budget, alias cleanup, runtime traces, docs and release QA.
Inspector catalog matches actual Jarvis-native MCP exposure and representative semantic scene batches are one MCP mutation call, one Core command and one scene revision.


## Documentation Updates
Finalize MCP tool contract, scene selection/batch contract and historical plan cross-links.


## Handoff Notes
Human end-to-end validation occurs only after machine QA is green.

## Slice 00 refinements
Read `slices/00-project-manager/READINESS.md` §2–§5 before starting: blind-audit touch points, inherited red tests (not yours), and baseline-realignment ownership.
