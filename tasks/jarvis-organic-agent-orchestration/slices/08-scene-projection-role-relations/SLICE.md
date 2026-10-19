# Slice 08 — Role-aware constellation projection & actual relation history

## Goal

Extend the existing Scene projection so actual non-ephemeral agent roles and typed relations become persistent visual topology, while Scene remains a projection.

## Dependencies

00-project-manager-readiness, 02-agent-relation-contracts, 03-work-state-mission-history, 05-orchestration-runtime-tools, 06-relations-runtime-communication

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Role identity projection onto agent stars.
- Mission Owner marker in projection data.
- Projection of Delegation/Communication/Adversary/QA/Handoff actual relations.
- Compatibility with existing `parent_of`/artifacts/signals.
- Ephemeral exclusion from persistent scene/history.
- Restart reconciliation from durable mission history + current Work State.
- No planned/future topology.

## Scope — out

- Final CSS/visual design (Slice 09).
- Making Scene execution truth.
- Archiving agents automatically outside current user disposition policy.

## Implementation steps

1. Audit `SceneObject.category`, relation closed vocabulary and authority matrix.
2. Choose backward-compatible scene-domain change for role identity and new relation kinds/style semantics.
3. Extend reducer/wire/transport tests before projector changes.
4. Extend `SceneProjector` to join Work State with durable mission semantics.
5. Project only actual explicit relations; use deterministic IDs.
6. Implement ephemeral rule so completed ephemeral work leaves no persistent scene/history record; verify no resurrection on restart.
7. Reconcile non-ephemeral completed history on Core restart without inventing live status.
8. Test saturation/degraded Scene paths.

## Files likely touched

- `jarvis/domain/scene.py`
- `jarvis/core/scene_projector.py`
- scene wire/client parity modules
- `docs/scene-model.md` / `ARCHITECTURE.md`
- tests/unit/integration scene projector

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

Required: code-review; qa-verification; runtime-validation.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Human Validation

- `HV-ORG-08-01` — Complete a non-ephemeral multi-agent mission, restart isolated Core, and confirm actual role/relation history reappears without invented live status.
- `HV-ORG-08-02` — Complete a trivial ephemeral task and confirm no persistent constellation/history star remains afterward.

See `human-validation.json`.

## Acceptance criteria

- [ ] Role and Mission Owner semantics reach Scene from Core-owned data.
- [ ] All typed actual relations can be projected deterministically.
- [ ] Existing scene relations/artifacts/signals still work.
- [ ] No planned relation is projected.
- [ ] Ephemeral completed work is absent after completion/restart.
- [ ] Non-ephemeral completed mission history remains visible until user disposition/archive.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- Role identity must live in a **runtime-owned** field (like `exec_state`/`work_ref`, `EXECUTION_FIELDS`), not in `category`, which brain and user can write (`_WRITABLE_FIELDS`, `scene_update_object`, `patch_selection`).
- New relation kinds/fields change stored payloads: expect `SCENE_SCHEMA_VERSION` 2 and `sqlite_scene._MIGRATIONS[2]` (today `_SCHEMA_VERSION = 1`, `_MIGRATIONS = {}`) with `tests/schema/scene.v2.sql`.
- **Ephemeral today (main):** the star is created and persisted, then hidden by the page view model 6 s after success (`docs/ARCHITECTURE.md` "Ephemeral tasks"). D08 is therefore not met yet. Recommended path: the projector never creates a persistent star for an item that is still ephemeral (live visibility stays in the Agents panel / work table already wired to `ephemeralVisibility`); a failure lowers the flag and the star is then created as an ordinary one. Do **not** reuse the `eph` worktree prototype (runtime `ARCHIVE` exception to scene Decision 12, leaves history rows).
- Documentation: `docs/scene-model.md`, `docs/ARCHITECTURE.md` "Runtime scene projection" and "Ephemeral tasks".
