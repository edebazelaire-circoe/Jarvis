# Jarvis Settings + Model Catalog UX

## Project

- Project: Jarvis
- Repository: `edebazelaire-circoe/Jarvis`
- Source snapshot inspected during handoff creation: `main` at `c33207281a5b6a10a6630b8914f19855ea096473` on 2026-09-12.
- Destination: `Jarvis/task/to-do/jarvis-settings-model-catalog-ux/`
- This handoff is based on the repository after the routing/self-development work landed and after the latest voice-surface change observed on 2026-09-12.

## Goal

Replace the current routing-centric/dense settings experience with technical-first Agent/CLI configuration, rich personalization, reusable model/sub-agent comparison catalogs, and categorized voice settings while preserving backend routing correctness.

## Locked user intent

- Remove the user-facing “Aiguillage” section; keep routing implementation internally if still required by the runtime.
- Move sub-agent delegation configuration into the agent/CLI configuration area, with technical options shown before personality/behavior options.
- Expose an Auto vs Dupliqué sub-agent mode switch, bound to the live runtime semantics rather than inventing a second routing engine.
- Provide extensive personalization, including verbosity and politeness/formality, while keeping technical controls visually prioritized.
- Reorganize the overloaded voice-model settings page into top sub-tabs/categories.
- Provide interactive catalog/comparison tables for sub-agents/models and voice models, with sorting, filtering, tags/descriptions, prices/capabilities when trustworthy, and clear availability state.
- Distinguish loaded/usable models from models that are discoverable/relevant but not currently configured, and provide an explicit “request/add model” workflow rather than pretending unavailable models are usable.
- Reuse shared catalog/table components across text/sub-agent and voice model surfaces.

## Start here

The receiving agent is the Project Manager for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself before dispatching any implementation Slice. Slice 00 must perform a blind live-repository audit and reconcile this handoff with the latest code before implementation.

## Cross-handoff coordination

The Voice sub-tabs must consume the supported turn-taking/settings contract produced by `jarvis-voice-turn-arbitration`. This handoff may implement unrelated Agent/CLI/catalog work in parallel, but must freshness-check voice settings immediately before Slice 06.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline` before implementation. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed to this task-creation environment. Implementation Slice metadata therefore uses `task_type: null`. Slice 00 must resolve each Slice to a valid existing Workspace Task Type before dispatch.
