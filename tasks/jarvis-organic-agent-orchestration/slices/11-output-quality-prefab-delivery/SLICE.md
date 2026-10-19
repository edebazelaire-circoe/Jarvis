# Slice 11 — Mission completion quality & prefab-first rich delivery

## Goal

Make Mission Owners responsible for both evidence/result quality and appropriate final presentation, reusing existing prefab/display systems for serious deliverables.

## Dependencies

00-project-manager-readiness, 04-role-registry-loadouts-methods, 05-orchestration-runtime-tools

## Dispatch gate

Do not start this Slice until Slice 00 is `READY` and this Slice's `metadata.json.task_type` has been replaced with an exact approved Workspace Task Type. One Work Agent owns this Slice.

## Scope — in

- Mission Owner completion guidance/quality checks.
- Output-surface selection heuristics.
- Use existing `jarvis.document`, `jarvis.table` and richer prefabs when appropriate.
- Structured fallback on display/prefab failure.
- Agent traces proving simple outputs stay simple and serious reports are polished.

## Scope — out

- Building a new report renderer.
- Forcing every answer into a prefab.
- Marking aesthetic quality as machine-proven without Human review.

## Implementation steps

1. Audit current brain display/prefab tools and style guide.
2. Add reusable Mission Owner delivery guidance tied to task/output intent.
3. Map comparison/report/document intents to existing semantic prefab catalogue instead of hard-coded one-off HTML.
4. Ensure display acknowledgement/failure is part of delivery completion where a visual artifact was requested.
5. Add deterministic tests for simple vs comparison vs report choice.
6. Run real-agent traces and Human review of representative research/comparison/report outputs.

## Files likely touched

- Mission Owner prompt/policy layer
- prefab/display tool integration (reuse, not duplicate)
- tests/replay output-quality scenarios
- relevant prefab/agent operation docs

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

- `HV-ORG-11-01` — Ask for a serious comparative research result and verify JARVIS delivers a polished structured comparison/report using appropriate prefab surfaces rather than an ugly raw text dump.
- `HV-ORG-11-02` — Ask for a trivial short result and confirm JARVIS does not force an unnecessary heavy report/prefab.

See `human-validation.json`.

## Acceptance criteria

- [ ] Simple answer is not needlessly heavyweight.
- [ ] Serious comparison uses structured readable display.
- [ ] Serious report uses polished document/rich surface.
- [ ] Prefab/display failure degrades honestly.
- [ ] Mission Owner judges sufficiency before final delivery.
- [ ] Human judges representative output visually acceptable.

## Documentation updates

Update the canonical repository docs for every contract made authoritative by this Slice. Do not leave handoff-only truth after code lands.

## Readiness amendments (Slice 00, 2026-10-20)

Audited HEAD `main@336f21be`. Evidence: `references/readiness-audit.md`. These amendments override the stale parts of this Slice; they do not change any locked decision of `docs/01-decisions.md`. Task Type gate: resolved (`waived-by-agent-0`). Run the freshness check of `references/readiness-audit.md` §7 before dispatch.

- Paths confirmed: `jarvis/core/prefab_service.py` (`PrefabService`), base prefabs `jarvis/prefabs/base/jarvis.{document,table,checklist,window,browser}`, agent tools `jarvis-display` (`docs/prefabs.md` "Agent tools"), consumers section (`docs/prefabs.md` "Consumers").
- Documentation: delivery section of `docs/subagent-roles.md` + `docs/prefabs.md` "Consumers".
