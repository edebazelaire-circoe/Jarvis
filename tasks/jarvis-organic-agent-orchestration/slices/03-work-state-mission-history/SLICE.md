# Slice 03 — Work State integration & durable Mission History

## Goal

Integrate semantic role/mission metadata with live Core Work State and add durable Core-owned non-ephemeral mission history without creating a second execution truth.

## Dependencies

00-project-manager-readiness, 01-agent-role-mission-contracts, 02-agent-relation-contracts

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Optional normalized WorkObservation/WorkItem semantic identifiers needed by UI/Brain.
- Durable Mission History store for mission identity, immutable role assignment, ownership changes/handoffs, typed relations and explicit relation records.
- Versioned DB migration if no existing store already covers the requirement.
- Restart/replay reconciliation between short-lived Work State and durable semantics.
- Ephemeral non-retention policy.
- Brain context bounded summaries.

## Scope — out

- Frontend rendering.
- Agent orchestration tool API.
- Duplicating WorkStatus/progress into a competing state machine.

## Implementation steps

1. Confirm storage owner chosen by Slice 00.
2. If using `jarvis.sqlite3`, add additive `_MIGRATIONS`, bump schema, write schema snapshot per `CLAUDE.md`; never rewrite published migration.
3. Add Core service/port for mission history and strict transactions.
4. Link WorkItem identity `(source, external_id)` to semantic agent instance without inference from label.
5. Design restart reconciliation: provider replay may refresh live state but cannot mutate immutable role/history.
6. Implement explicit ephemeral policy so completed ephemeral work never becomes durable mission/scene history.
7. Extend bounded BrainWorkContext only with fields required for supervision; protect 6k-ish context budget or current audited budget.
8. Test storage outage degradation: live work continues, history is marked degraded.

## Files likely touched

- `jarvis/adapters/sqlite_state.py` if migration required
- `jarvis/core/*mission*` service
- `jarvis/ports/*mission*`
- `jarvis/domain/work_state.py` additive fields if required
- `jarvis/core/brain_context.py` / brain context renderer as needed
- tests/schema/* if schema changes
- tests/unit/integration mission-history/work-state tests

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

caveman; coding-guideline

## Independent QA

Required: code-review; qa-verification; runtime-validation; agent-trace-analysis.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Human Validation

- None for this Slice.

See `human-validation.json`.

## Acceptance criteria

- [ ] Core Work State remains sole live execution-status truth.
- [ ] Durable role/relation history survives Core restart.
- [ ] Immutable role cannot be rewritten by replay/late observation.
- [ ] Completed ephemeral instance creates no retained mission-history/scene-history node.
- [ ] History failure does not stop live work and is visible diagnostically.
- [ ] Migration policy and schema snapshot gates pass if schema changed.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- **Persistence seam fixed (I-002):** additive tables in `jarvis.sqlite3` through `_MIGRATIONS[10]` of `jarvis/adapters/sqlite_state.py` (`_SCHEMA_VERSION` 9 -> 10, automatic `.v9.bak`, snapshot `tests/schema/jarvis_state.v10.sql`), a dedicated adapter `jarvis/adapters/sqlite_mission_history.py` on the shared connection (`run_serialized`, pattern `sqlite_artifacts.py`), port `jarvis/ports/mission_history.py`, Core service `jarvis/core/mission_history.py`. If another branch lands a v10 first, take the next number.
- Corrected paths: `TrackerWorkObserver` is in `jarvis/runtime/work_ingress.py`; `BrainWorkContext` in `jarvis/domain/brain_context.py` (Core side `jarvis/core/brain_context.py`); `work_brief.py` is `jarvis/runtime/work_brief.py`.
- The role is today only in the tracker snapshot (`agent_tasks.py:1011`, read from the description marker); carry it explicitly into `WorkObservation`/`WorkItem` (and `OBSERVATION_WIRE_KEYS`) if the UI/Brain need it.
- Link semantic instances to the stable `work_key` (the tracker's `AgentTask.id` moves from `tool_use_id` to `task_id`), never to the raw id or a label.
- **Role source (D25 arbitration, audit §8 N5):** the semantic facts sent to Core (role, ephemeral, mission, parent) come from the `PreToolUse` hook, before the spawn, under a Core contract; it has `tool_use_id` (join key with the tracked task) and, for nested calls, the caller's `agent_id`. The `stream-json` parsing of `agent_tasks.py:1011` stays diagnostic/compatibility display. The hook is short-lived and offline: it records a bounded fact the Control Center attaches to the observation; never a blocking call to Core. This Slice fixes the contract, Slice 05 the wiring.
- **Conversation Events are not history (N6):** `subagent.*` spans durably record ephemeral sub-agents too (`subagent_conversation.py:333`, attribute `ephemeral` allow-listed at `conversation_events.py:298`). That diagnostic record is not a history node in the sense of D08 and must not feed Mission History.
- Ephemeral: never write a durable row while the instance is ephemeral; a failure lowers the flag (existing rule) and the instance may then be retained.
- Documentation: `docs/mission-history.md` + link from `docs/ARCHITECTURE.md` "Core work state".
