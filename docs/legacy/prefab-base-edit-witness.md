# Témoin de la porte d'édition de base non branché — provisoire

**Introduit :** tâche `jarvis-scene-window-prefab-foundation`, Slice 02
(2026-10-03). Contrat : [prefabs.md](../prefabs.md) › *Base-edit gate*.

## Ce qui est provisoire

`PrefabService.edit_base` exige un témoin `user_utterance_witness(texte) ->
event_id | None` : la demande citée doit se retrouver dans un tour récent de
l'utilisateur (condition 4). La Slice 02 livre les conditions 1 à 3 et le
point d'injection ; la recherche dans les Conversation Events arrive avec la
Slice 07 (outil `prefab_edit_base`, route `/v1/prefabs/{prefab_id}/base-edits`).

En attendant, `jarvis/core/v2_app.py` injecte `_no_utterance_witness`, qui ne
trouve jamais rien : **toute édition de base est refusée en production**
(`base_edit_unconfirmed`, trace `core.prefab.base_edit_refused`). Aucun
appelant n'existe encore (ni route ni outil), donc rien n'est perdu ; le
comportement est fermé par défaut, jamais ouvert.

Test : `tests/unit/test_prefab_service.py::test_edit_base_gate_condition_4_witness`
(témoin absent ou muet -> refus) et
`::test_edit_base_with_a_witness_publishes_into_the_data_root_only` (témoin simulé).

## Condition de retrait

La Slice 07 remplace `_no_utterance_witness` par la recherche réelle
(`ConversationEventQueryService.search`, tours utilisateur des 30 dernières
minutes, texte normalisé) et supprime cette page. Si la recherche ne sait pas
l'exprimer, les conditions 1 à 3 restent seules et l'écart devient une Issue
du handoff (décision du PM).
