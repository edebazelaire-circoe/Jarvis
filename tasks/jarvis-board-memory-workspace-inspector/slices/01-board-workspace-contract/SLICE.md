# Slice 01 — Canonical Board workspace memory contract

## Goal
Define the pure domain contract for Board memory/workspace identity, optional Board kind metadata, and safe relationships to Sessions/SessionContexts/artifacts without implementing persistence or UI.

## Context
Current Board is already a durable context boundary with summary and refs, but it has no free-form durable memory workspace. The prerequisite task adds free-form SessionContext workspaces; this Slice must keep the two concepts distinct.

## Canonical Concepts
Board, JarvisSession, SessionContext, Artifact, ArtifactRelation.

## Scope
### In Scope
- Define Board workspace locator/identity and ownership.
- Define `BoardKind` (`empty`, `meeting`, `presentation`) if absent.
- Define explicit non-activating historical inspection semantics.
- Define Board <-> active SessionContext relationship/hydration contract at the domain/service boundary.
- Define stable errors for invalid Board/path/operation targets.
- Define what is management metadata vs free-form memory.
- Define artifact association/index semantics without duplicating artifacts.

### Out of Scope
- Filesystem I/O.
- UI.
- MCP registration.
- Meeting/presentation live behavior or phase transitions.

## Dependencies
Slice 00.

## Implementation Steps
1. Reuse existing Board IDs and strict payload conventions.
2. Add only minimal structured fields needed by product behavior.
3. Specify path-independent workspace references; never accept arbitrary absolute paths from clients.
4. Specify non-activating read operations as pure with respect to foreground/speech authority.
5. Specify backward decoding/migration behavior.

## Files Likely Touched
`jarvis/domain/workspace_board.py` or a canonical successor; SessionContext/artifact domain modules if the prerequisite split them; domain unit tests; canonical docs.

## Architecture Constraints
- Board memory is not SessionContext.
- `board_kind` does not switch interaction mode.
- No rigid internal memory schema.
- Historical inspection never activates a Board.

## Automated Validation
`qa-verification` + `code-review`. Pure contract/unit tests for payloads, enums, errors and side-effect invariants.

## Acceptance Criteria
A fresh implementer can tell exactly what a Board owns, what a SessionContext owns, how they relate, and which operations are guaranteed not to change foreground state.

## Documentation Updates
Update `docs/boards.md` and prerequisite Session/Context docs as necessary to establish canonical terminology.

## Handoff Notes
Do not preserve a legacy field merely because it exists if the current prerequisite implementation superseded it; reconcile deliberately.
