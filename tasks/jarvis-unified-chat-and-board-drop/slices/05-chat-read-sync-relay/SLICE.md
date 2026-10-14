# Slice 05 — Lecture live et rattrapage via événements existants

## Goal
Servir la projection avec cursor, relecture et mises à jour sans créer d'historique bis.

## Context
Control Center proxifie déjà `/api/conversations...` vers Core; long-poll et pagination ont des contrats déterministes.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Servir la projection avec cursor, relecture et mises à jour sans créer d'historique bis. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `02-chat-event-projection`
- `03-direct-brain-text-ingress`

## Implementation Steps
1. Réutiliser les routes GET, autorisation et long-poll existants ou ajouter un adaptateur minimal filtré; aucun bus parallèle.
2. Reprendre depuis `next_cursor`, même quand pages filtrées vides ; gérer reconnexion et switch de conversation/Board avec invalidation du cache.
3. Fournir états `pending/failed` d'un tour sans créer de faux message Brain ; aligner sur IDs et correlation existants.
4. Limiter payloads, poll frequency, backpressure et fuite de texte ; ne pas exposer via route la timeline diagnostic complète.
5. Écrire tests Core/Control Center de pagination, replays, grande conversation et droits.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/runtime/conversation_event_view.py`
- `jarvis/runtime/control_center.py`
- `jarvis/core/conversation_event_query.py`
- `jarvis/domain/conversation_event_query.py`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.
- Avant code, exécuter `/caveman` et `/coding-guideline`.

## Automated Validation
- `qa-verification` systématique.
- `code-review` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- Tests ciblés et cas adverses : UI cliente peut reconstituer historique et flux avec un seul mécanisme canonique.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- UI cliente peut reconstituer historique et flux avec un seul mécanisme canonique.
- Rattrapage exact après offline, sans contenu diagnostique ni répétitions.
- Le canal fonctionnera sans Voice process.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Aucun geste humain exigé pour cette Slice sauf blocage identifié par le PM.
