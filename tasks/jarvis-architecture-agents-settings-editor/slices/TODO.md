# Slice Graph / TODO

Slice order is for identification/readability only. It is **not a serial execution mandate**.

## Readiness gate

- [x] `00-project-manager` - **READY** 2026-10-23 (`docs/10-slice00-audit.md`, corrections C1-C10).

Dispatch (≤ 3 agents) : vague A = 01, 03, 04 ; vague B = 02, 05, 06.

## Initial parallel ready set after READY

| Slice | Hard depends_on | Main output |
| --- | --- | --- |
| 01 Architecture graph runtime contract | none | Generic nodes/ports/connections + mutation service/handler |
| 02 Brain config runtime contract | none | Generic brain config + five-level delegation policy |
| 03 Sub-agent role routing contract | none | Role-oriented candidate policy + compatibility migration |
| 04 Architecture canvas UI | none | Real 2D graph editor against adapter/fixtures |
| 05 Brain config popup UI | none | Contextual floating config panel |
| 06 Sous-agents tab UI | none | Redesigned role/routing UI preserving robust existing behavior |

Soft requirements between these Slices are documented in each `SLICE.md`; they are not hard start blockers.

## Convergence

- `07-settings-integration-and-legacy-migration` depends on **01, 02, 03, 04, 05, 06**. It owns shared hot-file wiring, final Settings navigation and legacy/deep-link migration.
- `08-final-integration-e2e-qa` depends on **07**. It is the only Slice that runs the complete unit suite and the full integration/E2E acceptance campaign.

## Main hard chain

`00 -> {01,02,03,04,05,06} -> 07 -> 08`

## Major unlocks

- Completion of 01/02/03 publishes live runtime contracts that UI Slices reconcile through their adapters.
- Completion of 04/05/06 plus runtime Slices unlocks 07 shared integration.
- Completion of 07 unlocks final acceptance Slice 08.

## External coordination

Before dispatch, PM must ensure the related task `jarvis-settings-ui-reorganization` will not concurrently run its obsolete Slice 04 (`agents-models-reorganization`). The broader Settings shell work remains a soft integration input.

## Avancement (agent 0)

- [x] 01 - approuvée après QA (d18593e9, c4079a9c), fusion 446bf901.
- [x] 02 - approuvée après QA + rework (05432ab5, c3d23595, ead55dca, fix bf9bd806), fusion 644a3788.
- [x] 03 - approuvée après QA + rework (9d98fadb, 6ab60200, fix 3fca3d08), fusion 25b4a2d8.
- [x] 04 - approuvée après QA + rework (191cf17d, fix f9019300), fusion 0e70613e.
- [x] 05 - approuvée après QA (00c923ee, 7df94c51, fix a296998f), fusion a353bed7.
- [x] 06 - approuvée après QA + rework (4dd2b4d6, fix 2340748b), fusion de la branche s06.
- [ ] 07 - en cours (worktree arch-s07).
- [ ] 08 - après 07.
