# Issue 003 — Le compte du registre de propriétaires du micro n'est pas lisible en SIMPLE au repos

Non bloquante. Trouvée en Slice 08 en écrivant la fiche `HV-WAKEWORD-MIC-01-i`. Non corrigée (aucun changement de code produit).

## Symptôme

`jarvis/audio/input_ownership.py::open_input_stream_count` compte les flux d'entrée vivants, mais le compte n'est exposé qu'à l'entrée en PRESENTATION (`presentation.runtime.entered`, `physical_input_owners`) et dans des tests. En SIMPLE, au repos, ni une trace, ni une route, ni l'écran ne le disent.

## Effet

Le contrôle « aucun micro ouvert quand `enabled=false` » ne peut pas citer le registre pour le Human : la preuve sur le poste est indirecte (aucune ligne `wake.own_stream.started` / `wake.shared_pcm.started`, page de confidentialité du micro de Windows, `physical_input_owners=1` à l'entrée en PRESENTATION). Le compte exact est vérifié par `tests/unit/test_simple_wake_word_wiring.py` avec des faux flux.

## Piste (non appliquée)

Ajouter le compte et les étiquettes des propriétaires vivants à un événement périodique ou à `GET /api/status`.

## Outillage (Slice 09, 2026-10-08) : l'Issue reste ouverte

`scripts/check_wake_word_disabled.py` lit le compte `input_ownership` après avoir composé le mot d'éveil de SIMPLE avec `enabled=false` sur un faux `sounddevice` (0 propriétaire, 0 tentative d'ouverture, avec un cas témoin à 1). C'est une preuve du code de composition, pas du processus Voice vivant : le compte n'est toujours exposé ni par une trace, ni par une route, ni à l'écran. L'Issue reste ouverte (non bloquante) ; la preuve sur le poste reste indirecte (aucune ligne `wake.own_stream.started` / `wake.shared_pcm.started`, page de confidentialité du micro de Windows, `physical_input_owners=1` à l'entrée en PRESENTATION).
