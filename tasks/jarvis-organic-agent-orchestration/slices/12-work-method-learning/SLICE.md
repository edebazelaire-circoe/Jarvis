# Slice 12 — Reusable Work Method candidate learning & promotion

## Goal

Allow successful organically adapted working approaches to become explicit reusable Work Method candidates based on repetition + quality, without storing rigid historical graphs as workflows.

## Dependencies

00-project-manager-readiness, 01-agent-role-mission-contracts, 03-work-state-mission-history, 04-role-registry-loadouts-methods, 05-orchestration-runtime-tools

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Evidence model for recurrence and quality.
- Candidate creation/proposal.
- Explicit promotion into versioned Work Method.
- Method provenance and role applicability.
- No silent self-modification.

## Scope — out

- Automatic promotion after one use.
- Copying exact agent graphs into a mandatory workflow.
- Self-editing existing methods without versioning/approval.

## Implementation steps

1. Define measurable recurrence keys that describe heuristic approach, not exact topology.
2. Define quality evidence sources: QA outcomes, user validation where available, observable success criteria; do not infer approval from silence.
3. Persist candidates with provenance.
4. Expose explicit promotion service/tool/UI seam as appropriate to existing architecture.
5. Create a new immutable/versioned method definition on promotion.
6. Test that poor/repeated methods are not promoted and that one successful run is insufficient.

## Files likely touched

- Work Method/candidate domain + store/service
- role registry integration
- inspection/promotion API
- tests/unit/replay
- canonical Work Method docs

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

- [ ] Candidate requires repetition plus positive quality evidence.
- [ ] Promotion is explicit.
- [ ] Promoted method stores principles/heuristics, not a fixed historical DAG.
- [ ] Existing methods are versioned rather than silently overwritten.
- [ ] No user approval is inferred from absence of complaint.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- Candidates persist in `jarvis.sqlite3` next to Mission History (next `sqlite_state` migration after Slice 03, with its snapshot); methods are attached to roles in the extended `subagent_roles` registry.
- Documentation: `docs/work-methods.md`.
