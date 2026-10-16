# Slice 01 — Contrats produit, événements, canal et attachments

## Goal
Définir des contrats testables avant tout comportement nouveau et verrouiller les propriétaires.

## Context
Les contrats préexistants couvrent conversation events, Boards/Sessions, artifacts et modes; le chat ajoute le filtrage, la source d'entrée texte et une exclusivité de canal.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Définir des contrats testables avant tout comportement nouveau et verrouiller les propriétaires. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `00-project-manager`

## Implementation Steps
1. Cartographier les routes et ownership de tour, source `BrainTurnSource`, publication Brain et Core/Control Center; ne jamais relier le chat au Voice bridge.
2. Définir normative allowlist `user.transcript.accepted` + `brain.message.published`, ordre/duplication, Board scope et échecs/pending sans logs du sous-agent ni réflexes.
3. Définir états Voice actif, arrêt demandé, Voice arrêté, voix réactivée ; authentification/erreurs des envois concurrents ; séparation de `InteractionMode`.
4. Spécifier sérialisation de références attachments (types réellement utilisables par Brain), garanties de stockage et permission, URL comme référence et événements éventuels; décider si adaptation modèle Artifact est nécessaire.
5. Documenter les routes et schémas compatibles, limites techniques configurables et protections contre fichiers arbitraires/URL non fiables.
6. Créer tests de contrat/fixtures avant Slice 02–08. Si choix produit résiduel réel, bloquer et escalader au PM.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `docs/conversation-events.md`
- `docs/boards.md`
- `docs/interaction-mode.md`
- `docs/artifacts.md`
- `jarvis/domain/v2.py`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.

## Automated Validation
- `qa-verification` systématique.
- Tests ciblés et cas adverses : Un contrat unique et vérifiable pour projection, ingress, canal et ressources.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Un contrat unique et vérifiable pour projection, ingress, canal et ressources.
- Les concepts L0 de `docs/05-documentation-levels.md` atteignent L2 avant implementation.
- Incompatibilités avec les deux autres vues (timeline debug, workspace inspector) traitées.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Aucun geste humain exigé pour cette Slice sauf blocage identifié par le PM.

## Contrat Slice 00 (agent 0, 2026-10-14)

**Nature :** documentation normative et fixture, **aucun code produit**. Source contraignante : `../../docs/06-resolved-architecture.md` ; cette Slice la transcrit en contrats du dépôt (L2) sans la rediscuter. Un désaccord trouvé dans le code remonte à l'agent 0 avant toute écriture.

**Dépendances :** 00. **Palier QA :** standard (`qa-verification` ; pas de `code-review` sans code).

**Fichiers :**
- N `docs/chat.md` : contrat L2 du Chat — projection (types montrés, promotion `uncertain`, repli, statut `brain.turn.failed`, portée binding), paramètre `projection=chat`, envoi (`POST /api/chat/turns` → `brain-turns` `source=text`, ordre des gardes, idempotence `chat:<client_request_id>`), disposition texte (`text_channel`), canal vocal (rapports, demande, machine d'état, délais 5 s et 10 s), pièces jointes (route `PUT /v1/uploads/{client_upload_id}`, bornes configurables, reniflage, `brain_readable`, bloc du brief, `artifacts_root`), dépôt Board (fichier, URL inerte), tableau des codes d'erreur, limites connues (8192 caractères, lien automatique au Board actif).
- M `docs/conversation-events.md` : paragraphe court dans *Query and live API* annonçant `projection=chat` (renvoi à `docs/chat.md`) ; note sur la clé d'attribut `attachment_count` de `user.transcript.accepted` (ajoutée par 07).
- M `docs/interaction-mode.md` : un paragraphe « Canal vocal / chat » qui dit que `VoiceChannelService` n'est pas `InteractionMode` ni `OutputDisposition`.
- M `docs/artifacts.md` : natures `upload` et `link` et provenances `chat_attachment` / `board_drop` (contrat ; le code suit en 07 et 08).
- M `docs/boards.md` : renvoi vers `docs/chat.md` pour le dépôt sur Board.
- N `tests/fixtures/chat_projection/cases.json` : au moins 12 cas d'entrée (événements stockés encodés exactement comme `encode_stored_event`) et leur sortie attendue — vide ; user `addressed` ; user `uncertain` promu ; `uncertain` récusé (jamais promu) ; republication identique repliée ; A/B/A gardé ; `brain.turn.failed` sur tour utilisateur ; `brain.turn.failed` sur tour système ignoré ; `mouth.*`, `subagent.*`, `brain.speech.requested` ignorés ; séquences non contiguës ; rejeu d'une page (même `event_id`) ; deux conversations.

**Tests à ajouter :** aucun test Python ; le fixture est consommé par 02. Vérifier qu'il se charge en JSON strict (`python -c "import json; json.load(open(...))"` noté au LOG).

**Acceptation :** `docs/chat.md` reprend chaque route, charge utile, code et état de `06-resolved-architecture.md` sans contradiction ; les liens internes résolvent ; aucun texte de contrat existant n'est réécrit hors des ajouts listés ; le fixture couvre les 12 cas.

**Ne pas toucher :** tout fichier sous `jarvis/` ou `tests/unit/` ; `control_center_timeline.js` ; les migrations.
