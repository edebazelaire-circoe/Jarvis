# Task 00 - Orchestrator and plan ownership

## Goal

Prendre la responsabilite de l'execution complete du plan V1 et garder les tasks coherentes avec la realite du code.

## Context

Cette task n'implemente pas une feature. Elle force le premier agent a lire les docs, inspecter le repository cible et piloter les tasks dans l'ordre.

## Scope
### In Scope
- Lire tout `docs/` et `tasks/TODO.md`.
- Identifier le repository de destination et son etat initial.
- Etablir le statut de chaque task.
- Verifier les prerequis machine/API.
- Maintenir le plan pendant toute l'implementation.

### Out of Scope
- Pas de feature produit.
- Pas de refactor non requis.

## Dependencies

Aucune.

## Implementation Steps

1. Lire les documents de ce handoff.
2. Inspecter le repo cible sans modifier le code.
3. Creer une courte note d'etat d'implementation si necessaire.
4. Verifier que chaque task est toujours pertinente.
5. Modifier/split/reordonner les tasks si le code existant l'exige.
6. Ne lancer la task 01 qu'apres avoir rendu le plan coherent.

## Files Likely Touched

- `tasks/TODO.md`
- `docs/01-decision-log.md`
- eventuel `IMPLEMENTATION-STATUS.md`

## Architecture Constraints

Le plan est une source de coordination, pas une contrainte aveugle. Toute modification doit garder les decisions securite et modularite verrouillees.

## Testing Requirements

- Verifier que tous les chemins de docs/tasks existent.
- Verifier qu'aucune task code n'est lancee sans `/caveman` et `/coding-guideline`.

## Acceptance Criteria

- Le repo cible est identifie.
- Les prerequis et risques bloquants sont notes.
- `tasks/TODO.md` correspond a l'ordre reel d'implementation.
- La task suivante est clairement selectionnee.

## Documentation Updates

Mettre a jour le decision log uniquement si une decision architecturale change.

## Handoff Notes

Rester en orchestration mode jusqu'au rapport final. Ne pas considerer une task comme terminee sans tests et acceptance criteria.
