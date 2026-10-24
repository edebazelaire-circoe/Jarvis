# Refonte UI Settings — Jarvis

## Project

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Default branch: `main`
- Repository head observed during task creation: `be80ab9baed0ea3819af5e916b102f3835663ce3` (2026-10-24)
- Local handoff: `tasks/refonte-ui-settings/`
- Canonical Drive destination: `Jarvis/task/to-do/refonte-ui-settings/`

## Mission

Perform a **real visual refactor of the Settings surfaces** using the five user-provided mockups as concrete visual references. This is not a generic cleanup and not a backend redesign. Each supplied page/view has its own implementation Slice with explicit layout, component, interaction, responsive, accessibility, visual-regression and Human-validation requirements.

The task exists specifically because earlier Settings handoffs did not make the visual work concrete enough and did not reliably include the approved reference images in the implementation package.

## Non-negotiable visual references

The task ships the five uploaded images in `references/ui/`:

1. `01-personnalisation.png` — Personalisation page.
2. `02-architecture-agents-subagents.png` — Architecture & Agents / Sous-agents view.
3. `03-architecture-agents-architecture.png` — Architecture & Agents / Architecture graph view + floating brain configuration panel.
4. `04-memory-settings.png` — Mémoire & connaissances / Mémoire view.
5. `05-memory-center.png` — Mémoire & connaissances / Memory Center view.

Every UI Slice links directly to its reference and must produce screenshot evidence at the corresponding reference aspect ratio before completion.

## Existing functional contracts remain authoritative

This task is primarily frontend/visual. Do **not** invent a second runtime model to make screenshots look right.

Coordinate with and preserve the decisions already established by:

- `Jarvis/task/done/jarvis-settings-ui-reorganization/`
- `Jarvis/task/done/jarvis-architecture-agents-settings-editor/`
- `Jarvis/task/to-do/jarvis-memory-knowledge-settings-ui/`

Important examples:

- Architecture & Agents keeps the current canonical role registry; the five roles shown in a mockup are illustrative, not a new role count.
- The canonical Architecture & Agents contract has **no standalone Brains tab**; brain configuration opens contextually from the Architecture graph. The sub-agent mockup's `Brains` tab is a visual artifact, not a requirement to restore that tab.
- Memory uses the current canonical memory/knowledge contracts and server-owned ranges/options. Mockup values/providers/statuses are examples unless the live runtime confirms them.
- Existing Settings navigation, persistence, accessibility and runtime semantics must be preserved unless a Slice explicitly identifies and validates a necessary UI integration change.

## Required execution order

The receiving agent is the **Project Manager/orchestrator**. It executes Slice `00-project-manager` itself.

Main hard chain:

`00 -> 01 -> {02,03,04,05,06} -> 07`

After Slice 01, the five page-specific UI Slices are intentionally parallel-safe where they touch separate modules/components. Slice 07 owns shared integration and final visual acceptance.

## Mandatory frontend discipline

Every coding Slice must load `/caveman` and `/coding-guideline`.

Every frontend Slice must additionally load `/impeccable` and use a Claude Work Agent when the host supports that routing rule.

For each UI Slice:

- inspect the live DOM/CSS/component implementation before editing;
- use the supplied mockup as the visual target;
- reuse live data and existing controllers instead of hard-coded demo values;
- preserve empty/loading/error/disabled states;
- capture before/after screenshots;
- validate at the reference viewport and at least one narrower desktop/tablet width;
- perform keyboard/focus checks for interactive controls;
- attach Human validation only after machine QA is clean.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible/runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime changes add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, create a new Slice, create an Issue, or escalate.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Machine validation must be exhausted first.

## Start here

Open `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md`. No implementation Slice may start until Slice 00 reaches `READY`.
