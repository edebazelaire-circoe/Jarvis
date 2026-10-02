# Slice 01 - Canonical Session + SessionContext contract

## Goal

Define the pure domain contract that changes JarvisSession from process-lifetime semantics to explicit-user-lifetime semantics and adds SessionContext with one-active-context invariants. No persistence, UI or capture adapters in this Slice.

## Context

On the inspected baseline, `JarvisSession` lives in `jarvis/domain/workspace_board.py`, includes `active_board_id`/`visited_board_ids`, and `SessionEndReason` includes `CORE_RESTART`. `SessionManager.start()` closes a stale open Session on Core startup. Existing Board/binding code is mature and must not be casually dismantled.

## Scope

### In scope

- Amend/extend Session lifecycle so runtime restart is resumable rather than a close reason for new behavior.
- Define `SessionContext` identity, active/dormant lifecycle, timestamps, validation and stable errors.
- Define atomic context transitions: create, activate/reactivate, dormant previous active.
- Define explicit new-session close semantics.
- Define compatibility behavior for historical `core_restart` Sessions and current Board-required fields without making Context Board-scoped.
- Define canonical payload codecs and bounded metadata.
- Unit-test pure invariants, concurrency-independent transitions and malformed payloads.

### Out of scope

SQLite migrations, filesystem Context folders, agent prompt hydration, capture/artifact behavior, Board removal.

## Architecture constraints

- New Context identity is keyed by `jarvis_session_id`, never `board_id`.
- Exactly one active Context per open Session.
- Dormant Context does not become mutable merely because another agent holds its path.
- Do not reinterpret historical rows to erase the fact that old Core restarts closed Sessions.
- Avoid a second competing Session type.

## Files likely touched

`jarvis/domain/workspace_board.py` or a newly separated session/context domain module, ports/contracts, domain unit tests, canonical docs. The PM must choose the owner after the fresh audit rather than preserving a file name for nostalgia.

## Automated validation

Baseline `qa-verification` + `code-review`. Run Session/Board contract tests and new SessionContext unit tests. No Human validation.

## Acceptance criteria

Domain contract represents the locked lifecycle unambiguously; old Board contracts remain coherent; one-active-Context is enforced by transitions; restart is not specified as a user-session close; stable payload/error behavior is tested.
