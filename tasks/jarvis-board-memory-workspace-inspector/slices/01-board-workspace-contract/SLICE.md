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

## Slice 00 contract (agent 0, 2026-10-02)

Binding over the generic sections above; source: `docs/06-resolved-architecture.md`.

- Pure domain only: `BoardKind` enum + `board_kind` on `Board` (default `empty`, backward decoding of payloads without it, round-trip, PATCH-able through the existing update path; never touches `interaction_mode`).
- Domain value types for Board memory: `BoardMemoryPath` (relative POSIX, validated: no absolute, no drive letter, no `..`, no empty/`.` segments, no backslash, no NUL/control chars, <= 240 chars, Windows-reserved names refused) and the stable error codes of 06-resolved-architecture R4 (`memory_path_invalid`, ...).
- Workspace locator function contract (`boards/<board_id>/memory`, derived from a validated `board_id` only) — the I/O lives in S02.
- New `ActivityKind` values listed in R2.
- `docs/boards.md`: fix stale line 19 (Core start resumes the Session), add the Board memory / board_kind / non-activating inspection sections and the Board-memory vs SessionContext ownership table (R1).
- Not in scope: SQLite, filesystem, routes, MCP, UI. No migration.
