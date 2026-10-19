# Slice 02 — Typed Agent Relation & collaboration record contracts

## Goal

Define strict semantic contracts for Delegation, Communication, Adversary, QA and Handoff, including explicit collaboration messages and reasoning/privacy boundaries.

## Dependencies

00-project-manager-readiness, 01-agent-role-mission-contracts

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Typed relation IDs and lifecycle.
- Delegation direction and sub-mission association.
- Communication participant sets and relation board identity.
- Adversary as symmetric peer competition with >=2 producers.
- QA as asymmetric review, distinct from Adversary.
- Handoff packet schema and predecessor/successor link.
- Explicit relation message types (proposal, critique, question, decision, result summary, etc.).
- Privacy rule excluding hidden thinking/raw provider payloads.

## Scope — out

- Rigid multi-round relation protocols.
- UI rendering.
- Persistence runtime.
- Private chain-of-thought export.

## Implementation steps

1. Audit existing `SceneRelation`, conversation events and provider trace contracts.
2. Create pure relation/message/handoff domain types with bounds and strict decode.
3. Decide N-party Adversary canonical representation independent of current binary Scene links.
4. Define allowed endpoints/participant invariants and relation closure semantics.
5. Add privacy allowlist for durable collaboration content.
6. Add tests proving QA != Adversary and that hidden reasoning fields/raw blobs are rejected.

## Files likely touched

- new/extended `jarvis/domain/*relation*` modules
- possible additive conversation-event type definitions only if needed
- tests/unit/*relation*
- canonical relation docs

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

Required: code-review; qa-verification; agent-trace-analysis.

QA is independent of the implementing Work Agent. QA cannot mark Human checks passed.

## Human Validation

- None for this Slice.

See `human-validation.json`.

## Acceptance criteria

- [ ] All five relation kinds are explicit data.
- [ ] Adversary supports peer competition; QA remains directional review.
- [ ] No relation requires a fixed number/order of interaction rounds.
- [ ] Communication messages are explicit bounded records only.
- [ ] Handoff requires a complete bounded transfer packet.
- [ ] No hidden reasoning/raw provider JSON can enter the collaboration contract.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- `SceneRelation`/`RelationKind` (`jarvis/domain/scene.py:236`, closed `parent_of|explains|groups`) is a projection vocabulary; the canonical relation model is defined here independently (N-party Adversary allowed).
- Conversation Events already allow-list the boolean attribute `ephemeral` and record `subagent.*` spans; add event types only if Slice 06 needs them for audit.
- Documentation: `docs/agent-relations.md`.
