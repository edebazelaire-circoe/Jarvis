# Slice 07 — Semantic artifacts

## Goal
Let the brain attach grouped, brain-selected artifacts that explain completed work (Decision 5), linked to execution stars and inspectable later.

## Context
Audit facts: sub-agent summaries exist in memory (`AgentTask.summary`, relayed to Core `WorkItem.summary` ≤1000 chars); completion notices reach the brain as unsolicited CLI turns (`claude_local.py:785-830`) and Core `announce_notice`; failures wake the brain via `WorkAttentionPolicy`. No durable artifact storage exists.

## Canonical Concepts
`artifact` scene object with `category` (research, files/diff, tests, api, roadmap/trello, email, document, other — open token list validated for shape, not closed semantics), bounded payload (title, summary, items with label/ref/url), `explains` relation to a star. Grouping is brain judgement; no runtime auto-artifacts. MCP tools: `scene_add_artifact`, `scene_update_artifact` (or extend 06 tools — implementer chooses, PM reviews for minimal surface). Prompt guidance: after completion notice, optionally create one grouped artifact instead of per-event nodes.

## Scope
### In Scope
Domain additions if needed, MCP tools, renderer representation for artifacts (capsule/window detail view), prompt guidance, tests.
### Out of Scope
Automatic artifact generation by runtime; fetching remote content.

## Dependencies
04, 06 (renderer 05 for display).

## Implementation Steps
1. Payload schema + bounds. 2. Tools. 3. Renderer detail view. 4. Prompt. 5. Real run: background task completes → brain adds artifact.

## Files Likely Touched
`jarvis/domain/scene.py`, `jarvis/runtime/display_mcp.py`, `jarvis/runtime/control_center_scene.js`, prompt catalog, tests.

## Architecture Constraints
No node-per-event explosion; payload size bounded; artifacts never auto-archived.

## Automated Validation
Unit + node tests; agent-trace-analysis on a real completion.

## Acceptance Criteria
A completed real task shows a grouped artifact linked to its star that survives reload and remains until user disposition.

## Documentation Updates
Scene model doc; OPERATIONS.md.

## Handoff Notes
Skills: `/caveman`, `/coding-guideline` (+ `/impeccable` for renderer part, Claude agent). QA: qa-verification + code-review + runtime-validation + agent-trace-analysis.
