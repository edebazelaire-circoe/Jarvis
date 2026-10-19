# Repository audit evidence at handoff creation

Baseline: `edebazelaire-circoe/Jarvis` `main@82051c3ada7a695b88042e8772e7da35bbae2513` (observed 2026-10-19).

This reference is orientation for the fresh PM, not a substitute for Slice 00's blind re-audit.

## Confirmed existing architecture

- `CLAUDE.md`: local DB data outside git; schema changes require versioned migrations + backup + schema snapshot; never start/restart live JARVIS without user permission.
- `docs/ARCHITECTURE.md` “Core work state”: `WorkStateStore` is canonical normalized work truth shared by brain and UI; in-memory with provider replay/reconciliation.
- `jarvis/domain/work_state.py`: WorkStatus, WorkObservation, WorkItem, WorkSnapshot, WorkLink.
- Brain context reads the WorkState snapshot; provider prompts/raw trace are excluded.
- Agents panel reads `GET /api/work`; provider tracker is diagnostic/non-authoritative.
- Conversation Events durably records redacted `agent.subagent.*` and other conversation events; raw provider trace remains diagnostic.
- `docs/scene-model.md`: Scene is explicitly a projection; agent/job stars, category as primary visual cue; relations currently include `parent_of`, `explains`, `groups`.
- `jarvis/core/scene_projector.py`: actual sub-agents/jobs project into persistent Scene and current parent topology uses `parent_of`.
- `scene.sqlite3` is durable and separate from operational Core state.
- `docs/skills-and-loadouts.md`: `LoadoutResolver.resolve(profile, role)` exists with `coder`, `reviewer`, `research`; routing hook appends loadout manifest to sub-agent brief.
- `docs/prefabs.md`: existing `jarvis.document`, `jarvis.table` and richer prefab infrastructure can support polished reports/comparisons.

## Design implication

This feature should be an evolution of Work State + explicit semantic Mission History + Scene projection + Role Registry. A parallel “new task engine” would contradict existing architecture.
