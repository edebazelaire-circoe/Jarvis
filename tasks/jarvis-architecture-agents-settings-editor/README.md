# Jarvis Architecture & Agents Settings Editor

## Project

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Source branch audited: `main`
- Handoff creation date: `2026-10-23`
- Local handoff: `tasks/jarvis-architecture-agents-settings-editor/`
- Canonical Drive destination: `Jarvis/task/to-do/jarvis-architecture-agents-settings-editor/`
- Related task: `Jarvis/task/to-do/jarvis-settings-ui-reorganization/`
- This handoff **supersedes/refines only Slice 04 (`agents-models-reorganization`)** of that related task. It does not supersede the rest of the Settings reorganization.

## Mission

Implement the new **Architecture & Agents** Settings page as a real configuration surface, not a decorative diagram.

The page has exactly two internal tabs:

1. **Architecture** - a real 2D representation of the running brain architecture and its audio/system connections.
2. **Sous-agents** - global configuration of sub-agent roles, routing candidates, models/harnesses, fallbacks, tools and role behavior.

There is **no `Brains` tab**. Brain-specific settings open in a contextual floating configuration window from the Architecture canvas (right click / context action on a brain).

The central product rule is:

> **The architecture graph decides what can talk to what. A brain decides when it delegates. The global sub-agent configuration decides which specialized agent/model executes a delegated role.**

## Locked product decisions

- The architecture diagram is operational. Enabling/disabling/creating/removing a supported connection changes the real runtime architecture.
- Connections are directional, typed and meaningful; they must identify source, target, channel/purpose and mutability.
- Required/non-removable connections are visibly distinct and cannot be disabled from the UI.
- Editable active, editable disabled and required/locked links are visually distinct.
- The current default diagram must represent the **actual current runtime**, not imagined future brains. The baseline must include audio input/output and the currently real Voice/Core/Tool brain surfaces after Slice 00 re-audits `main`.
- Future brains remain supported by a generic node/port/connection contract; they are not faked into the default graph.
- Brain cards/nodes are draggable for layout. Moving a node changes only saved UI layout, never runtime semantics.
- Right click on a brain opens a contextual action and then a floating/draggable brain configuration panel. A separate full-page Brain settings tab is forbidden.
- Brain configuration owns provider/model, mission/responsibilities, brain-specific instructions, activation where valid, and **delegation tendency**.
- Brain delegation tendency uses a five-level product vocabulary: `never`, `rare/occasional`, `standard`, `proactive`, `exploratory/spread`.
- Brain configuration does **not** decide which exact sub-agent/model handles Code, Research, QA, etc.
- Global sub-agent configuration owns role identity and the ordered harness/model candidates and fallback behavior for each role.
- Reuse the existing canonical seven-role registry on `main`; do not reduce it to the five illustrative roles visible in the UI reference image.
- Personality controls (tone, politeness, formality, response length/verbosity, humor) do not belong on this page.
- The old product-level `Auto` / `Duplique` sub-agent choice is not a target UI concept. Preserve compatibility internally where needed, but replace it with the new delegation + role-routing model.
- Raw CLI command/path, permission/sandbox controls, re-probe/re-detection, compatibility internals and low-level diagnostics stay in Advanced/Diagnostic surfaces.
- The server/runtime remains authoritative for model/provider availability and connection mutability. The browser must not invent a second catalog or a second architecture truth.

## Visual references

The two user-approved images are copied into `references/`:

- `architecture-ui-reference.png` - visual direction for the Architecture tab, semantic 2D graph and floating brain config window.
- `subagents-ui-reference.png` - visual direction for the Sous-agents tab, role rows/cards and routing/policy panels.

They are references, not literal contracts. `docs/07-reference-interpretation.md` records what is locked and what is illustrative only.

## Existing implementation to reuse

The live `main` audit found reusable foundations:

- `jarvis/domain/subagent_roles.py` + `docs/subagent-roles.md`: canonical seven-role registry, identity, capabilities, tools, skills, loadouts, Work Methods and prompt instructions.
- `jarvis/runtime/control_center_subagents_settings.js`: existing role UI data/error/revision behavior.
- `jarvis/domain/routing.py` + `jarvis/runtime/agent_routing.py`: candidate/fallback mechanics and model/harness selection primitives.
- `jarvis/runtime/model_catalog.py`: server-owned model/provider catalog.
- `jarvis/runtime/agent_settings.py`: current agent/CLI/model persistence primitives; technical CLI controls remain Advanced.
- `jarvis/runtime/tool_brain_brief.py` and Tool Brain ownership runtime: current Tool Brain existence/ownership semantics.
- `docs/ARCHITECTURE.md`: Core/Voice process ownership and current runtime boundaries.

See `docs/08-current-reuse-map.md` for keep/move/replace decisions.

## Async execution model

Slice numbers are identifiers and presentation order, **not a serial execution mandate**.

After Slice 00 reaches `READY`, the initial parallel dispatch set is:

- `01-architecture-graph-runtime-contract`
- `02-brain-config-runtime-contract`
- `03-subagent-role-routing-contract`
- `04-architecture-canvas-ui`
- `05-brain-config-popup-ui`
- `06-subagents-tab-ui`

These branches intentionally use fixtures/adapters and separate files so useful work can proceed in parallel. They converge in:

`07-settings-integration-and-legacy-migration` -> `08-final-integration-e2e-qa`

## Start here

The receiving agent is the **Project Manager/orchestrator**. It executes Slice `00-project-manager` itself and never delegates that Slice.

Before any implementation dispatch, Slice 00 must perform an independent blind audit of `main`, inspect the related Settings task, reconcile this handoff with the live repository, resolve valid Workspace Task Types, and return exactly one readiness state:

- `READY`
- `CONTEXT_REWORK_REQUIRED`
- `CONFLICT`
- `HUMAN_DECISION_REQUIRED`

No implementation work is dispatched below `READY`.

When `READY`, dispatch every hard-dependency-ready, parallel-safe Slice, not only the lowest-numbered Slice.

## QA doctrine

- Implementation Slices get lightweight `qa-verification` and targeted evidence, not a routine full unit-test run.
- Code changes add `code-review`.
- User-visible/runtime behavior adds targeted `runtime-validation`.
- Brain/routing/sub-agent runtime changes add `agent-trace-analysis` using real traces where applicable.
- A focused individual test may be run to diagnose a specific defect, but it is not the default Slice-completion gate.
- The complete unit suite runs **once**, only in Slice 08, together with integration/E2E validation. Unit and E2E suites should run concurrently when isolation/resources allow, otherwise in the same final validation phase.
- Regressions introduced by this task are blocking; do not park them as accepted Issues.
- Human validation occurs only after machine validation has been exhausted.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed to this task-creation environment. All implementation Slice metadata therefore uses `task_type: null`. Slice 00 must resolve a valid existing Task Type for every implementation Slice before dispatch and must not invent one.
