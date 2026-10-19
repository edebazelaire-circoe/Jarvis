# Slice 13 — End-to-end integration, rollout, quality gates & documentation

## Goal

Prove the complete organic orchestration architecture end to end, harden rollback/degraded behavior, reconcile documentation, and leave explicit workstation Human acceptance.

## Dependencies

00-project-manager-readiness, 01-agent-role-mission-contracts, 02-agent-relation-contracts, 03-work-state-mission-history, 04-role-registry-loadouts-methods, 05-orchestration-runtime-tools, 06-relations-runtime-communication, 07-interviewer-background-coordination, 08-scene-projection-role-relations, 09-task-graph-ui, 10-agent-roles-settings-ui, 11-output-quality-prefab-delivery, 12-work-method-learning

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Cross-slice scenario harness.
- Real-agent trace analysis.
- Fault injection.
- Performance/bounds.
- Migration/restart/reconciliation.
- UI integration and visual QA.
- Documentation/runbook/rollback.
- Human acceptance checklist.

## Scope — out

- Adding new feature scope discovered late unless required to satisfy locked decisions.
- Claiming physical/UI Human checks passed without execution.

## Implementation steps

1. Run targeted unit/integration suites for every canonical domain.
2. Run scripted E2E scenarios from `docs/04-testing-and-quality.md`.
3. Run isolated real-agent traces for trivial, research, code, QA, Adversary, Handoff, Interviewer and polished-report cases.
4. Inject persistence/Scene/provider/Control Center/prefab failures.
5. Run release verifier/static architecture gates and record pre-existing unrelated failures separately.
6. Run frontend browser matrix and `/impeccable` final review.
7. Reconcile all canonical docs to actual code and mark implementation status honestly.
8. Create operator rollback/degraded notes and Human workstation checklist; do not restart live JARVIS without permission.

## Files likely touched

- integration/replay tests
- release/verification scripts only if needed
- `docs/ARCHITECTURE.md`, relation/role/mission docs, `docs/control-center-shell.md`, `docs/OPERATIONS.md`
- task evidence/reports outside production code per project conventions

## Architecture constraints

- Preserve Core Work State as canonical live execution truth.
- Preserve Scene as projection, never a second execution state machine.
- No speculative/planned future graph.
- No rigid orchestration workflow/protocol introduced under the name Work Method or Relation.
- Follow `CLAUDE.md`; do not start/restart the user's live JARVIS without explicit permission.
- Any new schema evolves through a versioned migration and schema snapshot.

## Required implementation skills

caveman; coding-guideline; impeccable

## Independent QA

Required: code-review; qa-verification; runtime-validation; agent-trace-analysis.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Frontend routing

This is frontend work. Prefer Claude where the workspace supports agent routing and run `/impeccable` before implementation/review. Preserve the Control Center shell/stacking/accessibility contracts.

## Human Validation

- `HV-ORG-13-01` — End-to-end: start from a code mission that organically requires research, a competing alternative, QA and Handoff; confirm the final graph tells that actual history clearly.
- `HV-ORG-13-02` — After mission completion, confirm non-ephemeral history remains inspectable while ephemeral one-shot agents are absent.
- `HV-ORG-13-03` — Review one multi-day/long-running style simulated mission and confirm nested Mission Owners are understandable without presenting Mission Owner as a role.
- `HV-ORG-13-04` — Review final representative report/comparison artifacts and approve visual/presentation quality.

See `human-validation.json`.

## Acceptance criteria

- [ ] All locked decisions are traceable to code/tests/docs.
- [ ] Simple ephemeral and complex recursive multi-agent scenarios both pass.
- [ ] No planned graph or chain-of-thought leak exists.
- [ ] Role/relation visuals and Settings pass Human visual validation.
- [ ] Non-ephemeral history survives restart; ephemeral does not.
- [ ] Serious report/comparison is visibly polished.
- [ ] Rollback/degraded behavior is documented and tested.
- [ ] All required independent QA complete; Human-only checks remain pending until actually executed.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- Include the sandbox real-agent trial inherited from `jarvis-subagent-roles-interview` and record the absorption of that task in the final report (Drive move stays with the Human).
- Known pre-existing failures on main to report separately: `test_brain_capability_parity` (ui_intent_publish), `test_brain_delegation` (prompt).
