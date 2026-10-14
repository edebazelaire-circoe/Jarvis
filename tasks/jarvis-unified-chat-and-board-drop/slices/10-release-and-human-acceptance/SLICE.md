# Slice 10 — Documentation finale, livraison et validation utilisateur

## Goal
Conclure la tâche par une preuve de fonctionnement et une validation humaine ciblée.

## Context
Une tâche de conception n'autorise aucune mise en route du Jarvis vivant. Le PM doit obtenir accord explicite avant un essai sur machine utilisateur.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Conclure la tâche par une preuve de fonctionnement et une validation humaine ciblée. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `09-integration-and-security-gates`

## Implementation Steps
1. Revalider main HEAD, inventaire des migrations, statut des travaux et retours QA ; préparer rollout/rollback sans effacer les données locales.
2. Mettre à jour contrats L2/L3 : docs conversation-events, boards, interaction-mode (distinction), artifacts, opérations, instructions écran et règles d'import.
3. Vérifier qu'un nouvel agent comprend sources, routes, config, sécurité, tests, dépôts, limites connues, et qu'aucun second journal chat n'existe.
4. Demander Human validation des flux voix/chat, UX et Board dans l'ordre après tests machines ; enregistrer résultat sans inventer leur accord.
5. Déclarer prête seulement si tous les gates bloquants et checks nécessaires sont satisfaits, sinon documenter le blocage précis.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `docs/conversation-events.md`
- `docs/boards.md`
- `docs/artifacts.md`
- `docs/OPERATIONS.md`
- `docs/local-data.md`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.

## Automated Validation
- `qa-verification` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- `agent-trace-analysis` avec vraies traces si l'exécution, les outils ou le runtime agent changent.
- Tests ciblés et cas adverses : P0 démontré en mode purement texte, avec même Brain/Session/Board et sans fuite de détails internes.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- P0 démontré en mode purement texte, avec même Brain/Session/Board et sans fuite de détails internes.
- Extra Board démontré sans régression ni confusion avec Chat.
- Contrats et test evidence à jour ; validation humaine reçue si requise, sinon statut en attente honnête.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Valider parcours Voice puis Chat puis Voice éventuel sur instance volontairement démarrée par utilisateur; confirmer maintien des sous-agents et absence de TTS texte.
- Approuver la lisibilité finale, les dépôts chat/Board et la documentation d'utilisation.


## Contrat Slice 00 (agent 0, 2026-10-14)

**Dépendances :** 09. **Palier QA :** standard (`qa-verification`, `runtime-validation` sur l'instance de l'utilisateur seulement avec son accord explicite dans la conversation en cours).

**Fichiers :** M `docs/chat.md` (passage en L3 : liens vers les tests de conformité de chaque règle), `docs/OPERATIONS.md` (réglages `JARVIS_UPLOAD_MAX_BYTES`, `JARVIS_CHAT_MAX_ATTACHMENTS`, lecture de `GET /api/chat/state`, diagnostics `core.voice_channel.*`, `core.brain.speech_withheld_text_channel`, `chat.turn.relayed`), `docs/SECURITY.md` (garde `/api/chat`, flux de téléversement, URL inertes, octroi `artifacts_root`), `docs/ARCHITECTURE.md` (canal vocal possédé par Core), `docs/local-data.md` (payloads `upload.*` sous `artifacts/`, aucune nouvelle base). Mise à jour de la colonne finale de `../../docs/05-documentation-levels.md`.

**Redémarrage :** les changements de Core, du Control Center et de Voice exigent un redémarrage du JARVIS de l'utilisateur. L'agent le **dit** et laisse l'utilisateur le faire ; il ne lance jamais `project jarvis restart` ni `python -m jarvis …` dans le dépôt principal. Aucune migration : rien à sauvegarder au-delà de la sauvegarde habituelle.

**Contrôles humains :** HV-JCHAT-10-01, HV-JCHAT-10-02 après machine QA complète ; HV-JCHAT-04-01, 06-01, 07-01 (07b), 08-01 regroupés dans la même séance si l'utilisateur le souhaite.

**Acceptation :** un nouvel agent retrouve, depuis `docs/chat.md`, chaque route, code, réglage, limite connue (8192 caractères, lien automatique au Board actif, accès `artifacts_root`, pas d'objet de scène) et test ; aucun second journal de chat n'existe (recherche dans le dépôt notée) ; résultats humains consignés sans invention.

**Ne pas toucher :** code produit (sauf correction documentaire), données de l'utilisateur.
