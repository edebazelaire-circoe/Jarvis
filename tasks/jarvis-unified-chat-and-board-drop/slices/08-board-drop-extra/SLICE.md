# Slice 08 — Extra : dépôt de fichiers, images et URL sur le Board

## Goal
Permettre à l'utilisateur d'enrichir un Board par drop direct dans la scène, sans composer de message.

## Context
Les Boards, Artifacts et liens Board existent déjà; la scène constellation possède ses propres interactions. Réutiliser leurs contrats plutôt que dessiner un stockage de fichiers bis.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Permettre à l'utilisateur d'enrichir un Board par drop direct dans la scène, sans composer de message. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`
- `07-chat-attachments`

## Implementation Steps
1. Définir zones de drop acceptées (Board actif, scène/canevas) et feedback sans interférer avec les mouvements/clicks des objets existants.
2. Pour un fichier/image, réutiliser ingestion Artifact et lier ressource au Board actif avec provenance; pour une URL, enregistrer référence inerte/metadata validées et ne pas fetcher implicitement.
3. Afficher une ressource trouvable sur le Board et dans l'inspecteur Workspace; si l'objet scène requiert un contrat, valider cette projection séparément et sans remodéliser le graphe.
4. Supporter erreurs, annulation, duplicats, multi-drop et switch Board durant le transfert ; garantir aucune création de message chat, pas de déclenchement Brain auto.
5. Tests Board A vs B, image, document, URL, persistence après refresh, scoping, compatibilité avec inspecteur et scene.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/runtime/control_center_scene_interact.js`
- `jarvis/runtime/control_center_workspace.js`
- `jarvis/domain/board_artifact_links.py`
- `jarvis/core/artifact_service.py`
- `docs/scene-model.md`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.
- Avant code, exécuter `/caveman` et `/coding-guideline`.
- Frontend : exécuter `/impeccable`, affecter un agent Claude si cette règle est supportée par le host.

## Automated Validation
- `qa-verification` systématique.
- `code-review` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- Tests ciblés et cas adverses : Les dépôts sont reliés au **Board ciblé** et consultables après reconnexion.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Les dépôts sont reliés au **Board ciblé** et consultables après reconnexion.
- Pas de nouvelle conversation créée et aucune URL distante automatiquement lue.
- Fonction extra isolée, ne bloque pas l'usage chat P0.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Déposer fichier, image et URL dans un Board puis constater les trois ressources visibles et réutilisables après changement/reprise du Board.
