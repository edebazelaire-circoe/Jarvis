# Annonce de fin de tâche absente

- **Date** : 2026-09-17
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`

## Comportement constaté

Pendant la même session que le retour sur le barge-in, une tâche de fond s'est terminée
(un point sur les changements du projet iGuard, en 37 secondes environ). L'utilisateur
n'a pas eu l'impression que JARVIS venait spontanément lui communiquer le résultat.

## Comportement attendu

Quand une tâche se termine et que l'agent n'est pas déjà en train de parler, JARVIS prend
la parole de lui-même, du genre « au fait, à propos de la tâche… », et donne le résultat.
Il doit le faire même en veille : seul le lancement d'une tâche reste muet.

## Contexte

Juste avant la fin de la tâche, une phrase captée à côté (« Bonjour à tous ») avait été
classée comme ne s'adressant pas à l'agent. Le cerveau a bien produit un texte d'annonce
du résultat, mais il faut vérifier si ce texte a été réellement dit, mis en file
d'attente, supprimé ou masqué.

## Pistes

