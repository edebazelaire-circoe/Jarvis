# Slice execution plan

## Readiness (Slice 00, 2026-10-20)

State: **READY** (audited `main@336f21be`, evidence `references/readiness-audit.md`).

- Task Type gate resolved: `waived-by-agent-0` on every Slice (precedent `jarvis-unified-chat-and-board-drop`).
- Mission History seam: `jarvis.sqlite3` v10 via `sqlite_state._MIGRATIONS`.
- This task absorbs the remaining scope of `jarvis-subagent-roles-interview` (Slice 10 = its Settings tab).
- I-004 (meaning of ephemeral) decided by agent 0 (`6f2ca77d`): one flag, silence kept, brain rule widened; Slice 07 owns the prompt rule change (`claude_local.py:101`).
- Nested spawn proven on CLI 2.1.304 (readiness audit §8): D04 feasible natively; the `PreToolUse` hook is the role source sent to Core (D25).
- Before each dispatch: freshness check of `references/readiness-audit.md` §7 (compare `HEAD..main` **and** `HEAD..origin/main`), result in `LOG.md`.

## Order and dependencies

```text
00 Project Manager readiness
  -> 01 Role / Mission Owner / Work Method contracts
  -> 02 Agent relation contracts
  -> 03 Work State + durable mission history
       -> 04 Role registry / loadouts / methods
       -> 05 Mission Owner orchestration runtime
            -> 06 Relation runtime / communication
            -> 07 Interviewer + background coordination
       -> 08 Scene projection / role+relation history
            -> 09 Task graph UI
       -> 10 Roles Settings UI
       -> 11 Output quality / prefab delivery
       -> 12 Reusable Work Method candidates
  -> 13 Integration / rollout / quality / docs
```

03 depends on 01+02. 04 depends on 01+03. 05 depends on 01+02+03+04. 06 depends on 02+03+05. 07 depends on 01+05+06. 08 depends on 02+03+05+06. 09 depends on 08. 10 depends on 04. 11 depends on 04+05. 12 depends on 01+03+04+05. 13 depends on every previous Slice.

## Status

- [x] 00-project-manager-readiness (READY 2026-10-20; QA qa-verification PASS_WITH_NOTES, notes fixed 51b5e52c)
- [x] 01-agent-role-mission-contracts (2026-10-20; QA code-review+qa-verification+agent-trace PASS_WITH_NOTES, notes fixed bb97059e)
- [x] 02-agent-relation-contracts (2026-10-20; QA code-review+qa-verification+agent-trace PASS_WITH_NOTES, notes fixed 6c5d1df4)
- [x] 03-work-state-mission-history (2026-10-20; QA code-review+qa-verification+runtime-validation+agent-trace PASS_WITH_NOTES after rework, notes fixed 557243df)
- [x] 04-role-registry-loadouts-methods (2026-10-20; QA code-review+qa-verification+agent-trace PASS_WITH_NOTES, notes fixed 2da89aa4)
- [ ] 05-orchestration-runtime-tools (implemented, QA pending)
- [ ] 06-relations-runtime-communication
- [ ] 07-interviewer-background-coordination
- [ ] 08-scene-projection-role-relations
- [ ] 09-task-graph-ui
- [ ] 10-agent-roles-settings-ui
- [ ] 11-output-quality-prefab-delivery
- [ ] 12-work-method-learning
- [ ] 13-integration-rollout-quality-docs

## Task done when

Actual execution can range from one ephemeral agent to recursive multi-agent teams; roles and semantic relationships are explicit; Mission Owners can organically add delegation, QA, adversary, communication and handoff as needed; Core Work State remains live truth; non-ephemeral actual history is persisted/projected; ephemeral nodes do not survive completion; role/relation identity is visually legible; communication exposes explicit messages but not private reasoning; serious final outputs use appropriate polished prefab surfaces; all independent QA and Human Validation gates pass.
