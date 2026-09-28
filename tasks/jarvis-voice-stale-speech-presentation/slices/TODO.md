# Implementation TODO

## Orchestration rule

Exécuter la Slice 00 en premier, soi-même. Aucune Slice d'implémentation avant `READY`. Slices 02 et 03 parallélisables (une worktree chacune) ; tout le reste séquentiel.

## Slices

- [ ] 00 — Readiness et réconciliation (Project Manager)
  - Path: `slices/00-project-manager/SLICE.md`
  - Depends on: none
- [ ] 01 — Tests rouges : retard de 30 s et tour de retard
  - Path: `slices/01-red-conversation-tests/SLICE.md`
  - Depends on: 00
- [ ] 02 — Fin de parole Live par preuve locale
  - Path: `slices/02-live-output-completion/SLICE.md`
  - Depends on: 00, 01
- [ ] 03 — Relais spontanés typés (accusés transitoires)
  - Path: `slices/03-typed-spontaneous-notices/SLICE.md`
  - Depends on: 00, 01
- [ ] 04 — Présentation revalidée : la vérité survit, la formulation attend le cerveau
  - Path: `slices/04-presentation-revalidation/SLICE.md`
  - Depends on: 00, 01, 02, 03
- [ ] 05 — Interruption unifiée : l'utilisateur reprend la main
  - Path: `slices/05-unified-interruption/SLICE.md`
  - Depends on: 00, 01, 04
- [ ] 06 — Intégration, métriques et validation réelle
  - Path: `slices/06-integration-real-validation/SLICE.md`
  - Depends on: 02, 03, 04, 05

## Planning blocker

`task_type` reste null : proposer le waiver habituel en Slice 00.
