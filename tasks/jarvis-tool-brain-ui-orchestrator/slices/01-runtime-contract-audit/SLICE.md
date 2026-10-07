# Slice 01 — Runtime Contract Audit and Canonical Boundaries

## Goal

Recover and document the exact live contracts Tool Brain must integrate with before any new runtime abstraction is implemented.

## Context

Durable task evidence points to scene APIs, Board runtime, MCP catalog metadata, conversation event/timeline infrastructure and a multi-stage voice/speech pipeline. Their current file names and semantics must be recovered from the repository.

## Canonical Concepts

Scene object, Board, speech response/chunk, conversation event, MCP/tool metadata, user-visible browser/window surface.

## Scope

### In Scope

- Current UI/scene tool inventory and ownership.
- Board switch/create/list semantics and authority rules.
- Speech generation/playback/chunk/progress events and interruption semantics.
- Canonical conversation-event store + live timeline data path.
- MCP catalog/tool metadata/introspection path.
- Existing browser/window/process UI-control capabilities.
- Current stable IDs/revisions available for selectable objects.
- Contract gap report and canonical naming decisions.

### Out of Scope

- Tool Brain model/runtime implementation.
- New UI actions except minimal test probes needed to understand existing contracts.

## Dependencies

- `00-project-manager`

## Implementation Steps

1. Trace each relevant source-of-truth from domain/service to UI/MCP facade.
2. Build an inventory of existing UI mutators/readers and identify duplicates.
3. Map event/correlation IDs between User, Brain, Mouth/Reflex and timeline.
4. Determine the exact representation of generated response segments and playback progress.
5. Determine canonical Board/scene/browser object IDs and revision/version semantics.
6. Identify gaps that later Slices must fill without duplicating existing abstractions.
7. Write/update canonical repository documentation for the recovered contracts.

## Files Likely Touched

Repository docs and contract tests discovered during Slice 00. Durable evidence suggests paths near `jarvis/runtime/display_mcp.py`, `jarvis/domain/scene.py`, `jarvis/runtime/mcp_catalog.py`, `mcp_tool_meta.py`, Board/session runtime, voice/Mouth runtime, and conversation timeline code; use actual live paths.

## Architecture Constraints

Repository ownership is authoritative. Prefer adapting one canonical API over wrapping multiple diverging UI implementations.

## Automated Validation

- Contract inventory maps every Tool Brain-relevant mutation to one canonical owner.
- Event/speech correlation can be demonstrated in tests or a trace fixture.
- No unresolved duplicate source of truth remains hidden.

## Acceptance Criteria

- Later Slices can name exact canonical APIs/events/IDs instead of guesses.
- Cross-task dependencies are explicit.
- Any blocking ambiguity is escalated rather than papered over.

## Documentation Updates

Promote recovered canonical terms/contracts to at least Level 2.

## Handoff Notes

Use `/caveman` and `/coding-guideline` for any code/test probes.
