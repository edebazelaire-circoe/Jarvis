# Jarvis Settings UI Reorganization

## Project

- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Source audited for this rebuilt handoff: branch `main`, commit `20292e5c292dc8ab9a012ccf00ecb82b5c7f820e`
- Local handoff: `tasks/jarvis-settings-ui-reorganization/`
- Canonical Drive destination: `Jarvis/task/to-do/jarvis-settings-ui-reorganization/`

## Goal

Rebuild the Settings information architecture and visual shell so Jarvis exposes a small number of understandable, goal-oriented categories instead of a growing set of implementation-shaped tabs.

The task is intentionally **not** a backend settings rewrite. Existing validators, persistence keys, runtime semantics, server-described schemas, credentials rules, model/provider catalogs, localStorage appearance settings, and compatibility projections remain authoritative unless a Slice explicitly proves that a change is required.

## Current problem

On the audited `main`, the Settings surface is assembled from the base `TABS` list plus injected modules. The effective top-level navigation currently includes ten destinations:

1. `Voix`
2. `Mot d'eveil`
3. `Prompts`
4. `Agent / CLI`
5. `API Keys`
6. `Raccourcis`
7. `Memoire`
8. `Sous-agents`
9. `Apparence`
10. `Experimental`

Several of those pages mix preferences, developer tools, diagnostics, read-only state, compatibility controls, and operational repair actions. The UI also uses the same dense HUD language for ordinary preferences and low-level technical information.

## Locked target navigation

The Settings surface has exactly **six top-level menus**:

1. **Voix & audio**
2. **Agents & modeles**
3. **Memoire & connaissances**
4. **Interface & interactions**
5. **Connexions**
6. **Avance & diagnostic**

The current ten destinations stop being the primary navigation model. Their capabilities are redistributed according to `docs/07-target-settings-map.md`.

## Locked product principles

- Organize settings by **what the user is trying to change**, not by the module that implemented the setting.
- A normal Settings page must not look like a runtime inspector.
- Read-only runtime state, raw diagnostics, repair controls, benchmarks, capture/record tooling, compatibility toggles, and developer workbenches belong under **Avance & diagnostic** unless they are essential to a normal user decision.
- Do not delete backend capability merely because it leaves the normal Settings surface.
- A writable setting has one canonical editable home. Cross-links are allowed; duplicate writable controls are not.
- Server-owned option/range metadata remains authoritative. Do not fork backend vocabularies into browser-only copies.
- Preserve supported legacy programmatic tab IDs through explicit aliases during migration.
- New modules must register sections into the Settings information architecture rather than append another top-level tab.

## Visual direction

The old centered, framed, dense modal is replaced by the Settings direction established in the project conversation:

- dark full-screen or near-full-screen Settings surface over the blurred Jarvis background;
- no large boxed modal frame floating in the middle of the page;
- more space, clearer hierarchy, and stronger category identity;
- category entry points that read like application/settings destinations rather than a narrow text-only list;
- Jarvis dark/cyan visual language retained without applying dense monospace/HUD styling to every ordinary control;
- technical/monospace styling reserved for advanced diagnostics and identifiers;
- close/escape behavior remains predictable and accessible.

`references/current-settings-ui.png` is a **before-state reference**, not a target mockup.

## Start here

The receiving agent is the **Project Manager** for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself before dispatching implementation work.

Slice 00 must first perform a blind audit of the live repository and current Settings surface, reconcile that audit with this handoff, and return one of: `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`. No implementation Slice is dispatched below `READY`.

## Required coding and frontend skills

- Every coding Slice must load `/caveman` and `/coding-guideline`.
- Every frontend Slice must additionally load `/impeccable`.
- Frontend implementation/review must use a Claude Work Agent where the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, create a new Slice, create an Issue, or escalate.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed to this task-creation environment. Implementation Slice metadata therefore uses `task_type: null`. Slice 00 must resolve every implementation Slice to a valid existing Workspace Task Type before dispatch. It must not invent one.
