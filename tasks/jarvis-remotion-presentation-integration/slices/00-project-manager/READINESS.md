# Slice 00 - Readiness (2026-10-09)

## État déclaré : `READY` (avec réserves listées), aucun Slice dispatché

Aucun code produit modifié.

## Base (vérifiée dans le dépôt)

- Ancienne branche d'intégration `task/jarvis-remotion-presentation-integration` (9dae3d6d, base studio @16e3dc58 + READINESS
  `HUMAN_DECISION_REQUIRED`) **supprimée à la demande de l'Humain**, worktree `C:/Projects/jarvis/brm` recréé.
- Nouvelle branche créée depuis `origin/main` = `de7b9c59` (à jour après `git fetch`, 0/0 avec `main` local).
  `task/jarvis-interactive-presentation-studio` est ancêtre de `main` (S18-S22, S19ui, S20 présents en first-parent).
- Le handoff (zip Drive `12smNMUfdX69NyMzHrUKjYZnQqQPICGzs`, 85 472 o, 83 fichiers, inchangé depuis la copie du 2026-10-08)
  est recopié dans `tasks/jarvis-remotion-presentation-integration/` (commit S0 `163784b2`).

## Constats

1. Phase A du handoff (« attendre la fin de la tâche d'origine ») : le code de la tâche d'origine est fusionné dans `main`.
   Réserve : son LOG indique QA en attente pour les Slices 21/22 et des vérifications Humaines physiques H-1..H-11
   (`docs/presentation-studio-release.md`) ; `slices/TODO.md` de l'ancienne tâche n'est pas à jour. Cela n'empêche pas de
   démarrer, mais la Slice 01 doit les relever comme dette connue, pas comme régression de cette tâche.
2. Schémas : `jarvis.sqlite3` v8, `scene.sqlite3` v1.
3. Remotion est absent du code et des docs de `main` (`grep -i remotion` sur `jarvis/` et `docs/` : rien). Node v24.18.0, npm 12.0.1
   disponibles sur ce poste ; un essai isolé existe hors dépôt dans `C:/Projects/remotion-test` (non repris).
4. Test de base sur `main` seul (`.venv` du dépôt principal) : `test_schema_migrations` + `test_brain_capability_parity` =
   31 passed, **1 failed** : `test_every_tool_of_a_declared_server_is_documented_in_the_brain_prompt`
   (`{'jarvis-display': ['ui_intent_publish']}`). Rouge présent sur `main` : **pas à nous**, déjà listé « baseline » par S22
   de la tâche d'origine. Balayage large `tests/unit` à faire au début de la Slice 01 (recette : worktree détaché, morceaux
   en avant-plan).
5. Task Types : aucun vocabulaire « Workspace Task Type » dans ce dépôt ; waiver à acter par l'Humain (déjà accordé 4 fois).
6. Drive : le zip est dans `to-do` ; pas d'outil de déplacement, c'est à l'Humain de le passer en `current`.

## Décisions pour l'Humain

- D1 : confirmer que l'on démarre sans attendre QA 21/22 et H-1..H-11 de la tâche d'origine (recommandé : oui).
- D2 : waiver Task Type.
