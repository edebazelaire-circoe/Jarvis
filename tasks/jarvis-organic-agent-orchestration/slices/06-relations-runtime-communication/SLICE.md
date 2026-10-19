# Slice 06 — Relation runtime: Communication, Adversary, QA & Handoff

## Goal

Implement runtime creation/use of typed relations and durable explicit collaboration content without rigid interaction workflows.

## Dependencies

00-project-manager-readiness, 02-agent-relation-contracts, 03-work-state-mission-history, 05-orchestration-runtime-tools

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Create/close relation service/tool path.
- Relation-scoped communication boards/messages.
- Adversary creation among >=2 peer producer agents.
- QA request helper that spawns/links Quality Analyst to target work.
- Handoff helper that creates successor + complete packet + relation.
- Delegation relation alignment with sub-mission spawn.
- Inspection APIs for relation details/messages.

## Scope — out

- Frontend graph styling.
- Private reasoning capture.
- Hard-coded rounds/voting protocols.

## Implementation steps

1. Implement canonical relation service over Slice 03 persistence.
2. Ensure relation creation references real agent instances/missions and validates role/capability constraints.
3. Implement explicit message append/read with strict allowlisted fields.
4. Implement QA as reviewer relation, not adversary alias.
5. Implement Adversary as peer competition; allow N participants in canonical domain.
6. Implement Handoff transaction/recovery: successor never receives/claims a partial packet as complete.
7. Emit bounded audit/conversation events where useful without duplicating board content or raw reasoning.
8. Run real-agent traces demonstrating each relation and privacy sentinel test.

## Files likely touched

- Core relation/collaboration service
- MCP/tool schemas/catalogue
- mission history adapter/service
- conversation event definitions if required
- tests/replay and unit/integration relation runtime

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

- `HV-ORG-06-01` — Inspect a real Adversary run and confirm participants are competing producers defending different work, not one producer plus reviewer.
- `HV-ORG-06-02` — Inspect a real QA run and confirm the Quality Analyst is reviewing existing work asymmetrically.
- `HV-ORG-06-03` — Open a collaboration record and confirm it contains deliberate messages/decisions but no private reasoning/thinking transcript.

See `human-validation.json`.

## Acceptance criteria

- [ ] All five relations can be created/inspected as explicit semantics.
- [ ] QA and Adversary behavior remain distinct in real-agent traces.
- [ ] Communication messages persist and are not provider reasoning dumps.
- [ ] Handoff creates a fresh instance with complete bounded transfer.
- [ ] No fixed protocol forces unnecessary rounds.
- [ ] Failures are visible and do not fabricate successful collaboration.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- Persistence over the Slice 03 store; any extra table is a further `sqlite_state` migration with its snapshot.
- Reuse `SendMessage` (already in `DELEGATION_TOOLS`, `claude_local.py:477`) as the transport the brain uses to talk to a running agent; the communication board is the durable explicit record, not the transport.
