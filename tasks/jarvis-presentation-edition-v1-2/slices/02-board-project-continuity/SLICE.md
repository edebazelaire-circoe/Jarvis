# Slice 02 — Board project continuity

## Goal
Make reopening a Presentation Board feel like resuming a project: Jarvis immediately understands purpose, objectives, decisions, current state, useful documents, open questions and next step.

## Context
Board memory already exists and `summary.md` is automatically read into every turn. Sessions and CLI conversations can restart without losing the Board. The missing piece is the Presentation-specific durable project convention and the behavior that keeps it current.

## Canonical Concepts
- `docs/boards.md` Board memory/hydration/non-activating inspection/Dossier.
- `jarvis/runtime/board_brief.py` and Board hydration.
- Board memory MCP tools.
- Existing mission dossiers under `memory/missions/`.

## Scope
### In Scope
- define `summary.md` as the Presentation project digest convention;
- establish compact semantic sections: Finalité, Objectifs, État actuel, Décisions, Questions ouvertes, Prochaines étapes, Documents clés (wording may adapt but semantics must remain stable);
- instruct/enable the Presentation brain to update the digest after meaningful state changes, not every utterance;
- on Board activation/restart, inspect the digest and relevant Dossier/document entries needed to resume;
- keep multiple presentations/documents under the same Board/project identity;
- make absence/corruption of `summary.md` degrade safely and allow first meaningful turn to create it.

### Out of Scope
- new project database/table;
- copying old Session conversation into Board memory;
- forcing every transient thought into durable memory;
- changing Board type immutability.

## Dependencies
- `01-presentation-product-brain-scope`.

## Implementation Steps
1. Write a canonical Presentation-project memory contract layered on existing Board memory.
2. Implement/update prompt/behavior so meaningful goals, decisions, progress and next-step changes are persisted through `board_memory_*` APIs.
3. Prefer targeted edits/conditional writes; preserve concurrent mission/research files.
4. Define activation/resume behavior: read hydrated summary first, inspect named key documents/Dossier entries only when needed, then continue without asking the user to reconstruct prior state.
5. Ensure `context_summary` remains bounded management metadata and does not become a second detailed project truth.
6. Add recovery behavior for missing/unreadable summary and archive/read-only rules.

## Files Likely Touched
Presentation brain prompt/rules, Board brief/memory helpers if required, workspace tools/tests, canonical docs. Avoid storage-schema changes unless the audit proves necessary.

## Architecture Constraints
- Board remains the durable owner;
- Session/CLI history is not the project store;
- `summary.md` stays concise enough for automatic hydration;
- no cross-Board memory leakage.

## Automated Validation
- create Presentation Board, establish project state, restart Core/Control Center/brain, then verify next turn receives correct durable project state;
- A/B/A Board switch returns each Board's own project digest;
- multiple presentation sources/documents remain discoverable under one Board;
- missing summary creates no crash and can be initialized;
- concurrent Board-memory mutation conflict tests;
- real agent trace showing resume uses Board memory rather than asking “where were we?”.

## Acceptance Criteria
Jarvis can resume a project after process/session churn with no dependency on the previous natural-language conversation transcript and without confusing another Board's state.

## Documentation Updates
Document the Presentation-project `summary.md` convention next to Board memory, without changing generic Board memory into a mandatory schema for other editions.

## Handoff Notes
Do not overfill the digest. Detailed research/source material belongs in `documents/` or mission files and is linked from the digest.