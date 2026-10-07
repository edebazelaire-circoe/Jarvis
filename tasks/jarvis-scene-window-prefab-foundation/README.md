# Jarvis Scene Window & Prefab Foundation

## Project

- Project: **Jarvis**
- Canonical handoff slug: `jarvis-scene-window-prefab-foundation`
- Local handoff: `tasks/jarvis-scene-window-prefab-foundation/`
- Drive destination: `Jarvis/task/to-do/jarvis-scene-window-prefab-foundation/`
- Repository expected by existing Jarvis task material: `edebazelaire-circoe/Jarvis`

## Goal

Create the reusable scene-object foundation Jarvis needs before presentation-specific content orchestration: a shared prefab library, large reusable window families, parameterized HTML/CSS/JavaScript objects, structured data inputs, safe runtime instantiation, and agent-facing operations to reuse, fork, create, inspect, and save prefabs.

This task turns the existing "Rework FENETRES" direction and the newer prefab discussion into one implementation boundary:

`Brain / task agent -> Scene contract -> Prefab instance -> HTML/CSS/JS renderer`

Presentation mode is a **consumer** of this foundation, not part of this task.

## Why this is a separate task

The current Jarvis presentation work defines interaction semantics: ambient listening, initiative, silence vs speech, command priority, and presentation behavior. The prefab/window work defines a lower-level reusable rendering and object-authoring substrate. Mixing them would make presentation behavior depend on an unfinished rendering architecture and would make prefab design presentation-specific.

Implement this foundation independently, then integrate it into presentation mode in a follow-up task or explicit amendment to the presentation handoff.

## Locked user intent

- The prefab library is shared and globally maintained; it is not board-specific or user-private.
- Jarvis should prefer reuse: exact/close prefab first, then create from scratch only when needed.
- Jarvis may clone/fork an existing prefab, modify the copy, and optionally save it as a new prefab.
- Base/system prefabs may be modified, but **only after explicit user request**. Ordinary adaptation creates or modifies an instance/variant instead.
- Prefabs are not only windows. Windows are the first major family; lights/stars and later scene objects follow the same reusable-object idea where appropriate.
- A prefab is an actionable HTML/CSS/JavaScript object, not HTML markup alone.
- Prefabs expose variables/inputs so common changes (color, labels, values, options) do not require code edits.
- Prefabs must accept structured payloads such as JSON objects and lists; a checklist is a canonical example.
- Jarvis can populate and adapt a prefab at runtime from data.
- Objects created ad hoc can be retained as new prefabs for later reuse.
- The scene/runtime remains authoritative over placement, lifecycle, visibility, ownership, and cleanup. Generated UI code must not become an unrestricted path to the rest of Jarvis.
- Existing Session / Board / Context semantics are out of scope and must not be redesigned here.
- Presentation mode will later use these prefabs as prepared or on-demand visual material, but its orchestration and meeting behavior are not implemented in this task.

## Source evidence available at handoff creation

- Current project conversation: Rework FENETRES + prefab/library discussion + presentation integration discussion.
- Existing Drive task `Jarvis/task/current/jarvis-presentation-interaction-mode/` confirms that presentation behavior is already a distinct product-level concern and should remain separate from this lower-level rendering foundation.
- The Jarvis GitHub repository was not accessible through the GitHub connector in this creation environment. Slice 00 therefore requires a blind repository audit before implementation and must reconcile the real code with this handoff.

## Start here

The receiving agent is the Project Manager for this handoff. Open `slices/TODO.md`, then execute Slice `00-project-manager` itself before dispatching any implementation Slice.

Slice 00 must perform a blind audit of the current Jarvis repository before reading the handoff's documentation-level conclusions, reconcile drift, and reach `READY` before implementation dispatch.

## Required coding skills

Every coding Slice must load `/caveman` and `/coding-guideline`. Every frontend Slice must additionally load `/impeccable` and use a Claude agent when the host supports that routing rule.

## QA doctrine

- Every implemented Slice gets a baseline `qa-verification` pass.
- Code changes add `code-review`.
- User-visible or runtime behavior adds `runtime-validation`.
- Agent prompts, tools, routing, modules, or agent runtime add `agent-trace-analysis` with real trace evidence.
- QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.
- A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.
- Human validation is never a substitute for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Planning blocker

The current Workspace Task Type vocabulary is not exposed in this task-creation environment. Slice metadata therefore uses `task_type: null`. Slice 00 must resolve valid existing Workspace Task Types before dispatch or obtain an explicit project-level waiver; it must never invent Task Type labels.
