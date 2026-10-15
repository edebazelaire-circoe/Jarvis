# Slice 00 — Readiness, audit aveugle et orchestration

## Goal
Accepter une base d'exécution vérifiée et affecter les tâches correctement.

## Context
Le dépôt GitHub et les dossiers Drive contiennent d'autres chantiers Jarvis. La lecture statique de ce handoff ne constitue pas une validation du HEAD réel.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Accepter une base d'exécution vérifiée et affecter les tâches correctement. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
Aucune. Exécuter cette Slice en premier, en qualité de Project Manager, sans délégation.

## Implementation Steps
1. Audit indépendant **à l'aveugle**, à partir du but et du dépôt actuel, AVANT de lire `docs/05-documentation-levels.md` ; vérifier contrats, tests, chemins, état des tâches, branches, qualité de la base et vocabulaire Workspace Task Type.
2. Réconcilier ensuite les résultats du blind audit avec le handoff ; établir écarts et décisions divergentes.
3. Publier **exactement** un statut `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT` ou `HUMAN_DECISION_REQUIRED`, sa preuve, et les dépendances à jour. Interdire toute distribution en dessous de READY.
4. Corriger planning, données obsolètes, noms, ordre et besoin de découpage ; ne pas éditer de code produit. Vérifier fraîcheur juste avant **chaque** dispatch.
5. Attribuer à chaque Slice un Task Type existant et un Work Agent unique; ne jamais inventer le type ni choisir `code` par défaut.
6. Orchestrer les QA de chaque Slice : `qa-verification`; `code-review` si code ; `runtime-validation` si UI/runtime ; `agent-trace-analysis` si outils/prompts/routage/agent et traces réelles ; arbitrer les findings et bloquer les régressions.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `README.md`
- `slices/TODO.md`
- `docs/05-documentation-levels.md`
- `docs/01-decision-log.md`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.

## Automated Validation
- `qa-verification` systématique.
- Tests ciblés et cas adverses : Le blind audit est daté avec HEAD et constats indépendants.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Le blind audit est daté avec HEAD et constats indépendants.
- Statut readiness unique explicité, Task Types légitimes trouvés ou blocage signalé.
- Aucun dispatch d'implémentation avant READY et aucun code produit édité par PM.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Décision humaine requise uniquement en cas de conflit durable ou de contrat produit impossible à déterminer à partir du code.

## Readiness protocol (non négociable)

1. **Audit aveugle** : inspecter HEAD, tests, modules, contrats, tâches concurrentes et Workspace Task Types à partir des objectifs seulement, **avant** la lecture de nos estimations de niveaux documentaires.
2. **Réconciliation** : confronter l'audit indépendant avec l'ensemble du handoff, corriger informations périmées, dépendances et plans.
3. **Verdict unique** : `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`, `HUMAN_DECISION_REQUIRED`. Hors READY, **aucune distribution**.
4. **Réparation autorisée** : découper, ajouter, reclasser, superséder des Slices et enrichir leurs contrats, sans modifier le code du produit.
5. **Vérification fraîcheur ciblée** immédiatement avant chaque dispatch : HEAD, autres agents, conflits de fichiers, contrats, baseline.
6. **QA** : baseline `qa-verification` pour toute Slice implémentée ; `code-review` pour code ; `runtime-validation` pour comportement runtime/UI ; `agent-trace-analysis` sur traces réelles pour prompt/outils/routage/runtime agent. Les QA donnent constats ; PM décide approbation, rework, nouvelle Slice, Issue ou escalade. Régression induite bloquante, jamais Issue.
7. Human checks **après** QA machine maximale, avec justificatif ; aucune validation fictive.
