# ISSUE-02 — `activate()` et `mute()` ne sont pas sérialisés

**Découverte :** QA de la Slice 04, 2026-10-14, sur `f8d8860d`. La cause existe déjà dans `jarvis/runtime/voice_v2.py`, et l'arrêt Live la partage.

## Constat

Le seul garde entre `activate()` et `mute()` est un retour immédiat de `activate()` quand un `mute` est déjà en cours (`voice_v2.py:702`). Il n'y a pas de verrou. Le cas qui passe à travers :

1. le runtime est en `ERROR` avec un nettoyage audio en attente ;
2. un réveil lance `activate()` juste avant que le `mute()` d'une demande « Passer au chat » ne commence ;
3. `mute()` finit le premier et la demande est acquittée `accepted` ;
4. `activate()` finit ensuite en `ACTIVE`.

Le Chat se reverrouille au rapport suivant, en 1 s au plus, et la garde serveur de l'envoi suit l'état réel. Une écriture ne peut donc passer que pendant cette seconde au plus.

## Ce qu'il faudrait

Un verrou commun à `activate()` et `mute()` dans `PersistentVoiceRuntime`, hors du périmètre de la Slice 04 (son contrat interdit de modifier `mute()` et la logique de session).
