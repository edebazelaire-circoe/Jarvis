# Issue 001 — Test aléatoire : source évincée par son propre rangement

Hors périmètre de `jarvis-wake-word` : aucun rapport avec le mot d'éveil. Trouvé par la QA de la Slice 05 ; non corrigé ici.

## Symptôme

`tests/unit/test_presentation_integration.py::test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee` échoue de façon intermittente, sans modification du code. Taux observé : 2 échecs sur 9 exécutions.

## Cause probable

Le test range 12 sources (`MAX_WORKING_SET_SOURCES`) avec la même horloge fixe (`clock=lambda: now`), donc au **même horodatage**. L'identifiant de chaque source est un `uuid4` aléatoire (`jarvis/runtime/presentation_runtime.py`, ligne 1021 : `source_id = f"src-{uuid.uuid4().hex[:12]}"`). À horodatage égal, l'ordre d'éviction dépend de l'identifiant tiré, donc du hasard : la source que le test suppose être la plus vieille n'est pas toujours celle qui est évincée.

## Test et ligne concernés

- Test : `tests/unit/test_presentation_integration.py`, `test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee` (autour de la ligne 2435).
- Code : `jarvis/runtime/presentation_runtime.py`, `source_recorder`, ligne 1021.

## Piste (non appliquée)

Donner au test des horodatages strictement croissants (ou des identifiants déterministes), plutôt que douze sources au même instant.
