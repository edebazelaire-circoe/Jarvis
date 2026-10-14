# Slice 07 — Pièces jointes et drag-and-drop dans le chat

## Goal
Joindre des fichiers multiples au message Brain sans imposer des bornes produit arbitraires.

## Context
Le registre Artifacts et les Contexts existent; le Brain peut ou non supporter des modalités selon CLI, à mesurer avant implémentation.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Joindre des fichiers multiples au message Brain sans imposer des bornes produit arbitraires. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `01-canonical-contracts`
- `03-direct-brain-text-ingress`
- `06-chat-panel-and-composer`

## Implementation Steps
1. Construire endpoint authentifié de stage/upload selon sécurité Artifact (`JARVIS_DATA_ROOT`, payloads atomiques, types déclarés, ACL Session/Board, nom défensif, pas de symlinks/traversal).
2. Associer les références de fichiers au tour Brain par représentation structurée canonique et uniquement après upload réussi ; adapter au support réel des agents, annoncer les formats non supportés et ne pas prétendre analyser un fichier non lu.
3. Ajouter bouton attacher et dropzone dans le panneau avec liste, états progress/ready/failed, retry sûr, plusieurs fichiers, suppression avant envoi, taille/format erreurs humaines claires.
4. Établir bornes techniques configurables, vérifications MIME/ext/quotas/auth et observabilité sans enregistrer les octets dans les événements conversationnels.
5. Tester race abandon, double drop, gros fichier, image, PDF, caractères Unicode, environnement sans Voice, changement Board/Session avant envoi.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/core/artifact_service.py`
- `jarvis/domain/artifacts.py`
- `jarvis/adapters/artifact_payloads.py`
- `jarvis/runtime/control_center.html`
- `jarvis/runtime/workspace_relay.py`

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
- `agent-trace-analysis` avec vraies traces si l'exécution, les outils ou le runtime agent changent.
- Tests ciblés et cas adverses : Fichier(s) réellement accessibles au Brain autorisé et liés au bon contexte.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Fichier(s) réellement accessibles au Brain autorisé et liés au bon contexte.
- Aucun fichier non pris en charge annoncé comme traité ; aucune perte silencieuse ni double Artifact.
- Sûreté chemins/récupération et absence de fuites dans logs/événements.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Tester sélection et dépôt de deux fichiers de types différents dans un tour de Chat et vérifier la prise en compte par Brain.

## Note de compatibilité

Si le Brain actif ne sait pas consommer un format (ex. image vs document), ne pas prétendre qu'un chemin local passé en texte suffit. Définir explicitement support par agent, conversion/import sécurisé si existant, ou feedback « non pris en charge ». Toute extension de capacité doit être testée séparément.
