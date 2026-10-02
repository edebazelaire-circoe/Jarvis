# 01 - Decision log

## D01 - Reuse Board as the durable workspace boundary

Locked. Do not invent a separate Meeting/Presentation container for memory management. Existing Board is the durable workspace/context boundary.

## D02 - Board memory is free-form

Locked. The Board owns a backend-derived workspace root, but files/folders inside are agent-organized and evolvable. No mandatory `decisions.json`, `participants.json`, etc.

## D03 - Management data stays structured

Locked. Board identity, title, kind, lifecycle, timestamps, refs, relationships, paths/locators and artifact indexes stay in typed backend data/SQLite. Large or free-form agent memory stays in files.

## D04 - SessionContext and Board memory are distinct

Locked. SessionContext is current cognitive state; Board memory is durable workspace memory. Activation hydrates/selects relevant Board state without blindly copying the entire Board directory into every prompt.

## D05 - Historical inspection is non-activating

Locked. Reading/searching a past Board, Session or artifact must not change `active_board_id`, foreground binding, interaction mode or speech authority.

## D06 - Semantic operations, not raw database access

Locked. UI/MCP use domain/service operations. Raw SQL mutation is not a product surface.

## D07 - Safe Board-rooted file access

Locked. Memory operations are confined to the Board workspace root; reject traversal, symlink escape and arbitrary absolute paths.

## D08 - Reuse prerequisite artifact registry

Locked. Board manager reads/indexes generic artifacts and provenance. It does not create a second storage model for recordings/screenshots/transcripts.

## D09 - Dedicated `jarvis-workspace` MCP

Locked. The user accepted a dedicated server. Existing Board/Session MCP intents currently living on `jarvis-console` migrate to `jarvis-workspace` rather than being duplicated indefinitely.

## D10 - UI/MCP parity

Locked. Human and model surfaces call the same services/routes and return the same truth/error semantics.

## D11 - Agent/sub-agent inspection

Locked. The tool surface must support inspection of old Sessions/Boards without switching. Intended delegated agents must be able to use it, proven by traces.

## D12 - Deep manager + quick browser are separate UX jobs

Locked. Add a deep Sessions & Boards Manager in the top/settings control area. Keep a compact Board list/switcher for everyday navigation by evolving the existing Board UI.

## D13 - Board kind is metadata only in this task

Locked. `empty`, `meeting`, `presentation` may classify Boards. Opening a Board does not automatically enter Meeting/Presentation interaction behavior.

## D14 - Detailed live Meeting/Presentation behavior is deferred

Locked. Start/end lifecycle, `preparation/live/completed`, wake rules and OFF/SLEEP/profile UI are not implementation deliverables here.

## D15 - Prerequisite task must be reconciled, not reimplemented

Locked. `jarvis-session-context-recording-runtime` changes Session lifetime, SessionContext, artifacts and capture. Slice 00 must detect whether it has landed. If it has not, implementation work depending on its contracts is blocked or reordered explicitly; do not recreate a second incompatible version.
