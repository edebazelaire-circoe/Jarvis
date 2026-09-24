# Jarvis — MCP semantic batches and human inspector


## Purpose


This handoff turns the MCP audit into an implementation task. The target is not merely to make every UI action technically reachable from MCP. The target is to make one coherent user intent map to one coherent semantic operation, with clear domain meaning, minimal model-to-tool calls, and no hidden N-command fan-out when the user experiences the action as atomic.


The second deliverable is a human-facing MCP inspector in the Control Center. It must make the actual Jarvis MCP surface understandable without dumping a raw `tools/list` payload into a wall of JSON.


## Project identity


- Project: **Jarvis**
- Repository: `edebazelaire-circoe/Jarvis`
- Source branch inspected: `main`
- Source commit inspected: `ddcdb71e17d7be76236c7dd6ab070af90e8f7d65`
- Freshness check date: 2026-09-24
- Intended Drive destination: `Jarvis/task/to-do/jarvis-mcp-semantic-batch-inspector/`


## Locked product intent


1. A user-level scene intention must be expressible as a single semantic operation where the action is conceptually indivisible.
2. Scene batching must become real Core/domain batching: selection resolution, validation and mutation occur against one snapshot, producing at most one scene revision/patch for the operation.
3. Constellation membership must have one canonical domain meaning shared by MCP, UI and future Bare Hands behavior.
4. Selection itself becomes a domain concept rather than an MCP-only convenience.
5. MCP calls should become semantically denser. Do not replace one generic tool with dozens of setting-specific tools simply to make the inspector look friendly.
6. The inspector must be driven by the same source of truth as the MCP servers, with parity tests preventing documentation/schema drift.
7. Add an **MCP** button to the existing right-side Control Center dock (`ERR / TRC / LAB / CNV / SET / AGT`). It opens a dedicated, clean inspector surface.
8. The inspector defaults to a compact/collapsed view and supports detailed expansion. Parameters show type, required/optional state, defaults and constraints. Results show a readable output schema.
9. The inspector groups capabilities into human categories, at minimum **General**, **Stars / Scène**, **Settings**, and **Bare Hands**. Optional/external MCPs may have a separate category when Jarvis can describe them reliably.
10. The inspector is an inspection/documentation surface in this task, not an arbitrary destructive tool runner.
11. Adding the inspector must not increase the model's MCP context cost by advertising redundant meta-tools. Protocol/catalog helpers such as `list_tools`/`get_tool` belong in the Control Center catalog layer unless there is a separate, justified model use case.
12. Final advertised Jarvis-native tool count must not grow mechanically. Semantic tools should replace redundant granular tools where possible; the scene surface must not exceed its current 13 advertised tools without an explicit, documented reason.


## Current evidence from the audit


- `jarvis/runtime/display_mcp.py` exposes 13 scene tools. `scene_update_many` resolves a selection once but sends one Core command per object, reports `atomicity: best_effort`, has a 15 s bulk deadline and rejects more than 32 selected objects.
- `jarvis/domain/scene.py` already proves the domain can do a true batch: `archive_many` produces one revision, but its eligibility is intentionally narrower than general scene manipulation.
- MCP `connected` means a graph walk over scene relations. UI `constellationOf(...)` additionally creates virtual signal-owner edges using `signalOwners(...)`, so the same word can currently denote different sets.
- The scene UI supports multi-selection and drags selected objects together visually, then commits geometry object-by-object. Bare Hands currently documents an intentional single-frame limitation.
- FastMCP input metadata is reasonably rich through `Annotated`/`Field`, but many mutating tools return `dict[str, Any]`, so result schemas are not a strong human contract.
- `jarvis-console` has a good generic settings design (`settings_describe/get/set`). Preserve that density instead of generating one tool for every setting.
- The Control Center's existing tool dock is the correct home for the requested `MCP` entry.


## How the Project Manager starts


Open `slices/TODO.md`, then execute **Slice 00 — Project Manager** yourself. Do not dispatch implementation before Slice 00 reaches `READY`.


Slice 00 must perform an independent blind audit first, then reconcile it with this handoff. This task deliberately contains architecture conclusions from an audit; the blind audit is required to catch repository drift and bad assumptions before code moves.


## QA and Human validation doctrine


Every implemented Slice gets `qa-verification`. Code changes also get `code-review`. User-visible or runtime behavior also gets `runtime-validation`. Any Slice touching MCP tools, tool descriptions, tool exposure, prompts, routing or agent runtime also gets `agent-trace-analysis` with real trace evidence. QA agents return evidence and findings; the Project Manager decides approve, rework, continue, add a Slice, file an Issue, or escalate.


A regression caused by the current Slice is blocking and cannot be parked in `Issues/`. Human validation never substitutes for machine QA; run the strongest reasonable machine checks before requesting a Human check.


All coding Slices must require `/caveman` and `/coding-guideline`. Frontend Slices must additionally require `/impeccable` and a Claude Work Agent when the host supports that routing rule.


## Planning blocker carried into Slice 00


The current Workspace Task Type vocabulary is not exposed to this task creator. No Task Type is invented. Slice 00 must resolve valid existing Task Types before dispatch, or obtain an explicit host-supported waiver.