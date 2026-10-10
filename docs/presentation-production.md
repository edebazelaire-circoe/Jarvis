# Production d'une présentation ou d'une vidéo : le brain orchestre, trois agents construisent

Contrat de `jarvis/runtime/presentation_playbooks.py`. Les tests sont dans `tests/unit/test_presentation_playbooks.py`.

## Pourquoi

Un sous-agent ne voit ni le prompt système du brain ni le guide du planificateur (`PLANNER_PROMPT`). Il n'a que la
consigne que le brain a rédigée, et le prompt du brain demande des consignes de « quelques lignes de faits ». Une
vidéo demandée ainsi sort sans contexte, sans direction artistique rappelée et sans méthode.

## Le chemin

Un sous-agent ne lance pas de sous-agent : le brain enchaîne les rôles, tous en arrière-plan.

| Étape | Marqueur de la description de l'Agent | Rôle |
| --- | --- | --- |
| 1 (si le Board manque de matière) | `[general] [research]` | recherches, en parallèle |
| 2 | `[general] [presentation-brief]` | lit le Board, la direction artistique, les consignes de l'utilisateur ; écrit `presentation/production_brief.md` dans la mémoire du Board ; rend ses questions ouvertes |
| 3 | le brain | relaie une question bloquante à l'utilisateur, une à la fois, avec un choix par défaut |
| 4 | `[code] [presentation-author]` | construit depuis le dossier ; se compare aux critères de réussite ; corrige |
| 5 | `[general] [presentation-review]` | critique, sans rien modifier ; écrit `presentation/review.md` ; s'il y a des écarts, le brain relance l'auteur |

La qualité passe avant la vitesse : 30 minutes à 2 heures sont acceptables.

## Comment la méthode arrive à l'agent

Le hook de routage (`routing_hook.charter_input`) appose le playbook du rôle sur la consigne de l'appel `Agent`, comme
la charte du chantier : à toute profondeur, quoi que le brain ait rédigé, et jamais en double (`PLAYBOOK_MARK`). Le
brain n'a donc qu'à écrire le marqueur et une consigne courte (les mots exacts de l'utilisateur, le chemin du dossier).
La règle du brain est `claude_local.PRESENTATION_PRODUCTION_RULE`.

Le playbook de l'auteur contient `PLANNER_PROMPT` en entier : la porte de qualité s'applique à lui, et ses questions vont
dans son compte rendu, jamais à l'utilisateur.

## Limites connues

- Aucune vérification visuelle automatique : l'export et la lecture sont des gestes de l'utilisateur
  (`user_request`). La relecture juge sur la structure, les sources et la partition.
- La règle du brain est lue au premier tour d'une conversation ; une conversation déjà ouverte la voit après un
  redémarrage de JARVIS. Le hook, lui, s'applique dès l'appel suivant.
- Non éprouvé avec un vrai modèle : à valider par une vraie demande de vidéo.
