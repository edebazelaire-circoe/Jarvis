# Stratégie d'implémentation

## Ordre

```
00 ─► 01 ─┬─► 02 (Live completion)  ─┐
          └─► 03 (relais typés)      ─┴─► 04 (présentation revalidée) ─► 05 (interruption) ─► 06 (intégration + validation réelle)
```

- **01 d'abord** : les tests rouges fixent les comportements attendus avant
  tout correctif, et servent de juge aux Slices suivantes.
- **02 seule** supprime déjà la plus grande part du retard ressenti ; elle doit
  pouvoir être livrée et mergée seule si la tâche s'interrompt.
- **02 et 03** touchent des fichiers disjoints (bridge/bouche vs Core/Control
  Center/CLI) : parallélisables, **une worktree par implémenteur**.
- **04** touche bouche + Core + contrat d'évènements : séquentielle, après 02
  et 03.
- **05** réutilise l'état `held_for_brain` de 04.
- **06** intègre, mesure, fait la validation Category 2 réelle et prépare le
  HV.

## Règles

- Chaque Slice commence par un freshness-check des lignes citées.
- Aucun test existant n'est « adapté » pour passer sans que la Slice dise
  explicitement quel comportement décidé il encodait et pourquoi il change
  (cas connus : `test_a_durable_answer_of_a_past_intent_is_carried_over_and_spoken`,
  `test_speech_presentation_scheduler.py:34`,
  `test_a_durable_answer_spoken_past_the_revision_is_carried_over_not_stale`).
- Diagnostics testlab : ne jamais réécrire une version déclarée ; ajouter une
  version (ex. `supersession` v4) — les runs stockés restent jugés par leur
  version.
- Tests en premier plan, par paquets (RAM hôte limitée).
