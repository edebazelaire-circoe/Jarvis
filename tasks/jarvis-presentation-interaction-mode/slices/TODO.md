# Slice execution order (repaired by Slice 00, 2026-10-05)

Binding architecture: `../docs/06-resolved-architecture.md`. Read your Slice's `## Slice 00 contract (binding)` first.

| # | Slice | Depends on | Status | QA tier |
|---|---|---|---|---|
| 1 | `00-project-manager` | — | READY | — |
| 2 | `01-contract-reconciliation`: reveal fix + contract test + reconciliation doc | 00 | READY | glue |
| 3 | `02-interaction-mode-contract`: process-lifetime mode follower, explicit legacy refusal | 01 | READY | glue |
| 4 | `04-ambient-presentation-lane`: structural brain-turn authority, open-before-submit | 01, 02 | READY | critical |
| 5 | `05-presentation-working-set`: brain-turn presentation context transport, deaf pruning | 04 | READY | critical |
| 6 | `06-background-intelligence-arbitration`: pool 2+1 configurable, reachability | 05 | READY | glue |
| 7 | `07-manifestation-policy`: output intent + display sink port + direct adapter | 05, 06 | READY | glue |
| 8 | `10-observability-attention`: canonical timeline events, `/api/status.presentation`, attention cue | 06, 07 | READY | glue + ui |
| 9 | `03-control-center-mode-ui`: selector verification + live Presentation status | 02, 10 | READY | ui |
| 10 | `11-end-to-end-hardening`: scenario suite, privacy (Issue 002), latency | 03, 04, 05, 06, 07, 10 | READY | critical |
| — | `08-tool-brain-integration` | 07 + Tool Brain merged on main | DEFERRED | glue (when undeferred) |
| — | `09-scene-prefab-integration` | 05, 07 + prefab foundation merged on main | DEFERRED | glue (when undeferred) |

Rules:
- Sequential dispatch, one implementer per worktree. A QA agent that mutation-tests is a writer.
- Mutation testing only on critical tiers (04, 05, 11): ≤10 mutants, foreground.
- Freshness check of the cited file:line refs before each dispatch.
- Task Types are waived (A11).
- Human checks: HV-PRESENTATION-MODE-UI-01 (03), HV-PRESENTATION-ATTENTION-01 (10), HV-PRESENTATION-E2E-01 (11, last). They supersede the 2026-09 HV-PRES-* checks (06 R8).
