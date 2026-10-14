# ISSUE-01 — Réponse Brain > 8192 caractères absente du chat

**Découverte :** Slice 00, 2026-10-14, à 664d767b. Ce n'est pas une régression de cette tâche.

## Constat

`MAX_CONTENT_CHARS = 8192` (`jarvis/domain/conversation_events.py:40`). Un `brain.message.published` dont le texte est plus long n'est pas enregistré (`docs/conversation-events.md`, « Text above the content bound (8192) is not truncated: the event is not recorded »). Le chat, projection de ces événements, ne peut donc pas l'afficher.

## Atténuation dans cette tâche

- Le brief du canal texte demande une réponse de 6000 caractères au plus, et au-delà un fichier dans le dossier du Context.
- Après 120 s sans réponse, l'interface affiche un état honnête et un lien vers la chronologie complète.

## Ce qu'il faudrait

Une évolution du contrat d'événements, par exemple une troncature marquée avec la référence au texte complet. Elle sort du périmètre de cette tâche.
