# Slice 00 — READY (2026-10-30)

Baseline: origin/main c0858a8000e2ca23b57231edb8f46c643080ad07 after git fetch. Main checkout remains untouched. Dedicated integration worktree C:/Projects/jarvis/mov; branch task/jarvis-mouse-organization-viewer.

## Lifecycle fallback
docs/workflows/AGENT_TASK_LIFECYCLE.md does not exist. Per handle-task, no search for it: project memory C:/Users/Clarice/.claude/projects/C--Projects-jarvis-jarvis/memory/MEMORY.md supplies main (no dev), to-do 1pbNoTQ_nZKv3NVIe2ok-J6kplfnpmjmm, current 1BG9J5tWTuNfExK86YqH43QjMTPbOhB3D, done 16yBLZRVOEbfDAN_CRh5722bkN46IUmo7. Remote origin is the supplied Drive folder, not a ZIP. Folder moved to current and parent verified through connected Google Drive. Old memory's inability-to-move note is obsolete: current connector supports it and invoked handle-task authorizes this move. Human acceptance remains required before done, local deletion or main merge.

## Independent discovery, then reconciliation
Audit started from scene input, multi-object geometry and public execution details before reading docs/07-current-reuse-map.md. Concordant with map; current baseline exactly matches planning baseline.
- Level 3 canonical selection: docs/scene-selection-batch.md, domain/scene_selection.py, scene_batch.py. Explicit selection errors refuse the whole command. translate_selection handles common delta only; SelectionChanges explicitly excludes arbitrary geometry. Add one bounded arbitrary-target operation reusing reducer planners, authority, patch and batch report.
- Level 3 manipulation: runtime/control_center_scene_interact.js resizeBySides/manipulateBox shared by Bare Hands. Mouse uses resizeBox through hold pointerUpdate; .sc-grip recognizes bottom-right only. Extend shared hold descriptor instead of new engine.
- Selection in runtime/control_center_scene_page.js: anchorSelection preserves group during drag/focus, but onContextMenu uses select(id) and collapses it. Keyboard menu calls openObjectMenu; Enter/double-click viewer absent. One owner S02 then S05.
- Generic content: JarvisPrefabHost exclusively owns iframe.srcdoc, sandbox and lifecycle; scene prefab foundation is already implemented in this HEAD. Viewer consumes host/providers; never writes iframe.srcdoc itself. workspace_rail_model supplies validated artifact metadata and /api/artifacts/{id}/payload. Reuse existing document/prefab providers and typed fallbacks.
- Fullscreen: domain/surface_fullscreen.py plus runtime/control_center_fullscreen.js is browser Fullscreen API authority. Viewer is independent transient in-app overlay, never changes its state.
- Work State domain has bounded public fields, progress_fraction, canonical started_at/ended_at, explicit source/external_id/work_id and parent identity. No published future-step contract found. Show no published plan and actual children only.
- Mission History runtime/mission_view.py reads /api/missions/work/{source}/{external_id} and /api/missions/{id}; objective/instance/role remain historical, never status authority. Existing mission cache/role identity can be reused.
- IMPORTANT CORRECTION: protocol/server.py cancel_work explicitly refuses non-job work (not_cancellable). /api/jobs/cancel relay is canonical (registered in control_center.py:1699). Stop is enabled only for cancellable Core jobs, with truthful disabled explanation for CLI child agents; do not invent individual sub-agent stop.
- Ask: unified chat is implemented; JarvisChat.open exists, but no public prefill method or direct agent-question channel. S05 may minimally extend canonical chat API to prefill a target-identified draft; no auto-send and no new bus.

## Overlap and ownership
Drive queues enumerated by stable IDs. current contains prefab foundation, presentation studio, unified chat, memory intelligence and this feature; to-do contains presentation edition v1.2 and two settings/memory tasks. Local TODOs: prefab implemented awaiting Human; chat implemented awaiting closeout; presentation studio partly unfinished but browser-fullscreen and provider infrastructure already present. Existing worktrees pev1/pev12/rui are separate; none owns this worktree. Avoid modifying presentation runtime/variant explorer and prefab engine.
S01 owns Python scene domain/wire/relay + canonical batch doc. S02 owns scene_interact.js and scene_page.js input/CSS. S03 owns new viewer modules/tests/doc only (host insertion deferred S05). S04 owns new public projection module/tests/doc; prefer bounded composition of existing reads to avoid control_center.py contention. S05 owns final scene-page wiring, host insertion, organization planner, undo, chat prefill API; begins only after S02. S06 final convergence.

## Routing and execution
Feature retained as explicit user choice and task metadata. No workspace task-type registry or specialized Work routing tools exposed in this Codex session; cannot independently enumerate external vocabulary. Approved platform fallback is native collaboration sub-agents, role-specific prompts and inherited configured model. No model override. Dedicated short worktree per writer; at most TWO concurrent children (three agents total), tests foreground in small batches to respect machine memory. Initial 01/02/03/04 are independent by file ownership; resource-bound scheduling starts 01 and 02, then 03/04 as slots free.

## QA tiers
00 docs (PM audit); 01 critical (atomic persistence, authority, stale compares; independent adversarial QA/code review, at most 10 foreground mutations); 02 ui; 03 ui; 04 glue (public read composition; privacy/identity/error tests); 05 ui; 06 ui + critical integration checks. Every code Slice has qa-verification/code-review and appropriate runtime evidence, independent review. No full suite until S06 per handoff. New agent projection alone changes no model or prompt; agent-trace-analysis and real model testing become mandatory if runtime/prompt/provider publication paths change. Final S06 exercises a real running/terminal agent when available, truthful unavailable work, all layouts, keyboard, actual pointer resizing and regression neighbors. Sandboxes only: own ports/data; never start/stop/restart user's live Jarvis.

No product decision remains unresolved. No implementation dispatched before this READY.


