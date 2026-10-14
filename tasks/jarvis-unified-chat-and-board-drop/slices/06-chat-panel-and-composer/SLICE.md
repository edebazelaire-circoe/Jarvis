# Slice 06 — Onglet bas droit, panneau et dialogue texte

## Goal
Livrer le premier parcours Chat complet sans pièces jointes, sobre et utilisable au clavier.

## Context
Le Control Center possède déjà dock, `.panel`, z-index, scène, thèmes Cosmos et chronologie plein écran ; pas de refonte parallèle.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Livrer le premier parcours Chat complet sans pièces jointes, sobre et utilisable au clavier. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `04-voice-chat-channel-state`
- `05-chat-read-sync-relay`

## Implementation Steps
1. Ajouter bouton Chat en bas à droite et drawer latéral horizontal compatible dock/scene, sans casser les overlays existants.
2. Rendre bulles Utilisateur et Brain uniquement, lecture vocale en direct, scroll conservé, reprise persistée, statut attente/erreur clairement distinct d'un message.
3. Saisie multiligne, envoyer Enter et Shift+Enter, bouton envoyer, focus, notification si Voice actif ; bouton « Passer au chat » avec transition et grille désactivée.
4. Relier submit exclusivement à Slice 03 et flux à Slice 05 ; ne jamais écrire un message définitif avant admission confirmée ; éviter double submit et doublons événements.
5. Tester desktop/écrans étroits, clavier/lecteur écran, JS pur si utile, navigateur automatisé, emplacement lorsque Studio/Board/Live ouvert.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_live.js`
- `jarvis/runtime/control_center_timeline.js`
- `tests/unit/test_control_center_timeline_js.py`

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
- Tests ciblés et cas adverses : Un utilisateur peut uniquement utiliser Jarvis au clavier sur la même Session.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Un utilisateur peut uniquement utiliser Jarvis au clavier sur la même Session.
- Voice actif : chat lisible, input inerte et message explicatif, action de bascule.
- Compatibilité visuelle/focus/z-index prouvée avec menus et scène existants.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Valider ergonomie du panneau bas droite, bulles, focus, menus et accès au transcript détaillé sur l'écran habituel.
