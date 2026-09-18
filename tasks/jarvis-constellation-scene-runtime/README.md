# JARVIS - Persistent Constellation Scene Runtime & Brain Display Tools

## Purpose

Build the first production-capable version of JARVIS's persistent 2D constellation display: a scene owned by the JARVIS runtime, rendered by the Control Center browser, manipulated by the main brain through an MCP-style display tool surface, and seeded immediately by mandatory runtime events for sub-agent/process lifecycle and errors.

This handoff comes from the 2026-09-16 design/grilling session plus a compatibility review of `edebazelaire-circoe/Jarvis` main at commit `7ed67bb09f4f9e1d63df793a23777904f6c63d13`.

The central product rule is:

> Runtime guarantees the factual execution constellation. The main brain enriches and composes meaning. The browser/body renders and resolves physical constraints, but does not invent semantic importance.

## Project identity and destination

- Project: **JARVIS** (`project_id=jarvis`)
- Repository: `https://github.com/edebazelaire-circoe/Jarvis`
- Reviewed main SHA: `7ed67bb09f4f9e1d63df793a23777904f6c63d13`
- Queue: `Jarvis/task/to-do/jarvis-constellation-scene-runtime/`
- Priority: P1
- Domain: runtime
- Default receiving role: developer

## Locked scope

The V1 includes a durable scene model, persistent scene store, runtime-driven sub-agent stars and execution/error signals, strict-2D layered rendering, an AutoResolver that may mitigate collisions without flattening layers, a brain-accessible display MCP/tool surface, semantic artifact enrichment, user interactions, structured scene inspection, optional screenshots, restart reconciliation, and rollout/tests.

The V1 explicitly does **not** add a dedicated display AI. The main brain remains the semantic display orchestrator. Runtime events bypass the brain only for a narrow, systematic set of execution facts. Archiving is a user-side action and is deliberately absent from the brain display tool set in V1.

## How the Project Manager starts

1. Open `slices/TODO.md`.
2. Execute Slice `00-project-manager` personally; do not delegate it.
3. Perform the blind repository/context audit required by Slice 00 before relying on this handoff's conclusions.
4. Resolve the Workspace Task Type vocabulary. Every implementation Slice is deliberately blocked on `task_type_unresolved` until an approved Task Type is assigned.
5. Reach `READY` before dispatching implementation work.
6. Run a targeted freshness check immediately before every Slice dispatch.

## QA doctrine

Every implemented Slice receives a baseline `qa-verification` pass. Code changes also receive `code-review`. User-visible or runtime behavior also receives `runtime-validation`. Changes to agent prompts, tools, routing, modules, MCP integration, or agent runtime also require `agent-trace-analysis` with real trace evidence. QA agents return evidence and findings; the Project Manager decides approve, rework, continue, new Slice, Issue, or escalation.

A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation never substitutes for QA. Before any Human check, escalate machine validation to the maximum reasonable level and clear everything a machine could have caught.

## Required implementation skills

All coding Slices require `/caveman` and `/coding-guideline`. Frontend/browser Slices additionally require `/impeccable` and should route to a Claude agent when the host supports that routing rule.

## Source hierarchy

When sources disagree, use this precedence:

1. explicit decisions recorded in `docs/01-decision-log.md` from the 2026-09-16 user session;
2. current repository contracts and code after the Project Manager freshness audit;
3. the uploaded visual-direction document, with the user corrections captured here;
4. provisional architecture recommendations in this handoff.

The uploaded visual direction remains the aesthetic North Star, but its earlier suggestion that completed work may fade/disappear is overridden: completed work remains in the active scene until the user chooses its disposition.
