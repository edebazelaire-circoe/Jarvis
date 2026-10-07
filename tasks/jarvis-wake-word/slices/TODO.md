# Slice execution order (written by Slice 00, 2026-10-07)

Binding inputs: `../docs/01-blind-audit.md`, `00-project-manager/READINESS.md` (décisions D1-D7). Read your Slice's `## Slice 00 contract (binding)` first.

| # | Slice | Depends on | Status | QA tier |
|---|---|---|---|---|
| 1 | `00-project-manager` | — | DONE (planning) | — |
| 2 | `01-feasibility-dependencies`: openWakeWord sur Python 3.14, extra `wakeword`, catalogue de modèle SHA-256, notice de licence, coût d'inférence | 00 | APPROVED (2026-10-07): QA critical B1 (tests SHA/taille) corrigé par le rework `6f4cc04` (cherry-pick `7ce173a`), 5 mutants re-tués | critical |
| 3 | `02-openwakeword-engine`: `OpenWakeWordEngine` conforme à `WakeWordEngine`, seuil, cooldown, dernier score | 01 | APPROVED (2026-10-07): QA critical sans blocking, 11 mutants tués ; polish → Slice 08 (journal facultatif à aligner dans SLICE.md, trames np.array/bytes refusées : Slices 04/05 passent un tuple d'entiers) | critical |
| 4 | `03-wake-word-settings`: bloc `wake_word`, module, route, refus stricts, défaut désactivé | 00 | APPROVED (2026-10-07): QA glue B1 (OverflowError sur entier démesuré) corrigé par le rework S3 (cherry-picks `17d0a9d0`..`746bda25`), 3 mutants re-tués ; effet de bord `_settings()` = issue transverse identique à /api/interaction-mode | glue |
| 5 | `04-presentation-wiring`: fabrique configurable côté PRESENTATION, traces score/seuil | 02, 03 | APPROVED (2026-10-07): QA critical sans blocking, 9/10 mutants tués (le 10e tué par test_presentation_audio_capture) ; polish P1-P3 corrigés par le rework S4 (cherry-picks `770523b1`..`11e5ec48`) ; I1 (pas de garde de queue anti-écho) → Slice 09 | critical |
| 6 | `05-simple-wiring`: détecteur SIMPLE à flux propre avec moteur injecté, propriétaire du micro, `EXPECTED_INPUT_OPENERS` | 02, 03 | DELIVERED, awaiting QA critical (2026-10-07) | critical |
| 7 | `06-activation-parity`: source propagée jusqu'à `activate()`, parité F9/mot d'éveil, veille vocale minimale | 04, 05 | DELIVERED, awaiting QA glue (2026-10-07) | glue |
| 8 | `07-control-center-ui`: activation, sensibilité, état de santé dans les réglages | 03 | READY | ui |
| 9 | `08-docs-acceptance`: docs canoniques, copies `sw2`/`sw3` si suivies, fiche d'acceptation matérielle | 04-07 | READY | glue |
| 10 | `09-human-microphone-validation`: validation micro réel par le Human, faux positifs/négatifs, écho TTS, deux modes, F9, panne fournisseur | tout | READY | critical |

Rules:
- Sequential dispatch, one implementer per worktree. A QA agent that mutation-tests is a writer.
- Mutation testing only on critical tiers (01, 02, 04, 05, 09 pour sa partie logicielle): ≤10 mutants, foreground.
- Freshness check of the cited file:line refs before each dispatch (le code bouge : plusieurs sessions fusionnent dans main).
- Task Types are waived (A11).
- Human checks: HV-WAKEWORD-UI-01 (07), HV-WAKEWORD-MIC-01 (09, last).
- Baseline failures: voir `00-project-manager/READINESS.md` (6 unit hérités, 1 intermittent).
- Sweep large unit + integration après chaque lot de reworks intégrés.
